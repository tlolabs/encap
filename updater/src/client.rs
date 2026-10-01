//! Blocking helper API; native UIs run it off their UI thread.
use crate::*;
use std::{
    fs,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

fn save_state(path: &Path, state: &State) -> Result<()> {
    let mut file =
        tempfile::NamedTempFile::new_in(path.parent().ok_or("Missing state directory")?)?;
    serde_json::to_writer(&mut file, state)?;
    file.as_file().sync_all()?;
    file.persist(path)?;
    Ok(())
}
fn state_path(id: &str) -> Result<PathBuf> {
    let base = if cfg!(windows) {
        PathBuf::from(std::env::var("LOCALAPPDATA")?)
    } else if let Some(path) = std::env::var_os("XDG_STATE_HOME") {
        PathBuf::from(path)
    } else {
        PathBuf::from(std::env::var("HOME")?).join(".local/state")
    };
    if !base.is_absolute() {
        return Err("Updater state directory must be absolute".into());
    }
    let directory = base.join(id).join("updates");
    fs::create_dir_all(&directory)?;
    Ok(directory.join("state.json"))
}
#[cfg(not(windows))]
fn normalized_version(value: &str) -> Result<String> {
    let numbers: Vec<_> = value
        .trim()
        .split(|c: char| !c.is_ascii_digit())
        .take(3)
        .collect();
    if numbers.is_empty() || numbers.iter().any(|s| s.is_empty()) {
        return Err("Invalid OS version".into());
    }
    let mut numbers = numbers
        .iter()
        .map(|s| s.parse::<u64>())
        .collect::<std::result::Result<Vec<_>, _>>()?;
    while numbers.len() < 3 {
        numbers.push(0);
    }
    Ok(format!("{}.{}.{}", numbers[0], numbers[1], numbers[2]))
}
#[cfg(not(windows))]
fn command_output(program: &str, args: &[&str]) -> Result<String> {
    let result = std::process::Command::new(program).args(args).output()?;
    if !result.status.success() {
        return Err("Cannot determine operating system compatibility".into());
    }
    Ok(String::from_utf8(result.stdout)?.trim().to_owned())
}
fn platform_versions() -> Result<(String, Option<String>)> {
    #[cfg(windows)]
    {
        #[repr(C)]
        struct VersionInfo {
            size: u32,
            major: u32,
            minor: u32,
            build: u32,
            platform: u32,
            service: [u16; 128],
        }
        #[link(name = "ntdll")]
        extern "system" {
            fn RtlGetVersion(info: *mut VersionInfo) -> i32;
        }
        let mut info = VersionInfo {
            size: std::mem::size_of::<VersionInfo>() as u32,
            major: 0,
            minor: 0,
            build: 0,
            platform: 0,
            service: [0; 128],
        };
        // RtlGetVersion writes the fixed ABI structure supplied above; no borrowed pointers escape.
        if unsafe { RtlGetVersion(&mut info) } != 0 {
            return Err("Cannot determine Windows version".into());
        }
        Ok((
            format!("{}.{}.{}", info.major, info.minor, info.build),
            None,
        ))
    }
    #[cfg(target_os = "linux")]
    {
        let kernel = normalized_version(&command_output("/usr/bin/uname", &["-r"])?)?;
        let libc = command_output("/usr/bin/getconf", &["GNU_LIBC_VERSION"])?;
        Ok((
            kernel,
            Some(normalized_version(
                libc.split_whitespace()
                    .last()
                    .ok_or("Missing glibc version")?,
            )?),
        ))
    }
    #[cfg(not(any(windows, target_os = "linux")))]
    {
        Ok((
            normalized_version(&command_output("/usr/bin/sw_vers", &["-productVersion"])?)?,
            None,
        ))
    }
}
pub fn http_client() -> Result<reqwest::blocking::Client> {
    Ok(reqwest::blocking::Client::builder()
        .https_only(true)
        .connect_timeout(Duration::from_secs(15))
        .timeout(Duration::from_secs(900))
        .redirect(reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 5 {
                return attempt.error("Too many redirects");
            }
            match attempt.url().host_str() {
                Some(
                    "github.com"
                    | "release-assets.githubusercontent.com"
                    | "objects.githubusercontent.com",
                ) if attempt.url().scheme() == "https" => attempt.follow(),
                _ => attempt.error("Untrusted update redirect"),
            }
        }))
        .user_agent("TLO-Updater/1")
        .build()?)
}
pub fn discover(client: &reqwest::blocking::Client, config: &Config) -> Result<Manifest> {
    let mut bytes = Vec::new();
    client
        .get(format!(
            "https://github.com/{}/releases/latest/download/update-manifest.json",
            config.repository
        ))
        .timeout(Duration::from_secs(30))
        .send()?
        .error_for_status()?
        .take(MANIFEST_LIMIT + 1)
        .read_to_end(&mut bytes)?;
    verify(&bytes, config)
}
/// Existing AppImage adapter: stage on the same filesystem, authenticate all bytes,
/// preserve the prior image, then atomically rename. Never execute a staged image.
/// A failed download/verification/rename leaves the currently running image usable.
#[cfg(unix)]
pub fn install_appimage(source: impl Read, asset: &Asset, target: &Path) -> Result<PathBuf> {
    use std::os::unix::fs::{MetadataExt, PermissionsExt};
    let original = fs::symlink_metadata(target)?;
    if !target.is_absolute()
        || !original.file_type().is_file()
        || original.nlink() != 1
        || original.mode() & 0o6000 != 0
    {
        return Err(
            "AppImage location needs a manual update (link, special file or privileged image)"
                .into(),
        );
    }
    let parent = target.parent().ok_or("Missing AppImage directory")?;
    let mut staged = tempfile::NamedTempFile::new_in(parent)?;
    download(source, &mut staged, asset)?;
    staged
        .as_file()
        .set_permissions(fs::Permissions::from_mode(original.mode() & 0o777))?;
    staged.as_file().sync_all()?;
    let mut previous = tempfile::Builder::new()
        .prefix("tlo-previous-")
        .suffix(".AppImage")
        .tempfile_in(parent)?;
    let mut original_file = fs::File::open(target)?;
    if original_file.metadata()?.ino() != original.ino() {
        return Err("AppImage changed during update".into());
    }
    std::io::copy(&mut original_file, &mut previous)?;
    previous
        .as_file()
        .set_permissions(fs::Permissions::from_mode(original.mode() & 0o777))?;
    previous.as_file().sync_all()?;
    let (_, backup) = previous.keep()?;
    fs::File::open(parent)?.sync_all()?;
    let current = fs::symlink_metadata(target)?;
    if current.ino() != original.ino()
        || current.dev() != original.dev()
        || current.len() != original.len()
        || current.mtime() != original.mtime()
    {
        return Err("AppImage changed during update; original retained".into());
    }
    staged.persist(target)?;
    fs::File::open(parent)?.sync_all()?;
    Ok(backup)
}
pub fn run(application_id: &str, repository: &str, version: &str) -> Result<()> {
    let directory = std::env::current_exe()?
        .parent()
        .ok_or("Missing executable directory")?
        .to_owned();
    let config: Config = serde_json::from_slice(&fs::read(directory.join("update-config.json"))?)?;
    validate_config(&config)?;
    if config.application_id != application_id
        || config.repository != repository
        || config.version != version
    {
        return Err("Installed application/update configuration identity mismatch".into());
    }
    let (platform, arch, _) = target_parts(&config.target)?;
    if platform != std::env::consts::OS || arch != std::env::consts::ARCH {
        return Err("Installed updater architecture/platform mismatch".into());
    }
    let command = std::env::args().nth(1).unwrap_or_else(|| "check".into());
    if !["check", "check-auto", "download", "install-appimage"].contains(&command.as_str()) {
        return Err("Unknown update command".into());
    }
    let path = state_path(application_id)?;
    // OS locks release automatically after a crash; serialize state and installation.
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path.with_extension("lock"))?;
    fs2::FileExt::try_lock_exclusive(&lock)
        .map_err(|_| "Another update operation is in progress")?;
    let mut state: State = match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice(&bytes)?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => State::default(),
        Err(error) => return Err(error.into()),
    };
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    if command == "check-auto" && !state.due(now) {
        println!("{}", serde_json::json!({"available":false,"skipped":true}));
        return Ok(());
    }
    state.last_attempt = now;
    save_state(&path, &state)?;
    let client = http_client()?;
    let manifest = discover(&client, &config)?;
    let (os, libc) = platform_versions()?;
    let asset = select(
        &manifest,
        &config,
        state.highest_version.as_deref(),
        &os,
        libc.as_deref(),
    )?;
    if state
        .highest_version
        .as_deref()
        .map(stable_version)
        .transpose()?
        .is_none_or(|old| old < stable_version(&manifest.version).expect("already validated"))
    {
        state.highest_version = Some(manifest.version.clone());
    }
    state.last_success = now;
    save_state(&path, &state)?;
    if command.starts_with("check") {
        println!(
            "{}",
            serde_json::json!({"available":asset.is_some(),"version":manifest.version,"release_notes_url":manifest.release_notes_url,"manual_migration":manifest.migration!="none"})
        );
        return Ok(());
    }
    let asset = asset.ok_or("No compatible newer stable update is available")?;
    if manifest.migration != "none" {
        return Err(format!(
            "Manual migration required. See {}",
            manifest.release_notes_url
        )
        .into());
    }
    let response = client.get(&asset.url).send()?.error_for_status()?;
    if command == "install-appimage" {
        #[cfg(target_os = "linux")]
        {
            if asset.format != "AppImage" {
                return Err("This installation needs the system package manager".into());
            }
            let target = PathBuf::from(std::env::var("APPIMAGE").map_err(|_| "Automatic replacement needs a writable AppImage; download the verified package for manual installation")?);
            let backup = install_appimage(response, asset, &target)?;
            println!(
                "{}",
                serde_json::json!({"installed":true,"version":manifest.version,"backup":backup})
            );
        }
        #[cfg(not(target_os = "linux"))]
        {
            return Err("AppImage installation is only supported on Linux".into());
        }
    } else {
        let directory = tempfile::Builder::new().prefix("tlo-update-").tempdir()?;
        let path = directory.path().join(&asset.filename);
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        download(response, &mut file, asset)?;
        file.sync_all()?;
        let _ = directory.keep();
        println!(
            "{}",
            serde_json::json!({"path":path,"version":manifest.version,"sha256":asset.sha256,"target":config.target,"application_id":application_id})
        );
    }
    Ok(())
}
