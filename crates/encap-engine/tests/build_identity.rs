use serde_json::Value;
use std::process::Command;

#[test]
fn normal_engine_reports_the_resolved_core_pin_without_media_tools() {
    let output = Command::new(env!("CARGO_BIN_EXE_encap-engine"))
        .arg("build-info")
        .env("PATH", "")
        .env("ENCAP_FFMPEG", "/missing")
        .env("ENCAP_FFPROBE", "/missing")
        .output()
        .unwrap();
    assert!(output.status.success());
    let identity: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(identity["encap_version"], env!("CARGO_PKG_VERSION"));
    assert_eq!(identity["avid_core"]["version"], encap_core::CORE_VERSION);
    assert_eq!(identity["avid_core"]["revision"], encap_core::CORE_REVISION);
    assert_eq!(identity["avid_core"]["source"], encap_core::CORE_SOURCE);
    assert_eq!(encap_core::CORE_REVISION.len(), 40);
}
