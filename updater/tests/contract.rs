use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use ring::signature::{Ed25519KeyPair, KeyPair};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io::{self, Read, Write},
};
use tlo_updater::*;
const DATA: &[u8] = b"authenticated test image";
fn fixture() -> (Config, Manifest) {
    let key = Ed25519KeyPair::from_seed_unchecked(&[7; 32]).unwrap();
    let config = Config {
        application_id: "org.example.fixture".into(),
        repository: "example/fixture".into(),
        version: "1.9.0".into(),
        channel: "stable".into(),
        target: "linux-x64-appimage".into(),
        public_key: B64.encode(key.public_key().as_ref()),
    };
    let asset = Asset {
        url: "https://github.com/example/fixture/releases/download/v1.10.0/Test.AppImage".into(),
        filename: "Test.AppImage".into(),
        size: DATA.len() as u64,
        sha256: format!("{:x}", Sha256::digest(DATA)),
        platform: "linux".into(),
        architecture: "x86_64".into(),
        minimum_os: "4.18.0".into(),
        minimum_glibc: Some("2.39.0".into()),
        format: "AppImage".into(),
    };
    let manifest = Manifest {
        schema: 2,
        application_id: config.application_id.clone(),
        repository: config.repository.clone(),
        version: "1.10.0".into(),
        tag: "v1.10.0".into(),
        channel: "stable".into(),
        draft: false,
        prerelease: false,
        published_at: "2026-09-30T00:00:00Z".into(),
        release_notes_url: "https://github.com/example/fixture/releases/tag/v1.10.0".into(),
        restart_required: true,
        migration: "none".into(),
        assets: BTreeMap::from([(config.target.clone(), asset)]),
    };
    (config, manifest)
}
fn signed(manifest: &Manifest) -> Vec<u8> {
    let key = Ed25519KeyPair::from_seed_unchecked(&[7; 32]).unwrap();
    let payload = serde_json::to_vec(manifest).unwrap();
    serde_json::to_vec(&Envelope {
        payload: B64.encode(&payload),
        signature: B64.encode(key.sign(&payload)),
    })
    .unwrap()
}
fn available(manifest: &Manifest, config: &Config) -> bool {
    select(manifest, config, None, "6.8.0", Some("2.39.0"))
        .unwrap()
        .is_some()
}
#[test]
fn valid_newer_semver() {
    let (c, m) = fixture();
    let verified = verify(&signed(&m), &c).unwrap();
    assert!(available(&verified, &c));
}
#[test]
fn same_version() {
    let (mut c, m) = fixture();
    c.version = m.version.clone();
    assert!(!available(&m, &c));
}
#[test]
fn older_version() {
    let (mut c, m) = fixture();
    c.version = "2.0.0".into();
    assert!(!available(&m, &c));
}
#[test]
fn no_matching_target() {
    let (mut c, m) = fixture();
    c.target = "windows-arm64".into();
    assert!(!available(&m, &c));
}
#[test]
fn minimum_os_and_libc() {
    let (c, m) = fixture();
    assert!(select(&m, &c, None, "3.10.0", Some("2.39.0"))
        .unwrap()
        .is_none());
    assert!(select(&m, &c, None, "6.8.0", Some("2.38.0"))
        .unwrap()
        .is_none());
}
#[test]
fn replay_below_high_water() {
    let (c, m) = fixture();
    assert!(select(&m, &c, Some("1.11.0"), "6.8.0", Some("2.39.0")).is_err());
}
#[test]
fn malformed_and_nonstable_versions() {
    for v in [
        "1.2",
        "01.2.3",
        "bad",
        "1.2.3-beta.1",
        "1.2.3+nightly",
        "999999999999999999999.0.0",
    ] {
        assert!(stable_version(v).is_err(), "{v}");
    }
}
#[test]
fn invalid_signature_and_wrong_key() {
    let (mut c, m) = fixture();
    let bytes = signed(&m);
    c.public_key = B64.encode([8; 32]);
    assert!(verify(&bytes, &c).is_err());
    let (c, _) = fixture();
    let mut envelope: Envelope = serde_json::from_slice(&bytes).unwrap();
    envelope.signature = B64.encode([0; 64]);
    assert!(verify(&serde_json::to_vec(&envelope).unwrap(), &c).is_err());
}
#[test]
fn metadata_substitution_rejected_even_with_valid_signature() {
    let (c, m) = fixture();
    for field in [
        "application",
        "repository",
        "draft",
        "prerelease",
        "version",
        "channel",
        "tag",
        "notes",
        "schema",
        "migration",
    ] {
        let mut bad = m.clone();
        match field {
            "application" => bad.application_id = "org.example.other".into(),
            "repository" => bad.repository = "evil/fixture".into(),
            "draft" => bad.draft = true,
            "prerelease" => bad.prerelease = true,
            "version" => bad.version = "1.11.0-beta".into(),
            "channel" => bad.channel = "development".into(),
            "tag" => bad.tag = "main".into(),
            "notes" => bad.release_notes_url = "https://evil.example".into(),
            "schema" => bad.schema = 1,
            "migration" => bad.migration = "execute-script".into(),
            _ => unreachable!(),
        };
        assert!(verify(&signed(&bad), &c).is_err(), "{field}");
    }
}
#[test]
fn manifest_artifact_mismatch() {
    let (c, m) = fixture();
    for field in [
        "platform", "arch", "url", "tag", "filename", "digest", "size", "format",
    ] {
        let mut bad = m.clone();
        let a = bad.assets.get_mut(&c.target).unwrap();
        match field {
            "platform" => a.platform = "windows".into(),
            "arch" => a.architecture = "aarch64".into(),
            "url" => a.url = "https://evil.example/Test.AppImage".into(),
            "tag" => a.url = a.url.replace("v1.10.0", "v1.11.0"),
            "filename" => a.filename = "../Test.AppImage".into(),
            "digest" => a.sha256 = "0".repeat(63),
            "size" => a.size = 0,
            "format" => a.format = "exe".into(),
            _ => unreachable!(),
        };
        assert!(verify(&signed(&bad), &c).is_err(), "{field}");
    }
}
#[test]
fn corruption_truncation_overflow_and_checksum_mismatch() {
    let (c, m) = fixture();
    let a = &m.assets[&c.target];
    assert!(download(DATA, Vec::new(), a).is_ok());
    for bytes in [&DATA[..3], &b"bad bytes"[..], &[0; 256][..]] {
        assert!(download(bytes, Vec::new(), a).is_err());
    }
    let mut bad = a.clone();
    bad.sha256 = "0".repeat(64);
    assert!(download(DATA, Vec::new(), &bad).is_err());
}
struct Interrupted;
impl Read for Interrupted {
    fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::new(
            io::ErrorKind::ConnectionReset,
            "fixture interruption",
        ))
    }
}
#[test]
fn interrupted_download() {
    let (c, m) = fixture();
    assert!(download(Interrupted, Vec::new(), &m.assets[&c.target]).is_err());
}
#[test]
fn daily_policy_failure_backoff_and_clock_change() {
    let s = State {
        last_attempt: 100_000,
        last_success: 100_000,
        highest_version: None,
    };
    assert!(!s.due(100_001));
    assert!(s.due(186_400));
    assert!(s.due(90_000));
    let s = State {
        last_attempt: 100_000,
        last_success: 0,
        highest_version: None,
    };
    assert!(!s.due(103_599));
    assert!(s.due(103_600));
}
#[test]
fn unavailable_endpoint_is_an_error() {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    drop(listener);
    assert!(reqwest::blocking::Client::new()
        .get(format!("http://{addr}"))
        .timeout(std::time::Duration::from_secs(1))
        .send()
        .is_err());
}
#[test]
fn local_release_discovery_authentication_and_download() {
    let (c, m) = fixture();
    let metadata = signed(&m);
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        for data in [&metadata[..], DATA] {
            let (mut connection, _) = listener.accept().unwrap();
            let mut request = [0; 4096];
            let received = connection.read(&mut request).unwrap();
            assert!(received > 0);
            write!(
                connection,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                data.len()
            )
            .unwrap();
            connection.write_all(data).unwrap();
        }
    });
    // The HTTP fixture transport exists only in this test; production exposes no endpoint override.
    let client = reqwest::blocking::Client::new();
    let raw = client
        .get(format!("http://{addr}/manifest"))
        .send()
        .unwrap()
        .bytes()
        .unwrap();
    let m = verify(&raw, &c).unwrap();
    let asset = select(&m, &c, None, "6.8.0", Some("2.39.0"))
        .unwrap()
        .unwrap();
    let mut result = Vec::new();
    download(
        client.get(format!("http://{addr}/image")).send().unwrap(),
        &mut result,
        asset,
    )
    .unwrap();
    assert_eq!(result, DATA);
    server.join().unwrap();
}
#[cfg(unix)]
#[test]
fn interrupted_install_retains_old_image_and_success_keeps_backup() {
    use std::{fs, os::unix::fs::PermissionsExt};
    let (c, m) = fixture();
    let a = &m.assets[&c.target];
    let temp = tempfile::tempdir().unwrap();
    let image = temp.path().join("old.AppImage");
    fs::write(&image, b"old image").unwrap();
    fs::set_permissions(&image, fs::Permissions::from_mode(0o755)).unwrap();
    assert!(client::install_appimage(Interrupted, a, &image).is_err());
    assert_eq!(fs::read(&image).unwrap(), b"old image");
    assert!(client::install_appimage(&DATA[..3], a, &image).is_err());
    assert_eq!(fs::read(&image).unwrap(), b"old image");
    let backup = client::install_appimage(DATA, a, &image).unwrap();
    assert_eq!(fs::read(&backup).unwrap(), b"old image");
    assert_eq!(fs::read(&image).unwrap(), DATA);
}
#[cfg(unix)]
#[test]
fn appimage_symlink_rejected() {
    let (c, m) = fixture();
    let dir = tempfile::tempdir().unwrap();
    let original = dir.path().join("old");
    std::fs::write(&original, b"old").unwrap();
    let link = dir.path().join("link");
    std::os::unix::fs::symlink(&original, &link).unwrap();
    assert!(client::install_appimage(DATA, &m.assets[&c.target], &link).is_err());
    assert_eq!(std::fs::read(&original).unwrap(), b"old");
}

