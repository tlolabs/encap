//! Release authentication probe. This does NOT install or qualify a native upgrade.
use std::{fs, path::Path};
use tlo_updater::{client, download, select, verify, Config, Result};
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 {
        return Err(
            "Usage: tlo-qualify TRUSTED-OLD-CONFIG.json ASSET-DIRECTORY|--published".into(),
        );
    }
    let config: Config = serde_json::from_slice(&fs::read(&args[1])?)?;
    let http = client::http_client()?;
    let manifest = if args[2] == "--published" {
        client::discover(&http, &config)?
    } else {
        verify(
            &fs::read(Path::new(&args[2]).join("update-manifest.json"))?,
            &config,
        )?
    };
    // Compatibility is tested on native hosts. Here use the artifact's declared floor.
    let asset = manifest
        .assets
        .get(&config.target)
        .ok_or("Target absent from published manifest")?;
    let selected = select(
        &manifest,
        &config,
        None,
        &asset.minimum_os,
        asset.minimum_glibc.as_deref(),
    )?
    .ok_or("Not a newer stable release for this older build")?;
    if args[2] == "--published" {
        download(
            http.get(&selected.url).send()?.error_for_status()?,
            std::io::sink(),
            selected,
        )?;
    } else {
        download(
            fs::File::open(Path::new(&args[2]).join(&selected.filename))?,
            std::io::sink(),
            selected,
        )?;
    }
    println!(
        "{}",
        serde_json::json!({"application_id":config.application_id,"previous_version":config.version,"version":manifest.version,"target":config.target,"discovery_authentication_download":"passed","installation":"not_tested"})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("Release authentication failed: {error}");
        std::process::exit(1);
    }
}
