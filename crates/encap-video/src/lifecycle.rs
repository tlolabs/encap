//! Application limits across engine subprocesses, above Core's four-probe limit.
use crate::CancellationToken;
use encap_core::{EncapError, Result};
use fs2::FileExt;
use std::{
    collections::hash_map::DefaultHasher,
    fs::{self, File, OpenOptions},
    hash::{Hash, Hasher},
    path::{Path, PathBuf},
    time::Duration,
};

pub(crate) fn check(token: &CancellationToken) -> Result<()> {
    if token.is_cancelled() {
        Err(EncapError::from(avid_core::Error::Cancelled))
    } else {
        Ok(())
    }
}

fn io_error(source: std::io::Error) -> EncapError {
    tracing::error!(%source, "Video worker coordination failed");
    EncapError::Message("Video could not coordinate media workers safely.".into())
}

fn lock_file(root: &Path, name: &str) -> Result<File> {
    // Keep lock files after releasing them: unlinking permits two independent
    // locks on the same destination while an older process still holds a handle.
    OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join(name))
        .map_err(io_error)
}

fn try_lock(file: &File) -> Result<bool> {
    match file.try_lock_exclusive() {
        Ok(()) => Ok(true),
        Err(error) if error.raw_os_error() == fs2::lock_contended_error().raw_os_error() => {
            Ok(false)
        }
        Err(error) => Err(io_error(error)),
    }
}

fn wait(token: &CancellationToken) -> Result<()> {
    check(token)?;
    std::thread::sleep(Duration::from_millis(25));
    check(token)
}

/// Core operations are blocking. Keep this guard on the application's worker
/// until Core has returned and all of its child processes/probe workers joined.
pub(crate) struct OperationGuard {
    _destination: Option<File>,
    _slot: File,
}

impl OperationGuard {
    pub(crate) fn acquire(destination: Option<&Path>, token: &CancellationToken) -> Result<Self> {
        Self::acquire_in(
            &std::env::temp_dir().join("encap-video-workers-v1"),
            destination,
            token,
        )
    }

    fn acquire_in(
        root: &Path,
        destination: Option<&Path>,
        token: &CancellationToken,
    ) -> Result<Self> {
        check(token)?;
        fs::create_dir_all(root).map_err(io_error)?;
        let destination = destination
            .map(|path| {
                let path = destination_key(path)?;
                let mut hash = DefaultHasher::new();
                path.hash(&mut hash);
                lock_file(root, &format!("destination-{:016x}.lock", hash.finish()))
            })
            .transpose()?;
        if let Some(file) = &destination {
            while !try_lock(file)? {
                wait(token)?;
            }
        }
        // Two concurrent operations allow independent jobs/cancellation while
        // bounding aggregate artwork probes to eight, including engine processes.
        let mut slots = vec![
            lock_file(root, "slot-0.lock")?,
            lock_file(root, "slot-1.lock")?,
        ];
        loop {
            check(token)?;
            for index in 0..slots.len() {
                if try_lock(&slots[index])? {
                    return Ok(Self {
                        _destination: destination,
                        _slot: slots.swap_remove(index),
                    });
                }
            }
            wait(token)?;
        }
    }
}