#[test]
fn malformed_manifest_and_payload_are_rejected() {
    let (c, _) = fixture();
    for raw in [b"".as_slice(), b"{", b"{}", b"null", b"[]"] {
        assert!(verify(raw, &c).is_err());
    }
    let key = Ed25519KeyPair::from_seed_unchecked(&[7; 32]).unwrap();
    let payload = b"not JSON";
    let envelope = Envelope {
        payload: B64.encode(payload),
        signature: B64.encode(key.sign(payload)),
    };
    assert!(verify(&serde_json::to_vec(&envelope).unwrap(), &c).is_err());
}

#[test]
fn service_failure_and_interrupted_download_can_retry() {
    let (c, m) = fixture();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        for (status, size, body) in [
            ("503 Service Unavailable", 0, &b""[..]),
            ("200 OK", DATA.len(), &DATA[..3]),
            ("200 OK", DATA.len(), DATA),
        ] {
            let (mut connection, _) = listener.accept().unwrap();
            let mut request = [0; 4096];
            assert!(connection.read(&mut request).unwrap() > 0);
            write!(
                connection,
                "HTTP/1.1 {status}\r\nContent-Length: {size}\r\nConnection: close\r\n\r\n"
            )
            .unwrap();
            connection.write_all(body).unwrap();
        }
    });
    let http = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .unwrap();
    let url = format!("http://{addr}/fixture");
    assert!(http.get(&url).send().unwrap().error_for_status().is_err());
    assert!(download(
        http.get(&url).send().unwrap(),
        Vec::new(),
        &m.assets[&c.target]
    )
    .is_err());
    let mut verified = Vec::new();
    download(
        http.get(&url).send().unwrap(),
        &mut verified,
        &m.assets[&c.target],
    )
    .unwrap();
    assert_eq!(verified, DATA);
    server.join().unwrap();
}

