//! Authenticated Windows portable replacement. Runs outside the installation.
use fs2::FileExt;
use semver::Version;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};
use zip::ZipArchive;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const MAX_UNPACKED: u64 = 2 * 1024 * 1024 * 1024;

#[derive(Debug)]
struct Request {
    package: PathBuf,
    hash: String,
    install: PathBuf,
    parent_pid: u32,
    target: String,
    version: Version,
    ready: PathBuf,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("Portable update failed; previous installation retained: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let arguments: Vec<_> = std::env::args_os().skip(1).collect();
    if arguments.len() != 7 {
        return Err("Expected package, signed hash, installation, parent process, target, version and readiness path".into());
    }
    let request = Request {
        package: PathBuf::from(&arguments[0]).canonicalize()?,
        hash: arguments[1].to_string_lossy().into_owned(),
        install: PathBuf::from(&arguments[2]).canonicalize()?,
        parent_pid: arguments[3].to_string_lossy().parse()?,
        target: arguments[4].to_string_lossy().into_owned(),
        version: Version::parse(&arguments[5].to_string_lossy())?,
        ready: PathBuf::from(&arguments[6]),
    };
    if !request.install.is_dir()
        || request.install.parent().is_none()
        || request.install.parent() == Some(request.install.as_path())
    {
        return Err("Invalid portable installation directory".into());
    }
    verify_target(&request.target)?;
    verify_hash(&request.package, &request.hash)?;
    let parent = request
        .install
        .parent()
        .ok_or("Missing installation parent")?;
    let lock_name = format!(
        ".encap-install-{:x}.lock",
        Sha256::digest(request.install.to_string_lossy().to_uppercase().as_bytes())
    );
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(parent.join(lock_name))?;
    lock.try_lock_exclusive()?;

    let nonce = format!(
        "{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos()
    );
    let stage = parent.join(format!(".encap-stage-{nonce}"));
    let backup = parent.join(format!(".encap-backup-{nonce}"));
    let journal = parent.join(format!(".encap-recovery-{nonce}.json"));
    fs::create_dir(&stage)?;
    let mut moved = false;
    let operation = (|| -> Result<()> {
        let mut managed = extract(&request.package, &stage)?;
        verify_identity(&request, &stage)?;
        verify_authenticode(&request.install, &stage)?;
        verify_runtime(&stage)?;
        fs::write(&request.ready, b"validated")?;
        wait_parent(request.parent_pid)?;
        collect_old_managed(&request.install, &mut managed)?;
        preserve_user_files(&request.install, &request.install, &stage, &managed)?;
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&journal)?;
        serde_json::to_writer(
            &mut file,
            &serde_json::json!({
                "installation": request.install, "previous": backup, "staged": stage
            }),
        )?;
        file.flush()?;
        file.sync_all()?;
        fs::rename(&request.install, &backup)?;
        moved = true;
        fs::rename(&stage, &request.install)?;
        let acknowledgement = request.ready.with_file_name("launched");
        let mut child = Command::new(request.install.join("EnCap.exe"))
            .env("ENCAP_UPDATE_STARTUP_ACK", &acknowledgement)
            .spawn()?;
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            if acknowledgement.exists() {
                break;
            }
            if child.try_wait()?.is_some() {
                return Err("Updated application exited before opening its UI".into());
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                return Err("Updated application did not acknowledge startup".into());
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        fs::remove_file(&journal)?;
        Ok(())
    })();
    if let Err(error) = operation {
        if moved {
            if request.install.exists() {
                let failed = parent.join(format!(".encap-failed-{nonce}"));
                fs::rename(&request.install, failed)?;
            }
            fs::rename(&backup, &request.install)?;
            let _ = Command::new(request.install.join("EnCap.exe")).spawn();
        }
        if stage.exists() {
            let _ = fs::remove_dir_all(&stage);
        }
        return Err(error);
    }
    Ok(())
}

fn verify_hash(path: &Path, expected: &str) -> Result<()> {
    let mut input = File::open(path)?;
    let mut hash = Sha256::new();
    io::copy(&mut input, &mut hash)?;
    let actual = format!("{:x}", hash.finalize());
    if !actual.eq_ignore_ascii_case(expected) {
        return Err("Update bytes changed after authentication".into());
    }
    Ok(())
}

fn verify_target(target: &str) -> Result<()> {
    #[cfg(target_arch = "x86_64")]
    let native = "windows-x64";
    #[cfg(target_arch = "aarch64")]
    let native = "windows-arm64";
    #[cfg(not(any(target_arch = "x86_64", target_arch = "aarch64")))]
    let native = "unsupported";
    if target != native {
        return Err("Wrong target update".into());
    }
    Ok(())
}

fn safe_name(name: &str) -> Result<PathBuf> {
    if name.is_empty()
        || name.starts_with('/')
        || name.contains('\\')
        || name.contains(':')
        || name.contains('\0')
        || name
            .split('/')
            .any(|segment| segment.is_empty() || segment == "." || segment == "..")
    {
        return Err("Unsafe portable package entry".into());
    }
    let path = Path::new(name);
    if path
        .components()
        .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("Unsafe portable package entry".into());
    }
    Ok(path.to_path_buf())
}

