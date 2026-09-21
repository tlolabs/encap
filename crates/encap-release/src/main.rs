use std::{
    collections::BTreeMap,
    env,
    error::Error,
    fs::{self, File},
    io::{self, BufReader, Read},
    path::{Path, PathBuf},
};

use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use clap::Parser;
use ring::signature::{Ed25519KeyPair, KeyPair};
use serde::Serialize;
use sha2::{Digest, Sha256};
use time::{format_description::well_known::Rfc2822, OffsetDateTime};

const REPOSITORY_URL: &str = "https://github.com/tlolabs/encap";
const SPARKLE_NAMESPACE: &str = "http://www.andymatuschak.org/xml-namespaces/sparkle";
type Result<T> = std::result::Result<T, Box<dyn Error + Send + Sync>>;

#[derive(Debug, Parser)]
#[command(about = "Build signed EnCap release metadata")]
struct Args {
    #[arg(long)]
    assets_dir: PathBuf,
    #[arg(long)]
    version: String,
    #[arg(long)]
    tag: String,
    #[arg(long)]
    notes_file: Option<PathBuf>,
}

#[derive(Serialize)]
struct Asset {
    archive: String,
    sha256: String,
    size: u64,
    url: String,
}

#[derive(Serialize)]
struct Payload {
    assets: BTreeMap<String, Asset>,
    notes: String,
    release_url: String,
    schema_version: u8,
    version: String,
}

#[derive(Serialize)]
struct Manifest<'a> {
    payload: &'a Payload,
    signature: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    validate_version(&args.version, &args.tag)?;

    let seed_value = required_environment("ENCAP_UPDATE_PRIVATE_KEY")?;
    let public_value = required_environment("ENCAP_UPDATE_PUBLIC_KEY")?;
    let seed = BASE64.decode(seed_value).map_err(|error| {
        fail(format!(
            "ENCAP_UPDATE_PRIVATE_KEY must be valid base64: {error}"
        ))
    })?;
    if seed.len() != 32 {
        return Err(fail(
            "ENCAP_UPDATE_PRIVATE_KEY must be a base64-encoded 32-byte seed",
        ));
    }
    let key_pair = Ed25519KeyPair::from_seed_unchecked(&seed)
        .map_err(|_| fail("ENCAP_UPDATE_PRIVATE_KEY is not a valid Ed25519 seed"))?;
    if BASE64.encode(key_pair.public_key().as_ref()) != public_value {
        return Err(fail(
            "the configured update private and public keys do not match",
        ));
    }

    let notes = args
        .notes_file
        .as_deref()
        .filter(|path| path.exists())
        .map(fs::read_to_string)
        .transpose()
        .map_err(|error| fail(format!("failed to read release notes: {error}")))?
        .unwrap_or_default()
        .trim()
        .to_owned();
    let base_url = format!("{REPOSITORY_URL}/releases/download/{}", args.tag);
    let specs = [
        (
            "linux-arm64",
            format!("EnCap-{}-linux-arm64.tar.gz", args.version),
            "tar.gz",
        ),
        (
            "linux-x64",
            format!("EnCap-{}-linux-x64.tar.gz", args.version),
            "tar.gz",
        ),
        (
            "macos-arm64",
            format!("EnCap-{}-macos-arm64.dmg", args.version),
            "dmg",
        ),
        (
            "macos-intel",
            format!("EnCap-{}-macos-intel.dmg", args.version),
            "dmg",
        ),
        (
            "windows-arm64",
            format!("EnCap-{}-windows-arm64.zip", args.version),
            "zip",
        ),
        (
            "windows-x64",
            format!("EnCap-{}-windows-x64.zip", args.version),
            "zip",
        ),
    ];
    let mut assets = BTreeMap::new();

    for (platform, filename, archive) in specs {
        let path = args.assets_dir.join(&filename);
        if !path.is_file() {
            return Err(fail(format!(
                "required release asset is missing: {}",
                path.display()
            )));
        }
        let size = path.metadata()?.len();
        let url = format!("{base_url}/{filename}");
        assets.insert(
            platform.to_owned(),
            Asset {
                archive: archive.to_owned(),
                sha256: digest(&path)?,
                size,
                url: url.clone(),
            },
        );

        if platform.starts_with("macos-") {
            let bytes = fs::read(&path)?;
            let signature = BASE64.encode(key_pair.sign(&bytes).as_ref());
            let appcast = appcast(&args.version, &args.tag, &url, &signature, size)?;
            fs::write(
                args.assets_dir.join(format!("appcast-{platform}.xml")),
                appcast,
            )
            .map_err(|error| fail(format!("failed to write Sparkle appcast: {error}")))?;
        }
    }

    let payload = Payload {
        assets,
        notes,
        release_url: format!("{REPOSITORY_URL}/releases/tag/{}", args.tag),
        schema_version: 1,
        version: args.version,
    };
    let canonical = serde_json::to_vec(&payload)?;
    let signature = BASE64.encode(key_pair.sign(&canonical).as_ref());
    let mut output = serde_json::to_string_pretty(&Manifest {
        payload: &payload,
        signature,
    })?;
    output.push('\n');
    fs::write(args.assets_dir.join("latest.json"), output)
        .map_err(|error| fail(format!("failed to write update manifest: {error}")))?;
    Ok(())
}

