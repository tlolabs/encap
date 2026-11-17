//! Bounded preflight before SwiftPM can evaluate a fatal Bundle.module accessor.
use super::*;
use sha2::{Digest, Sha256};
use std::io::Read;
const MAX_RECEIPT: u64 = 4 * 1024 * 1024;
const RECEIPT: &str = "encap-transcription-resources.json";
const SIGNED: &str = "encap-transcription-signed.json";
#[derive(Deserialize)]
struct Receipt {
    schema: u32,
    layout: String,
    scope: String,
    platform: String,
    minimum_macos: String,
    abi_version: u32,
    schema_version: u32,
    source_commit: String,
    snapshot_sha256: String,
    source_manifest_sha256: String,
    library_code_sha256: BTreeMap<String, String>,
    files: Vec<Entry>,
}
#[derive(Deserialize)]
struct Entry {
    path: String,
    sha256: String,
    size: u64,
}
#[derive(Deserialize)]
struct Signed {
    schema: u32,
    original_receipt_sha256: String,
    library_code_sha256: BTreeMap<String, String>,
    files: BTreeMap<String, SignedFile>,
}
#[derive(Deserialize)]
struct SignedFile {
    sha256: String,
    size: u64,
}
fn fail(detail: impl Into<String>) -> EncapError {
    message(format!(
        "Linked transcription resources are missing or incompatible: {}",
        detail.into()
    ))
}
fn read_receipt(path: &Path) -> Result<Vec<u8>> {
    let info = fs::symlink_metadata(path).map_err(|e| fail(e.to_string()))?;
    if !info.is_file() || info.file_type().is_symlink() || info.len() > MAX_RECEIPT {
        return Err(fail("invalid receipt size/type"));
    }
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(|e| fail(e.to_string()))?
        .take(MAX_RECEIPT + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| fail(e.to_string()))?;
    if bytes.len() as u64 > MAX_RECEIPT {
        return Err(fail("receipt grew while reading"));
    }
    Ok(bytes)
}
fn hash(path: &Path, maximum: u64) -> Result<String> {
    let mut input = fs::File::open(path)
        .map_err(|e| fail(e.to_string()))?
        .take(maximum + 1);
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 65536];
    loop {
        let n = input.read(&mut buffer).map_err(|e| fail(e.to_string()))?;
        if n == 0 {
            break;
        }
        digest.update(&buffer[..n]);
    }
    Ok(format!("{:x}", digest.finalize()))
}
fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn relative(root: &Path, name: &str) -> Result<PathBuf> {
    if name.is_empty()
        || name.contains(['\\', ':'])
        || name
            .split('/')
            .any(|p| p.is_empty() || p == "." || p == "..")
    {
        return Err(fail("unsafe inventory path"));
    }
    let mut path = root.to_path_buf();
    for component in name.split('/') {
        path.push(component);
        let info = fs::symlink_metadata(&path).map_err(|e| fail(e.to_string()))?;
        if info.file_type().is_symlink() {
            return Err(fail("linked inventory path"));
        }
    }
    Ok(path)
}
fn can_sign(name: &str) -> bool {
    name == "EnCAPTranscription"
        || name.starts_with("Frameworks/") && name.ends_with(".dylib")
        || name.split('/').any(|p| p == "_CodeSignature")
}
fn inventory(root: &Path, path: &Path, files: &mut BTreeSet<String>) -> Result<()> {
    for entry in fs::read_dir(path).map_err(|e| fail(e.to_string()))? {
        let entry = entry.map_err(|e| fail(e.to_string()))?;
        let path = entry.path();
        let kind = entry.file_type().map_err(|e| fail(e.to_string()))?;
        if kind.is_symlink() {
            return Err(fail("linked resource path"));
        }
        if kind.is_dir() {
            inventory(root, &path, files)?;
        } else if kind.is_file() {
            let name = path
                .strip_prefix(root)
                .map_err(|_| fail("escaping resource path"))?
                .to_str()
                .ok_or_else(|| fail("non UTF-8 resource path"))?
                .replace(std::path::MAIN_SEPARATOR, "/");
            if name != RECEIPT && name != SIGNED {
                files.insert(name);
            }
            if files.len() > 10000 {
                return Err(fail("resource inventory is too large"));
            }
        } else {
            return Err(fail("special resource file"));
        }
    }
    Ok(())
}
pub(super) fn verify(library: &Path) -> Result<()> {
    let root = library
        .parent()
        .ok_or_else(|| fail("invalid library path"))?;
    if fs::symlink_metadata(root)
        .map_err(|e| fail(e.to_string()))?
        .file_type()
        .is_symlink()
    {
        return Err(fail("linked resource root"));
    }
    let framework = root
        .parent()
        .and_then(Path::parent)
        .ok_or_else(|| fail("invalid framework path"))?;
    if root.file_name().and_then(|v| v.to_str()) != Some("A")
        || root
            .parent()
            .and_then(Path::file_name)
            .and_then(|v| v.to_str())
            != Some("Versions")
        || framework.file_name().and_then(|v| v.to_str()) != Some("EnCAPTranscription.framework")
    {
        return Err(fail("invalid framework layout"));
    }
    #[cfg(target_os = "macos")]
    for (link, target) in [
        ("Versions/Current", "A"),
        ("EnCAPTranscription", "Versions/Current/EnCAPTranscription"),
        ("Resources", "Versions/Current/Resources"),
        ("Frameworks", "Versions/Current/Frameworks"),
    ] {
        if fs::read_link(framework.join(link)).ok().as_deref() != Some(Path::new(target)) {
            return Err(fail("framework links changed"));
        }
    }
    let parent = framework
        .parent()
        .ok_or_else(|| fail("invalid framework location"))?;
    let metadata = if parent.file_name().and_then(|v| v.to_str()) == Some("Frameworks")
        && parent
            .parent()
            .and_then(Path::file_name)
            .and_then(|v| v.to_str())
            == Some("Contents")
    {
        parent
            .parent()
            .unwrap()
            .join("Resources/EnCAPTranscription")
    } else {
        #[cfg(debug_assertions)]
        {
            parent.join("EnCAPTranscription-metadata")
        }
        #[cfg(not(debug_assertions))]
        {
            return Err(fail(
                "framework must be installed in the application's Frameworks directory",
            ));
        }
    };
    let bytes = read_receipt(&metadata.join(RECEIPT))?;
    let receipt: Receipt = serde_json::from_slice(&bytes).map_err(|e| fail(e.to_string()))?;
    if receipt.schema != 1
        || receipt.layout != "macos-versioned-framework-v1"
        || receipt.scope != "encap_linked_transcription_staging"
        || receipt.platform != "macos-arm64"
        || receipt.minimum_macos != "14.0"
        || receipt.abi_version != 1
        || receipt.schema_version != 1
        || receipt.source_commit != "dd112d497b68df6786f49a71b3611f7f32f090e9"
        || receipt.snapshot_sha256
            != "76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3"
        || receipt.source_manifest_sha256
            != "7dcb2311c335a8b06fb91e160ee8441337a02ddb17b8b03fb14c1f3a0f110a27"
        || receipt.files.is_empty()
        || receipt.files.len() > 10000
    {
        return Err(fail("source, ABI or platform identity differs"));
    }
    let signed = if metadata.join(SIGNED).exists() {
        Some(
            serde_json::from_slice::<Signed>(&read_receipt(&metadata.join(SIGNED))?)
                .map_err(|e| fail(e.to_string()))?,
        )
    } else {
        None
    };
    if signed.as_ref().is_some_and(|s| {
        s.schema != 1
            || s.original_receipt_sha256 != digest(&bytes)
            || s.library_code_sha256 != receipt.library_code_sha256
            || s.files.keys().any(|p| !can_sign(p))
    }) {
        return Err(fail(
            "signed resource binding differs from the original receipt",
        ));
    }
    let mut expected = BTreeMap::new();
    let mut total = 0u64;
    for entry in &receipt.files {
        if expected
            .insert(entry.path.clone(), (entry.sha256.clone(), entry.size))
            .is_some()
        {
            return Err(fail("duplicate inventory file"));
        }
    }
    if let Some(signed) = signed {
        for (name, file) in signed.files {
            expected.insert(name, (file.sha256, file.size));
        }
    }
    if !expected.contains_key("EnCAPTranscription")
        || !receipt
            .library_code_sha256
            .contains_key("EnCAPTranscription")
        || !expected.keys().any(|p| {
            p.starts_with("Resources/AVIDTranscription_AVIDTranscription.bundle/")
                && p.ends_with("/models.json")
        })
        || !expected
            .keys()
            .any(|p| p.starts_with("Resources/mlx-swift_Cmlx.bundle/") && p.ends_with(".metallib"))
    {
        return Err(fail("critical catalog, Metal or library inventory missing"));
    }
    for (name, (sha, size)) in &expected {
        total = total
            .checked_add(*size)
            .ok_or_else(|| fail("resource size overflow"))?;
        if *size > 512 * 1024 * 1024
            || total > 2 * 1024 * 1024 * 1024
            || sha.len() != 64
            || !sha.bytes().all(|v| v.is_ascii_hexdigit())
        {
            return Err(fail("resource inventory size/hash invalid"));
        }
        let path = relative(root, name)?;
        let info = fs::metadata(&path).map_err(|e| fail(e.to_string()))?;
        if !info.is_file() || info.len() != *size || hash(&path, *size)? != *sha {
            return Err(fail(format!("resource checksum differs: {name}")));
        }
    }
    let mut actual = BTreeSet::new();
    inventory(root, root, &mut actual)?;
    if actual != expected.keys().cloned().collect() {
        return Err(fail("resource inventory changed"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture(root: &Path) -> PathBuf {
        let framework = root.join("EnCAPTranscription.framework");
        let payload = framework.join("Versions/A");
        let metadata = root.join("EnCAPTranscription-metadata");
        fs::create_dir_all(&payload).unwrap();
        fs::create_dir_all(&metadata).unwrap();
        #[cfg(target_os = "macos")]
        for (link, target) in [
            ("Versions/Current", "A"),
            ("EnCAPTranscription", "Versions/Current/EnCAPTranscription"),
            ("Resources", "Versions/Current/Resources"),
            ("Frameworks", "Versions/Current/Frameworks"),
        ] {
            std::os::unix::fs::symlink(target, framework.join(link)).unwrap();
        }
        let root = payload.as_path();
        let paths = [
            "EnCAPTranscription",
            "Resources/AVIDTranscription_AVIDTranscription.bundle/Contents/Resources/models.json",
            "Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib",
        ];
        let files: Vec<_> = paths
            .iter()
            .map(|name| {
                let path = root.join(name);
                fs::create_dir_all(path.parent().unwrap()).unwrap();
                fs::write(&path, b"fixture").unwrap();
                serde_json::json!({"path":name,"sha256":digest(b"fixture"),"size":7})
            })
            .collect();
        let value = serde_json::json!({"schema":1,"layout":"macos-versioned-framework-v1","scope":"encap_linked_transcription_staging","platform":"macos-arm64","minimum_macos":"14.0","abi_version":1,"schema_version":1,
            "source_commit":"dd112d497b68df6786f49a71b3611f7f32f090e9","snapshot_sha256":"76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3",
            "source_manifest_sha256":"7dcb2311c335a8b06fb91e160ee8441337a02ddb17b8b03fb14c1f3a0f110a27","library_code_sha256":{"EnCAPTranscription":"c".repeat(64)},"files":files});
        fs::write(metadata.join(RECEIPT), serde_json::to_vec(&value).unwrap()).unwrap();
        root.join(paths[0])
    }
    #[test]
    fn production_app_candidate_keeps_contents_location_and_resource_link_checks() {
        let directory = tempfile::tempdir().unwrap();
        let contents = directory.path().join("EnCap.app/Contents");
        let binaries = contents.join("MacOS");
        let frameworks = contents.join("Frameworks");
        fs::create_dir_all(&binaries).unwrap();
        let library = fixture(&frameworks);
        fs::create_dir_all(contents.join("Resources")).unwrap();
        fs::rename(
            frameworks.join("EnCAPTranscription-metadata"),
            contents.join("Resources/EnCAPTranscription"),
        )
        .unwrap();
        let candidate = packaged_libraries(&binaries)
            .unwrap()
            .into_iter()
            .next()
            .unwrap();
        assert_eq!(candidate, library);
        assert!(!candidate
            .components()
            .any(|v| v == std::path::Component::ParentDir));
        verify(&candidate).unwrap();
        #[cfg(unix)]
        {
            let catalog=library.parent().unwrap().join("Resources/AVIDTranscription_AVIDTranscription.bundle/Contents/Resources/models.json");
            let unowned = directory.path().join("unowned-catalog.json");
            fs::rename(&catalog, &unowned).unwrap();
            std::os::unix::fs::symlink(&unowned, &catalog).unwrap();
            assert!(verify(&candidate)
                .unwrap_err()
                .to_string()
                .contains("linked inventory path"));
            assert_eq!(fs::read(&unowned).unwrap(), b"fixture");
        }
    }
    #[test]
    fn missing_catalog_corrupt_metal_and_extra_resources_fail_before_dlopen() {
        let directory = tempfile::tempdir().unwrap();
        let library = fixture(directory.path());
        assert!(verify(&library).is_ok());
        let catalog = library.parent().unwrap().join(
            "Resources/AVIDTranscription_AVIDTranscription.bundle/Contents/Resources/models.json",
        );
        fs::remove_file(&catalog).unwrap();
        assert!(verify(&library).is_err());
        fs::write(&catalog, b"fixture").unwrap();
        let metal = library
            .parent()
            .unwrap()
            .join("Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib");
        fs::write(&metal, b"corrupt").unwrap();
        assert!(verify(&library).is_err());
        fs::write(&metal, b"fixture").unwrap();
        fs::write(library.parent().unwrap().join("extra.json"), b"extra").unwrap();
        assert!(verify(&library).is_err());
    }
    #[test]
    fn signed_raw_hashes_require_binding_to_the_original_receipt() {
        let directory = tempfile::tempdir().unwrap();
        let library = fixture(directory.path());
        fs::write(&library, b"signed fixture").unwrap();
        assert!(verify(&library).is_err());
        let receipt = fs::read(
            directory
                .path()
                .join("EnCAPTranscription-metadata")
                .join(RECEIPT),
        )
        .unwrap();
        let mut binding = serde_json::json!({"schema":1,"original_receipt_sha256":digest(&receipt),"library_code_sha256":{"EnCAPTranscription":"c".repeat(64)},
            "files":{"EnCAPTranscription":{"sha256":digest(b"signed fixture"),"size":14}}});
        fs::write(
            directory
                .path()
                .join("EnCAPTranscription-metadata")
                .join(SIGNED),
            serde_json::to_vec(&binding).unwrap(),
        )
        .unwrap();
        assert!(verify(&library).is_ok());
        binding["original_receipt_sha256"] = serde_json::Value::String("0".repeat(64));
        fs::write(
            directory
                .path()
                .join("EnCAPTranscription-metadata")
                .join(SIGNED),
            serde_json::to_vec(&binding).unwrap(),
        )
        .unwrap();
        assert!(verify(&library).is_err());
    }
    #[test]
    fn missing_receipt_is_a_rust_error_before_loading_swift() {
        let directory = tempfile::tempdir().unwrap();
        let library = directory.path().join("libEnCAPTranscription.dylib");
        fs::write(&library, b"not loaded").unwrap();
        assert!(verify(&library)
            .unwrap_err()
            .to_string()
            .contains("resources are missing"));
    }
}