fn extract(package: &Path, stage: &Path) -> Result<HashSet<String>> {
    let mut archive = ZipArchive::new(File::open(package)?)?;
    let mut managed = HashSet::new();
    let mut total = 0u64;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        let name = entry.name().to_string();
        let relative = safe_name(name.trim_end_matches('/'))?;
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err("Portable package contains a symlink".into());
        }
        let key = relative.to_string_lossy().to_lowercase();
        if !managed.insert(key) {
            return Err("Duplicate package entry".into());
        }
        total = total
            .checked_add(entry.size())
            .ok_or("Oversized portable package")?;
        if total > MAX_UNPACKED {
            return Err("Oversized portable package".into());
        }
        let destination = stage.join(relative);
        if entry.is_dir() {
            fs::create_dir_all(destination)?;
            continue;
        }
        fs::create_dir_all(destination.parent().ok_or("Invalid package entry")?)?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(destination)?;
        io::copy(&mut entry, &mut output)?;
        output.sync_all()?;
    }
    Ok(managed)
}

fn read_config(directory: &Path) -> Result<Value> {
    Ok(serde_json::from_slice(&fs::read(
        directory.join("update-config.json"),
    )?)?)
}
fn config_text<'a>(config: &'a Value, name: &str) -> Result<&'a str> {
    config
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("Missing update identity: {name}").into())
}
fn verify_identity(request: &Request, stage: &Path) -> Result<()> {
    let new = read_config(stage)?;
    let old = read_config(&request.install)?;
    if config_text(&new, "target")? != request.target
        || Version::parse(config_text(&new, "version")?)? != request.version
        || config_text(&new, "application_id")? != "com.tlolabs.encap"
        || config_text(&new, "repository")? != "tlolabs/encap"
        || config_text(&new, "channel")? != "stable"
    {
        return Err("Wrong package identity, version or target".into());
    }
    if request.version <= Version::parse(config_text(&old, "version")?)? {
        return Err("Update must advance the installed version".into());
    }
    if config_text(&new, "public_key")? != config_text(&old, "public_key")? {
        return Err("Signing key rotation requires a bridge installer".into());
    }
    Ok(())
}

fn collect_old_managed(install: &Path, managed: &mut HashSet<String>) -> Result<()> {
    let path = install.join("portable-package-files.json");
    if !path.exists() {
        return Ok(());
    }
    let entries: Vec<String> = serde_json::from_slice(&fs::read(path)?)?;
    for entry in entries {
        managed.insert(entry.to_lowercase());
    }
    Ok(())
}
fn preserve_user_files(
    root: &Path,
    source: &Path,
    destination: &Path,
    managed: &HashSet<String>,
) -> Result<()> {
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let old = entry.path();
        let metadata = fs::symlink_metadata(&old)?;
        if metadata.file_type().is_symlink() {
            return Err("Linked installation paths require a manual update".into());
        }
        #[cfg(windows)]
        if std::os::windows::fs::MetadataExt::file_attributes(&metadata) & 0x400 != 0 {
            return Err("Linked installation paths require a manual update".into());
        }
        let new = destination.join(entry.file_name());
        if metadata.is_dir() {
            fs::create_dir_all(&new)?;
            preserve_user_files(root, &old, &new, managed)?;
        } else {
            let relative = old.strip_prefix(root).unwrap_or(&old);
            if !managed.contains(&relative.to_string_lossy().to_lowercase()) && !new.exists() {
                fs::copy(&old, &new)?;
            }
        }
    }
    Ok(())
}

