use crate::{EncapError, Result};
use std::fs::{self, File};
use std::path::{Path, PathBuf};
use uuid::Uuid;

/// Replace `destination` with a completed file staged in the same directory.
///
/// POSIX rename replaces atomically. Platforms whose rename API refuses to
/// replace an existing file use a same-directory recovery backup. If the final
/// rename fails, the original is restored before the error is returned.
pub fn replace_staged_file(staged: &Path, destination: &Path) -> Result<()> {
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    match fs::rename(staged, destination) {
        Ok(()) => sync_parent(parent),
        Err(first_error) if destination.is_file() => {
            let backup = recovery_path(destination);
            fs::rename(destination, &backup).map_err(|_| EncapError::Write {
                path: destination.to_path_buf(),
                source: first_error,
            })?;
            if let Err(source) = fs::rename(staged, destination) {
                let _ = fs::rename(&backup, destination);
                return Err(EncapError::Write {
                    path: destination.to_path_buf(),
                    source,
                });
            }
            if let Err(source) = fs::remove_file(&backup) {
                tracing::warn!(
                    path = %backup.display(),
                    error = %source,
                    "completed replacement left a recoverable backup"
                );
            }
            sync_parent(parent)
        }
        Err(source) => Err(EncapError::Write {
            path: destination.to_path_buf(),
            source,
        }),
    }
}

fn recovery_path(destination: &Path) -> PathBuf {
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("encap-output");
    destination.with_file_name(format!(".{name}.recovery-{}", Uuid::new_v4().simple()))
}

fn sync_parent(parent: &Path) -> Result<()> {
    #[cfg(unix)]
    File::open(parent)
        .and_then(|file| file.sync_all())
        .map_err(|source| EncapError::Write {
            path: parent.to_path_buf(),
            source,
        })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replaces_existing_file_after_staging_completes() {
        let temporary = tempfile::tempdir().unwrap();
        let staged = temporary.path().join("staged");
        let destination = temporary.path().join("project.encap");
        fs::write(&staged, b"complete replacement").unwrap();
        fs::write(&destination, b"known good original").unwrap();

        replace_staged_file(&staged, &destination).unwrap();

        assert_eq!(fs::read(destination).unwrap(), b"complete replacement");
        assert!(!staged.exists());
    }
}
