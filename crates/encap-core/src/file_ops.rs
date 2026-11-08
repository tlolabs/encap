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
    let parent = match destination.parent() {
        Some(p) if !p.as_os_str().is_empty() => p,
        _ => Path::new("."),
    };
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
        let parent = if _parent.as_os_str().is_empty() {
            Path::new(".")
        } else {
            _parent
        };
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

fn resolve_for_conflict_check(path: &Path, canon: Option<PathBuf>) -> PathBuf {
    if let Some(c) = canon {
        return c;
    }
    let lex = normalize_path(path);
    if let Ok(c) = fs::canonicalize(&lex) {
        return c;
    }
    let absolute = if lex.is_absolute() {
        lex
    } else {
        std::env::current_dir().unwrap_or_default().join(lex)
    };
    if let Ok(c) = fs::canonicalize(&absolute) {
        return c;
    }
    let mut ancestor = absolute.as_path();
    let mut missing = Vec::new();
    let mut resolved = loop {
        match fs::canonicalize(ancestor) {
            Ok(c) => break c,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                if let Some(file_name) = ancestor.file_name() {
                    missing.push(file_name.to_os_string());
                }
                match ancestor.parent() {
                    Some(parent) => ancestor = parent,
                    None => break ancestor.to_path_buf(),
                }
            }
            Err(_) => break ancestor.to_path_buf(),
        }
    };
    for component in missing.into_iter().rev() {
        resolved.push(component);
    }
    resolved
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

    // 3. Symmetric normalization for non-existent or future target files
    let dest_resolved = resolve_for_conflict_check(destination, dest_canon);
    let src_resolved = resolve_for_conflict_check(source, src_canon);

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

    #[test]
    #[cfg(unix)]
    fn detects_conflicts_across_symlinked_directories_for_nonexistent_targets() {
        let temporary = tempfile::tempdir().unwrap();
        let real_dir = temporary.path().join("real_folder");
        let sym_dir = temporary.path().join("sym_folder");
        fs::create_dir_all(&real_dir).unwrap();
        std::os::unix::fs::symlink(&real_dir, &sym_dir).unwrap();

        let real_future = real_dir.join("future_output.wav");
        let sym_future = sym_dir.join("future_output.wav");

        // Neither file exists yet: must detect conflict symmetrically
        assert!(conflicts_with_path(&real_future, &sym_future));
        assert!(conflicts_with_path(&sym_future, &real_future));

        // When source exists in real_dir and destination is nonexistent in sym_dir:
        fs::write(&real_future, b"media content").unwrap();
        assert!(conflicts_with_path(&sym_future, &real_future));
        assert!(conflicts_with_path(&real_future, &sym_future));
    }

    #[test]
    fn detects_relative_bare_filename_conflict_with_current_dir() {
        let current = std::env::current_dir().unwrap();
        let canon_current = fs::canonicalize(&current).unwrap();
        let file_name = "test_nonexistent_conflict_target.encap";

        let bare_relative = Path::new(file_name);
        let absolute_target = canon_current.join(file_name);

        assert!(conflicts_with_path(bare_relative, &absolute_target));
        assert!(conflicts_with_path(&absolute_target, bare_relative));
    }

    #[test]
    #[cfg(unix)]
    fn detects_conflicts_across_symlinked_directories_with_nonexistent_subdirectories() {
        let temporary = tempfile::tempdir().unwrap();
        let real_dir = temporary.path().join("real_folder");
        let sym_dir = temporary.path().join("sym_folder");
        fs::create_dir_all(&real_dir).unwrap();
        std::os::unix::fs::symlink(&real_dir, &sym_dir).unwrap();

        let real_future = real_dir.join("nested_sub").join("future_output.wav");
        let sym_future = sym_dir.join("nested_sub").join("future_output.wav");

        assert!(conflicts_with_path(&real_future, &sym_future));
        assert!(conflicts_with_path(&sym_future, &real_future));
    }

    #[test]
    fn replaces_bare_relative_file_in_current_dir() {
        let id = uuid::Uuid::new_v4().simple().to_string();
        let staged = PathBuf::from(format!(".staged-{id}.tmp"));
        let destination = PathBuf::from(format!(".dest-{id}.tmp"));
        fs::write(&staged, b"bare replacement").unwrap();
        fs::write(&destination, b"bare original").unwrap();

        let result = replace_staged_file(&staged, &destination);
        let read = fs::read(&destination);
        let _ = fs::remove_file(&destination);
        let _ = fs::remove_file(&staged);

        result.unwrap();
        assert_eq!(read.unwrap(), b"bare replacement");
    }
}