#[cfg(unix)]
#[test]
fn unable_to_install_preserves_image_and_cleans_staging() {
    use std::{fs, os::unix::fs::PermissionsExt};
    let (c, m) = fixture();
    let root = tempfile::tempdir().unwrap();
    let directory = root.path().join("readonly");
    fs::create_dir(&directory).unwrap();
    let image = directory.join("old.AppImage");
    fs::write(&image, b"old image").unwrap();
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o500)).unwrap();
    let result = client::install_appimage(DATA, &m.assets[&c.target], &image);
    fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(result.is_err());
    assert_eq!(fs::read(&image).unwrap(), b"old image");
    assert_eq!(fs::read_dir(&directory).unwrap().count(), 1);
}

#[cfg(unix)]
#[test]
fn failed_authentication_cleans_install_staging_before_retry() {
    let (c, m) = fixture();
    let root = tempfile::tempdir().unwrap();
    let image = root.path().join("old.AppImage");
    std::fs::write(&image, b"old image").unwrap();
    let mut bad = m.assets[&c.target].clone();
    bad.sha256 = "0".repeat(64);
    assert!(client::install_appimage(DATA, &bad, &image).is_err());
    assert_eq!(std::fs::read(&image).unwrap(), b"old image");
    assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), 1);
    let backup = client::install_appimage(DATA, &m.assets[&c.target], &image).unwrap();
    assert_eq!(std::fs::read(backup).unwrap(), b"old image");
    assert_eq!(std::fs::read(image).unwrap(), DATA);
}
