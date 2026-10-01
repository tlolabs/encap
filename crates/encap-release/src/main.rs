//! Compatibility entry point; shared tooling owns the update wire contract.
fn main() {
    let mut args = std::env::args().skip(1);
    let mut command = std::process::Command::new(if cfg!(windows) { "python" } else { "python3" });
    command.arg("script/tlo_update_release.py");
    while let Some(arg) = args.next() {
        if arg == "--notes-file" {
            let _ = args.next();
            continue;
        }
        command.arg(if arg == "--assets-dir" {
            "--assets"
        } else {
            &arg
        });
    }
    match command.status() {
        Ok(status) => std::process::exit(status.code().unwrap_or(1)),
        Err(error) => {
            eprintln!("Cannot run shared release tooling: {error}");
            std::process::exit(1);
        }
    }
}