fn required_environment(name: &str) -> Result<String> {
    let value = env::var(name).unwrap_or_default().trim().to_owned();
    if value.is_empty() {
        return Err(fail(format!("{name} is required")));
    }
    Ok(value)
}

fn validate_version(version: &str, tag: &str) -> Result<()> {
    if tag != format!("v{version}") {
        return Err(fail(format!(
            "tag {tag} must exactly match package version v{version}"
        )));
    }
    let parts: Vec<_> = version.split('.').collect();
    if !(2..=4).contains(&parts.len())
        || parts
            .iter()
            .any(|part| part.is_empty() || !part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return Err(fail(
            "release versions must contain 2 to 4 numeric components",
        ));
    }
    Ok(())
}

fn digest(path: &Path) -> Result<String> {
    let file = File::open(path)?;
    let mut reader = BufReader::new(file);
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

fn appcast(
    version: &str,
    tag: &str,
    asset_url: &str,
    signature: &str,
    length: u64,
) -> Result<String> {
    let published = OffsetDateTime::now_utc()
        .format(&Rfc2822)
        .map_err(|error| {
            fail(format!(
                "failed to format appcast publication date: {error}"
            ))
        })?;
    Ok(format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<rss xmlns:sparkle=\"{SPARKLE_NAMESPACE}\" version=\"2.0\">\n  <channel>\n    <title>EnCap updates</title>\n    <link>{REPOSITORY_URL}</link>\n    <description>EnCap stable releases</description>\n    <item>\n      <title>EnCap {version}</title>\n      <link>{REPOSITORY_URL}/releases/tag/{tag}</link>\n      <sparkle:version>{version}</sparkle:version>\n      <sparkle:shortVersionString>{version}</sparkle:shortVersionString>\n      <sparkle:minimumSystemVersion>13.0.0</sparkle:minimumSystemVersion>\n      <pubDate>{published}</pubDate>\n      <enclosure url=\"{asset_url}\" sparkle:edSignature=\"{signature}\" length=\"{length}\" type=\"application/octet-stream\" />\n    </item>\n  </channel>\n</rss>\n"
    ))
}

fn fail(message: impl Into<String>) -> Box<dyn Error + Send + Sync> {
    io::Error::other(message.into()).into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_release_version_and_matching_tag() {
        assert!(validate_version("2.0.0", "v2.0.0").is_ok());
    }

    #[test]
    fn rejects_non_numeric_or_mismatched_versions() {
        assert!(validate_version("2.0.0-beta", "v2.0.0-beta").is_err());
        assert!(validate_version("2.0.0", "v2.0.1").is_err());
    }
}