fn destination_key(path: &Path) -> Result<PathBuf> {
    let absolute = std::path::absolute(path).map_err(io_error)?;
    let parent = absolute
        .parent()
        .ok_or_else(|| EncapError::Message("Choose a valid Video output destination.".into()))?;
    // Core creates missing output directories. Resolve the nearest existing
    // ancestor without creating directories before source/output protection.
    let mut ancestor = parent;
    let mut missing = Vec::new();
    let mut resolved = loop {
        match fs::canonicalize(ancestor) {
            Ok(path) => break path,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                missing.push(ancestor.file_name().ok_or_else(|| io_error(error))?);
                ancestor = ancestor.parent().ok_or_else(|| {
                    EncapError::Message("Choose a valid Video output destination.".into())
                })?;
            }
            Err(error) => return Err(io_error(error)),
        }
    };
    for component in missing.into_iter().rev() {
        resolved.push(component);
    }
    resolved.push(
        absolute.file_name().ok_or_else(|| {
            EncapError::Message("Choose a valid Video output destination.".into())
        })?,
    );
    // Platform defaults commonly ignore filename case. Folding on these
    // platforms can conservatively serialize distinct names on a case-sensitive
    // volume, which is safer than allowing concurrent writers to an alias.
    #[cfg(any(target_os = "macos", windows))]
    {
        resolved = PathBuf::from(resolved.to_string_lossy().to_lowercase());
    }
    Ok(resolved)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{sync::mpsc, time::Instant};

    #[test]
    fn aggregate_limit_and_destination_wait_are_independently_cancellable() {
        let root = tempfile::tempdir().unwrap();
        let token = CancellationToken::default();
        let output = root.path().join("out.mp4");
        let first = OperationGuard::acquire_in(root.path(), Some(&output), &token).unwrap();
        let second = OperationGuard::acquire_in(root.path(), None, &token).unwrap();
        for destination in [Some(output.clone()), None] {
            let wait_token = CancellationToken::default();
            let worker_token = wait_token.clone();
            let root = root.path().to_path_buf();
            let (started, received) = mpsc::channel();
            let worker = std::thread::spawn(move || {
                started.send(()).unwrap();
                OperationGuard::acquire_in(&root, destination.as_deref(), &worker_token).map(|_| ())
            });
            received.recv().unwrap();
            std::thread::sleep(Duration::from_millis(60));
            let start = Instant::now();
            wait_token.cancel();
            assert!(worker
                .join()
                .unwrap()
                .unwrap_err()
                .to_string()
                .contains("cancelled"));
            assert!(start.elapsed() < Duration::from_secs(1));
            assert!(!token.is_cancelled());
        }
        drop(first);
        drop(second);
        OperationGuard::acquire_in(root.path(), Some(&output), &token).unwrap();
    }

    #[test]
    fn missing_output_parents_and_relative_spelling_have_stable_keys() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("new/nested/out.mp4");
        assert_eq!(
            destination_key(&output).unwrap(),
            destination_key(&root.path().join("./new/nested/out.mp4")).unwrap()
        );
        assert!(!root.path().join("new").exists());
        fs::create_dir_all(output.parent().unwrap()).unwrap();
        assert_eq!(
            destination_key(&output).unwrap(),
            destination_key(&root.path().join("new/../new/nested/out.mp4")).unwrap()
        );
    }

    #[cfg(unix)]
    #[test]
    fn parent_symlink_aliases_share_a_lock_while_file_symlinks_are_separate_entries() {
        let root = tempfile::tempdir().unwrap();
        let real = root.path().join("real");
        fs::create_dir(&real).unwrap();
        let alias = root.path().join("alias");
        std::os::unix::fs::symlink(&real, &alias).unwrap();
        assert_eq!(
            destination_key(&real.join("out.mp4")).unwrap(),
            destination_key(&alias.join("out.mp4")).unwrap()
        );
        fs::write(real.join("out.mp4"), b"old").unwrap();
        std::os::unix::fs::symlink(real.join("out.mp4"), real.join("link.mp4")).unwrap();
        // Core's rename publishes by replacing the named symlink itself.
        assert_ne!(
            destination_key(&real.join("out.mp4")).unwrap(),
            destination_key(&real.join("link.mp4")).unwrap()
        );
        #[cfg(target_os = "macos")]
        assert_eq!(
            destination_key(&real.join("out.mp4")).unwrap(),
            destination_key(&real.join("OUT.MP4")).unwrap()
        );
    }
}

#[cfg(test)]
mod process_lock_tests {
    use super::*;

    #[test]
    fn locks_coordinate_independent_engine_processes() {
        const CHILD_ROOT: &str = "ENCAP_VIDEO_LOCK_TEST_ROOT";
        const CHILD_BLOCKED: &str = "ENCAP_VIDEO_LOCK_TEST_BLOCKED";
        if let Some(root) = std::env::var_os(CHILD_ROOT) {
            let root = PathBuf::from(root);
            let token = CancellationToken::default();
            let signal = token.clone();
            let cancel = std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(150));
                signal.cancel();
            });
            let destination = root.join("out.mp4");
            let result = OperationGuard::acquire_in(&root, Some(&destination), &token);
            if std::env::var_os(CHILD_BLOCKED).is_some() {
                assert!(result.is_err(), "Child bypassed a held coordination lock");
            } else {
                assert!(result.is_ok(), "Released coordination lock remained held");
            }
            cancel.join().unwrap();
            return;
        }
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("out.mp4");
        let token = CancellationToken::default();
        let run_child = |blocked: bool| {
            let mut command = std::process::Command::new(std::env::current_exe().unwrap());
            command
                .args([
                    "--exact",
                    "lifecycle::process_lock_tests::locks_coordinate_independent_engine_processes",
                ])
                .env(CHILD_ROOT, root.path());
            if blocked {
                command.env(CHILD_BLOCKED, "1");
            }
            let output = command.output().unwrap();
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stdout)
            );
        };
        let destination_guard =
            OperationGuard::acquire_in(root.path(), Some(&output), &token).unwrap();
        run_child(true);
        drop(destination_guard);
        let first = OperationGuard::acquire_in(root.path(), None, &token).unwrap();
        let second = OperationGuard::acquire_in(root.path(), None, &token).unwrap();
        run_child(true);
        drop(first);
        drop(second);
        run_child(false);
    }
}
