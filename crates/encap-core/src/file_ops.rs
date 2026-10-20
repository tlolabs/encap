use crate::{EncapError, Result};
use std::fs;
#[cfg(unix)]
use std::fs::File;
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

fn sync_parent(_parent: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        let parent = _parent;
        match File::open(parent).and_then(|file| file.sync_all()) {
            Ok(()) => {}
            Err(source) => {
                let is_tolerated_kind = matches!(
                    source.kind(),
                    std::io::ErrorKind::PermissionDenied | std::io::ErrorKind::Unsupported
                );
                let is_tolerated_raw = match source.raw_os_error() {
                    // 1: EPERM, 13: EACCES, 22: EINVAL, 30: EROFS, 45: ENOTSUP (macOS/BSD), 95: ENOTSUP (Linux)
                    Some(code) => matches!(code, 1 | 13 | 22 | 30 | 45 | 95),
                    None => false,
                };
                if !is_tolerated_kind && !is_tolerated_raw {
                    return Err(EncapError::Write {
                        path: parent.to_path_buf(),
                        source,
                    });
                }
            }
        }
    }
    Ok(())
}

fn normalize_path(path: &Path) -> PathBuf {
    use std::path::Component;
    let mut components = Vec::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                if let Some(Component::Normal(_)) = components.last() {
                    components.pop();
                } else {
                    components.push(component);
                }
            }
            _ => components.push(component),
        }
    }
    components.into_iter().collect()
}

/// Determines whether `destination` refers to the same file or path as `source`,
/// accounting for symlinks, aliases, parent `..` normalization, hardlinks, and filesystem identity.
pub fn conflicts_with_path(destination: &Path, source: &Path) -> bool {
    let dest_lex = normalize_path(destination);
    let src_lex = normalize_path(source);

    // 1. Direct equality after canonicalization
    let dest_canon = fs::canonicalize(&dest_lex)
        .or_else(|_| fs::canonicalize(destination))
        .ok();
    let src_canon = fs::canonicalize(&src_lex)
        .or_else(|_| fs::canonicalize(source))
        .ok();

    if let (Some(dc), Some(sc)) = (&dest_canon, &src_canon) {
        if dc == sc {
            return true;
        }
    }

    // 2. Physical file identity (device/inode or volume/file index) if both exist
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if let (Ok(m1), Ok(m2)) = (fs::metadata(destination), fs::metadata(source)) {
            if m1.dev() == m2.dev() && m1.ino() == m2.ino() {
                return true;
            }
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if let (Ok(m1), Ok(m2)) = (fs::metadata(destination), fs::metadata(source)) {
            if let (Some(v1), Some(v2)) = (m1.volume_serial_number(), m2.volume_serial_number()) {
                if let (Some(i1), Some(i2)) = (m1.file_index(), m2.file_index()) {
                    if v1 == v2 && i1 == i2 {
                        return true;
                    }
                }
            }
        }
    }

    // 3. Normalization for non-existent destination or future file
    let dest_resolved = if let Some(canon) = dest_canon {
        canon
    } else if let Some(parent) = dest_lex.parent() {
        let parent_norm = fs::canonicalize(parent).unwrap_or_else(|_| {
            if parent.is_absolute() {
                parent.to_path_buf()
            } else {
                std::env::current_dir().unwrap_or_default().join(parent)
            }
        });
        if let Some(file_name) = dest_lex.file_name() {
            parent_norm.join(file_name)
        } else {
            dest_lex.clone()
        }
    } else {
        dest_lex.clone()
    };

    let src_resolved = if let Some(canon) = src_canon {
        canon
    } else if src_lex.is_absolute() {
        src_lex
    } else {
        std::env::current_dir().unwrap_or_default().join(src_lex)
    };

    #[cfg(any(target_os = "macos", target_os = "windows"))]
    {
        if dest_resolved == src_resolved
            || dest_resolved.to_string_lossy().to_lowercase()
                == src_resolved.to_string_lossy().to_lowercase()
        {
            return true;
        }
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        if dest_resolved == src_resolved {
            return true;
        }
    }

    false
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

    #[test]
    fn detects_conflicting_paths_with_symlinks_and_aliases() {
        let temporary = tempfile::tempdir().unwrap();
        let source = temporary.path().join("recording.wav");
        fs::write(&source, b"original audio bytes").unwrap();

        // Direct conflict
        assert!(conflicts_with_path(&source, &source));

        // Relative with ..
        let rel_conflict = temporary.path().join("subdir/../recording.wav");
        assert!(conflicts_with_path(&rel_conflict, &source));

        // Symlink to source
        #[cfg(unix)]
        {
            let symlink = temporary.path().join("link.wav");
            std::os::unix::fs::symlink(&source, &symlink).unwrap();
            assert!(conflicts_with_path(&symlink, &source));
            assert!(conflicts_with_path(&source, &symlink));

            // Hardlink to source
            let hardlink = temporary.path().join("hardlink.wav");
            fs::hard_link(&source, &hardlink).unwrap();
            assert!(conflicts_with_path(&hardlink, &source));
        }

        // Distinct file does not conflict
        let distinct = temporary.path().join("export.mp3");
        assert!(!conflicts_with_path(&distinct, &source));

        // Original bytes remain unchanged
        assert_eq!(fs::read(&source).unwrap(), b"original audio bytes");
    }
}
