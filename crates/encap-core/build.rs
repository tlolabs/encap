// Embed the resolved Cargo identity, not a sibling checkout or runtime recipe.
use std::{env, fs, path::Path};

fn main() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    for name in ["Cargo.toml", "Cargo.lock"] {
        println!("cargo:rerun-if-changed={}", root.join(name).display());
    }
    let manifest: toml::Value = fs::read_to_string(root.join("Cargo.toml"))
        .unwrap()
        .parse()
        .unwrap();
    let lock: toml::Value = fs::read_to_string(root.join("Cargo.lock"))
        .unwrap()
        .parse()
        .unwrap();
    let pin = &manifest["workspace"]["dependencies"]["avid-core"];
    let packages: Vec<_> = lock["package"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|package| package["name"].as_str() == Some("avid-core"))
        .collect();
    assert_eq!(packages.len(), 1, "Exactly one pinned Core is required");
    let package = packages[0];
    let revision = pin["rev"].as_str().unwrap();
    assert_eq!(revision.len(), 40, "Core requires a full commit pin");
    let version = package["version"].as_str().unwrap();
    assert_eq!(pin["version"].as_str().unwrap(), format!("={version}"));
    let source = format!(
        "git+{}?rev={revision}#{revision}",
        pin["git"].as_str().unwrap()
    );
    assert_eq!(
        package["source"].as_str().unwrap(),
        source,
        "Core lock must match the approved pin"
    );
    println!("cargo:rustc-env=ENCAP_CORE_VERSION={version}");
    println!("cargo:rustc-env=ENCAP_CORE_REVISION={revision}");
    println!("cargo:rustc-env=ENCAP_CORE_SOURCE={source}");
}