#[cfg(windows)]
fn verify_authenticode(install: &Path, stage: &Path) -> Result<()> {
    let script = "$ErrorActionPreference='Stop'; $old=Get-AuthenticodeSignature -LiteralPath $env:ENCAP_OLD_EXE; if($old.Status -ne 'Valid' -or !$old.TimeStamperCertificate){throw 'Invalid installed signature'}; $subject=$old.SignerCertificate.Subject; Get-ChildItem -LiteralPath $env:ENCAP_VERIFY_DIR -Recurse -Filter '*.exe' | ForEach-Object { $s=Get-AuthenticodeSignature -LiteralPath $_.FullName; if($s.Status -ne 'Valid' -or !$s.TimeStamperCertificate -or $s.SignerCertificate.Subject -cne $subject){throw 'Invalid update signature, timestamp or signer'} }";
    let status = Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-Command", script])
        .env("ENCAP_OLD_EXE", install.join("EnCap.exe"))
        .env("ENCAP_VERIFY_DIR", stage)
        .status()?;
    if !status.success() {
        return Err("Authenticode verification failed".into());
    }
    Ok(())
}
#[cfg(not(windows))]
fn verify_authenticode(_install: &Path, _stage: &Path) -> Result<()> {
    Err("Portable installation is supported only on Windows".into())
}

fn verify_runtime(stage: &Path) -> Result<()> {
    let status = Command::new(stage.join("encap-engine.exe"))
        .arg("validate-tools")
        .env("PATH", "")
        .stdout(Stdio::null())
        .status()?;
    if !status.success() {
        return Err("New Core runtime failed validation".into());
    }
    Ok(())
}

#[cfg(windows)]
fn wait_parent(pid: u32) -> Result<()> {
    use windows_sys::Win32::Foundation::{CloseHandle, WAIT_OBJECT_0, WAIT_TIMEOUT};
    use windows_sys::Win32::System::Threading::{OpenProcess, WaitForSingleObject};
    const SYNCHRONIZE_ACCESS: u32 = 0x0010_0000;
    let handle = unsafe { OpenProcess(SYNCHRONIZE_ACCESS, 0, pid) };
    if handle.is_null() {
        return Ok(());
    }
    let result = unsafe { WaitForSingleObject(handle, 120_000) };
    unsafe { CloseHandle(handle) };
    if result == WAIT_OBJECT_0 {
        Ok(())
    } else if result == WAIT_TIMEOUT {
        Err("Old application did not exit within two minutes".into())
    } else {
        Err("Could not wait for old application".into())
    }
}
#[cfg(not(windows))]
fn wait_parent(_pid: u32) -> Result<()> {
    Err("Portable installation is supported only on Windows".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unsafe_archive_names() {
        for value in [
            "../escape",
            "a/../escape",
            "a\\b",
            "/absolute",
            "C:drive",
            "a/./b",
            "",
        ] {
            assert!(safe_name(value).is_err(), "{value}");
        }
        assert!(safe_name("nested/EnCap.exe").is_ok());
    }
    #[test]
    fn hash_rejects_changed_bytes() {
        let path = std::env::temp_dir().join(format!("encap-portable-test-{}", std::process::id()));
        fs::write(&path, b"package").unwrap();
        assert!(verify_hash(&path, &format!("{:x}", Sha256::digest(b"package"))).is_ok());
        assert!(verify_hash(&path, &format!("{:x}", Sha256::digest(b"different"))).is_err());
        fs::remove_file(path).unwrap();
    }
}
