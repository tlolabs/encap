//! Shared stable release policy. No application/media dependencies and no telemetry.
use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use ring::signature::{UnparsedPublicKey, ED25519};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    error::Error,
    io::{Read, Write},
};
pub mod client;
pub type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub const MANIFEST_LIMIT: u64 = 1024 * 1024;
pub const CHECK_INTERVAL: u64 = 24 * 60 * 60;
pub const RETRY_INTERVAL: u64 = 60 * 60;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Config {
    pub application_id: String,
    pub repository: String,
    pub version: String,
    pub channel: String,
    pub target: String,
    pub public_key: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Asset {
    pub url: String,
    pub filename: String,
    pub size: u64,
    pub sha256: String,
    pub platform: String,
    pub architecture: String,
    pub minimum_os: String,
    pub minimum_glibc: Option<String>,
    pub format: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Manifest {
    pub schema: u32,
    pub application_id: String,
    pub repository: String,
    pub version: String,
    pub tag: String,
    pub channel: String,
    pub draft: bool,
    pub prerelease: bool,
    pub published_at: String,
    pub release_notes_url: String,
    pub restart_required: bool,
    pub migration: String,
    pub assets: BTreeMap<String, Asset>,
}
#[derive(Deserialize, Serialize)]
pub struct Envelope {
    pub payload: String,
    pub signature: String,
}

pub fn stable_version(value: &str) -> Result<Version> {
    let version = Version::parse(value)?;
    if !version.pre.is_empty() || !version.build.is_empty() {
        return Err("Stable versions must be MAJOR.MINOR.PATCH".into());
    }
    Ok(version)
}
pub fn target_parts(target: &str) -> Result<(&str, &str, &str)> {
    match target {
        "macos-arm64" => Ok(("macos", "aarch64", "zip")),
        "macos-intel" => Ok(("macos", "x86_64", "zip")),
        "windows-arm64" => Ok(("windows", "aarch64", "zip")),
        "windows-x64" => Ok(("windows", "x86_64", "zip")),
        "linux-arm64-appimage" => Ok(("linux", "aarch64", "AppImage")),
        "linux-x64-appimage" => Ok(("linux", "x86_64", "AppImage")),
        _ => Err("Unsupported update target; use the platform package manager".into()),
    }
}
pub fn validate_config(config: &Config) -> Result<()> {
    stable_version(&config.version)?;
    target_parts(&config.target)?;
    let repository: Vec<_> = config.repository.split('/').collect();
    if config.channel != "stable"
        || repository.len() != 2
        || repository.iter().any(|p| {
            p.is_empty()
                || !p
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        })
        || config.application_id.is_empty()
        || !config
            .application_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'-')
        || B64.decode(&config.public_key)?.len() != 32
    {
        return Err("Invalid stable update trust configuration".into());
    }
    Ok(())
}
pub fn verify(bytes: &[u8], config: &Config) -> Result<Manifest> {
    validate_config(config)?;
    if bytes.len() as u64 > MANIFEST_LIMIT {
        return Err("Manifest exceeds size limit".into());
    }
    let envelope: Envelope = serde_json::from_slice(bytes)?;
    let raw = B64.decode(envelope.payload)?;
    UnparsedPublicKey::new(&ED25519, B64.decode(&config.public_key)?)
        .verify(&raw, &B64.decode(envelope.signature)?)
        .map_err(|_| "Invalid update signature")?;
    let manifest: Manifest = serde_json::from_slice(&raw)?;
    stable_version(&manifest.version)?;
    let base = format!("https://github.com/{}/releases", config.repository);
    if manifest.schema != 2
        || manifest.application_id != config.application_id
        || manifest.repository != config.repository
        || manifest.channel != "stable"
        || manifest.draft
        || manifest.prerelease
        || manifest.tag != format!("v{}", manifest.version)
        || manifest.release_notes_url != format!("{base}/tag/{}", manifest.tag)
        || manifest.published_at.is_empty()
        || !manifest.restart_required
        || !["none", "manual"].contains(&manifest.migration.as_str())
        || manifest.assets.is_empty()
    {
        return Err("Manifest application, release identity or policy mismatch".into());
    }
    for (target, asset) in &manifest.assets {
        let (platform, arch, format) = target_parts(target)?;
        stable_version(&asset.minimum_os)?;
        if let Some(glibc) = &asset.minimum_glibc {
            stable_version(glibc)?;
        }
        if asset.platform != platform
            || asset.architecture != arch
            || asset.format != format
            || (platform == "linux" && asset.minimum_glibc.is_none())
            || asset.filename.is_empty()
            || !asset
                .filename
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-._".contains(&b))
            || asset.filename == "."
            || asset.filename == ".."
            || !asset.filename.ends_with(&format!(".{format}"))
            || asset.url != format!("{base}/download/{}/{}", manifest.tag, asset.filename)
            || asset.sha256.len() != 64
            || !asset
                .sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || asset.size == 0
            || asset.size > 2 * 1024 * 1024 * 1024
        {
            return Err("Manifest artifact identity, target, URL or digest mismatch".into());
        }
    }
    Ok(manifest)
}
pub fn select<'a>(
    manifest: &'a Manifest,
    config: &Config,
    highest: Option<&str>,
    os_version: &str,
    glibc: Option<&str>,
) -> Result<Option<&'a Asset>> {
    let proposed = stable_version(&manifest.version)?;
    if proposed <= stable_version(&config.version)? {
        return Ok(None);
    }
    if let Some(highest) = highest {
        if proposed < stable_version(highest)? {
            return Err("Update replay below previously authenticated version".into());
        }
    }
    let Some(asset) = manifest.assets.get(&config.target) else {
        return Ok(None);
    };
    if stable_version(os_version)? < stable_version(&asset.minimum_os)? {
        return Ok(None);
    }
    if let Some(minimum) = &asset.minimum_glibc {
        if glibc
            .map(stable_version)
            .transpose()?
            .ok_or("Cannot determine glibc version")?
            < stable_version(minimum)?
        {
            return Ok(None);
        }
    }
    Ok(Some(asset))
}
pub fn download(mut source: impl Read, mut output: impl Write, asset: &Asset) -> Result<()> {
    let mut hash = Sha256::new();
    let mut total = 0;
    let mut buffer = [0u8; 65536];
    loop {
        let n = source.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        total += n as u64;
        if total > asset.size {
            return Err("Download exceeds authenticated size".into());
        }
        hash.update(&buffer[..n]);
        output.write_all(&buffer[..n])?;
    }
    if total != asset.size || format!("{:x}", hash.finalize()) != asset.sha256 {
        return Err("Download checksum/size mismatch".into());
    }
    Ok(())
}
#[derive(Default, Deserialize, Serialize)]
pub struct State {
    pub last_attempt: u64,
    pub last_success: u64,
    pub highest_version: Option<String>,
}
impl State {
    pub fn due(&self, now: u64) -> bool {
        // A clock moved backwards must not suppress checks indefinitely.
        (now < self.last_success || now.saturating_sub(self.last_success) >= CHECK_INTERVAL)
            && (now < self.last_attempt || now.saturating_sub(self.last_attempt) >= RETRY_INTERVAL)
    }
}
