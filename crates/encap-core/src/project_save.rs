//! Disposable, machine-local save index. The ZIP remains the complete project;
//! losing this index only costs a full save. Never use it after the archive or
//! source file's identity/timestamps change.
use super::{add_file, safe_stored_path, MAX_MANIFEST};
use crate::{EncapError, ProjectDocument, Result};
use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::time::SystemTime;
use zip::write::SimpleFileOptions;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct FileStamp {
    length: u64,
    modified: SystemTime,
    created: Option<SystemTime>,
    #[cfg(unix)]
    identity: (u64, u64, i64, i64),
}

impl FileStamp {
    pub(super) fn read(path: &Path) -> std::io::Result<Self> {
        let metadata = fs::metadata(path)?;
        if !metadata.is_file() {
            return Err(std::io::Error::other("Expected a regular file"));
        }
        Ok(Self {
            length: metadata.len(),
            modified: metadata.modified()?,
            created: metadata.created().ok(),
            #[cfg(unix)]
            identity: {
                use std::os::unix::fs::MetadataExt;
                (
                    metadata.dev(),
                    metadata.ino(),
                    metadata.ctime(),
                    metadata.ctime_nsec(),
                )
            },
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct MediaFile {
    source: PathBuf,
    stored: String,
    stamp: FileStamp,
}

#[derive(Serialize, Deserialize)]
pub(super) struct SaveCache {
    version: u32,
    archive: PathBuf,
    stamp: FileStamp,
    media: Vec<MediaFile>,
}

impl SaveCache {
    fn path(archive: &Path) -> Option<PathBuf> {
        let canonical = fs::canonicalize(archive).ok()?;
        let key = Sha256::digest(canonical.as_os_str().as_encoded_bytes());
        let base_dir = std::env::var_os("ENCAP_SAVE_CACHE_DIR")
            .map(PathBuf::from)
            .or_else(|| {
                ProjectDirs::from("com", "TLO Labs", "EnCap")
                    .map(|dirs| dirs.cache_dir().to_path_buf())
            })?;
        Some(base_dir.join("save-index-v1").join(format!("{key:x}.json")))
    }

    pub(super) fn read(archive: &Path) -> Option<Self> {
        let mut bytes = Vec::new();
        File::open(Self::path(archive)?)
            .ok()?
            .take(MAX_MANIFEST + 1)
            .read_to_end(&mut bytes)
            .ok()?;
        if bytes.len() as u64 > MAX_MANIFEST {
            return None;
        }
        let cache: Self = serde_json::from_slice(&bytes).ok()?;
        if cache.version != 1
            || cache.archive != fs::canonicalize(archive).ok()?
            || cache.stamp != FileStamp::read(archive).ok()?
            || cache.media.iter().any(|file| {
                file.stored == "manifest.json" || safe_stored_path(&file.stored).is_err()
            })
        {
            return None;
        }
        Some(cache)
    }

    pub(super) fn record(archive: &Path, media: Vec<MediaFile>) {
        // The cache is optional. Failure here must not turn a committed save
        // into a reported failure, and readers must never see a partial index.
        let write = || -> Option<()> {
            let path = Self::path(archive)?;
            let cache = Self {
                version: 1,
                archive: fs::canonicalize(archive).ok()?,
                stamp: FileStamp::read(archive).ok()?,
                media,
            };
            fs::create_dir_all(path.parent()?).ok()?;
            let mut staged = tempfile::NamedTempFile::new_in(path.parent()?).ok()?;
            serde_json::to_writer(staged.as_file_mut(), &cache).ok()?;
            staged.persist(path).ok()?;
            Some(())
        };
        let _ = write();
    }

    pub(super) fn record_loaded(project: &ProjectDocument, original: Option<FileStamp>) {
        let Some(archive) = project.project_path.as_deref() else {
            return;
        };
        if original.is_none() || FileStamp::read(archive).ok() != original {
            return;
        }
        let collect = || -> Option<Vec<MediaFile>> {
            let mut files = Vec::new();
            let mut add = |path: &Path, stored: &str| -> Option<()> {
                if !files.iter().any(|file: &MediaFile| file.stored == stored) {
                    files.push(MediaFile {
                        source: fs::canonicalize(path).ok()?,
                        stored: stored.into(),
                        stamp: FileStamp::read(path).ok()?,
                    });
                }
                Some(())
            };
            for audio in &project.audio_sources {
                add(&audio.source_path, audio.stored_path.as_deref()?)?;
            }
            if let Some(path) = &project.metadata.artwork_path {
                add(path, project.metadata.artwork_stored_path.as_deref()?)?;
            }
            for chapter in &project.chapters {
                if let Some(path) = &chapter.image_path {
                    add(path, chapter.image_stored_path.as_deref()?)?;
                }
            }
            Some(files)
        };
        if let Some(files) = collect() {
            Self::record(archive, files);
        }
    }
}

pub(super) struct MediaPlan<'a> {
    previous: Option<&'a SaveCache>,
    pub(super) files: Vec<MediaFile>,
}

impl<'a> MediaPlan<'a> {
    pub(super) fn new(previous: Option<&'a SaveCache>) -> Self {
        Self {
            previous,
            files: Vec::new(),
        }
    }

    pub(super) fn add(&mut self, path: &Path, suggested: String) -> Result<String> {
        let source = fs::canonicalize(path).map_err(|source| EncapError::Read {
            path: path.into(),
            source,
        })?;
        if let Some(file) = self.files.iter().find(|file| file.source == source) {
            return Ok(file.stored.clone());
        }
        let stamp = FileStamp::read(path).map_err(|source| EncapError::Read {
            path: path.into(),
            source,
        })?;
        let mut stored = self
            .previous
            .and_then(|cache| cache.media.iter().find(|file| file.source == source))
            .map(|file| file.stored.clone())
            .unwrap_or_else(|| suggested.clone());
        let mut suffix = 0;
        while self.files.iter().any(|file| file.stored == stored) {
            suffix += 1;
            let (directory, name) = suggested.rsplit_once('/').unwrap_or(("media", &suggested));
            stored = format!("{directory}/{suffix}-{name}");
        }
        self.files.push(MediaFile {
            source,
            stored: stored.clone(),
            stamp,
        });
        Ok(stored)
    }

    fn verify_unchanged(&self) -> Result<()> {
        for file in &self.files {
            if FileStamp::read(&file.source).ok().as_ref() != Some(&file.stamp) {
                return Err(EncapError::Message(format!(
                    "Media changed while saving. Please save again: {}",
                    file.source.display()
                )));
            }
        }
        Ok(())
    }
}

pub(super) fn write_archive(
    staged: &Path,
    json: &[u8],
    plan: &MediaPlan<'_>,
    previous: Option<&SaveCache>,
) -> Result<()> {
    let write_error = |source| EncapError::Write {
        path: staged.into(),
        source,
    };
    let mut original = previous
        .and_then(|cache| File::open(&cache.archive).ok())
        .and_then(|file| zip::ZipArchive::new(file).ok());
    // Archives we create put the manifest last. Replace that tail in a staged
    // filesystem copy (copy-on-write on APFS), then atomically publish it. The
    // live archive is never appended to or truncated in place.
    let metadata_tail = previous
        .zip(original.as_mut())
        .and_then(|(cache, archive)| {
            if cache.media.len() != plan.files.len()
                || !plan.files.iter().all(|file| cache.media.contains(file))
                || archive.len() != plan.files.len() + 1
            {
                return None;
            }
            let manifest = archive.by_index(archive.len() - 1).ok()?;
            if manifest.name() != "manifest.json" {
                return None;
            }
            let offset = manifest.header_start();
            drop(manifest);
            // Central-directory order need not match physical entry order in an
            // externally generated ZIP. Never truncate through a media member.
            for file in &plan.files {
                let entry = archive.by_name(&file.stored).ok()?;
                if entry.data_start().checked_add(entry.compressed_size())? > offset {
                    return None;
                }
            }
            Some(offset)
        });
    let mut writer = if let Some(offset) = metadata_tail {
        crate::stage_archive_copy(&previous.unwrap().archive, staged).map_err(write_error)?;
        // Save As also works when the source archive is read-only. Only the
        // private staged copy needs to become writable.
        let mut permissions = fs::metadata(staged).map_err(write_error)?.permissions();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            permissions.set_mode(permissions.mode() | 0o600);
        }
        #[cfg(not(unix))]
        // This clears Windows' read-only attribute; Unix uses explicit mode bits above.
        #[allow(clippy::permissions_set_readonly_false)]
        permissions.set_readonly(false);
        fs::set_permissions(staged, permissions).map_err(write_error)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(staged)
            .map_err(write_error)?;
        let mut cursor = file.try_clone().map_err(write_error)?;
        let mut writer = zip::ZipWriter::new_append(file)?;
        writer.abort_file()?;
        // Parsed ZIP entries do not always let abort_file rewind. The cloned
        // File shares the writer's cursor; explicitly reset/truncate the staged
        // tail after the writer has read its directory and before any writes.
        cursor.set_len(offset).map_err(write_error)?;
        cursor.seek(SeekFrom::Start(offset)).map_err(write_error)?;
        writer
    } else {
        let mut create = OpenOptions::new();
        create.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            create.mode(0o600);
        }
        let mut writer = zip::ZipWriter::new(create.open(staged).map_err(write_error)?);
        // Audio and artwork are already encoded. Storing them avoids expensive
        // deflate passes on first save or when a source actually changes.
        let options =
            SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored);
        for file in &plan.files {
            let reusable = previous.is_some_and(|cache| cache.media.contains(file));
            if let Some(existing) = original
                .as_mut()
                .filter(|_| reusable)
                .and_then(|archive| archive.by_name(&file.stored).ok())
            {
                writer.raw_copy_file(existing)?;
            } else {
                add_file(
                    &mut writer,
                    &file.source,
                    &file.stored,
                    options.large_file(file.stamp.length >= u32::MAX as u64),
                )?;
            }
        }
        writer
    };
    writer.start_file(
        "manifest.json",
        SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated),
    )?;
    writer.write_all(json).map_err(write_error)?;
    let mut file = writer.finish()?;
    // A shorter manifest must not leave the previous end-of-directory record
    // behind, or ZIP readers can reopen the stale manifest.
    let end = file.stream_position().map_err(write_error)?;
    file.set_len(end).map_err(write_error)?;
    file.sync_all().map_err(write_error)?;
    plan.verify_unchanged()?;
    if previous
        .is_some_and(|cache| FileStamp::read(&cache.archive).ok().as_ref() != Some(&cache.stamp))
    {
        return Err(EncapError::Message(
            "The project file changed while saving. Please save again.".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{load_project, save_project, AudioSource, WorkspaceMode};
    use std::collections::BTreeMap;
    use std::time::Instant;

    fn fixture(root: &Path) -> ProjectDocument {
        let source = root.join("source.wav");
        fs::write(&source, b"original audio").unwrap();
        let artwork = root.join("cover.png");
        fs::write(&artwork, b"original image").unwrap();
        let mut project = ProjectDocument::default();
        project.audio_sources.push(AudioSource {
            source_path: source,
            display_name: "Source".into(),
            duration_seconds: 1.0,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        project.metadata.artwork_path = Some(artwork);
        project
    }

    fn remove_cache(path: &Path) {
        if let Some(path) = SaveCache::path(path) {
            let _ = fs::remove_file(path);
        }
    }

    #[test]
    fn repeated_metadata_saves_reopen_and_do_not_accumulate_old_manifests() {
        let root = tempfile::tempdir().unwrap();
        let mut project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        let initial_size = fs::metadata(&path).unwrap().len();
        for index in 0..20 {
            project.metadata.summary = if index % 2 == 0 {
                "long description".repeat(1000)
            } else {
                String::new()
            };
            project.active_mode = if index % 2 == 0 {
                WorkspaceMode::Video
            } else {
                WorkspaceMode::Audio
            };
            assert!(SaveCache::read(&path).is_some());
            save_project(&project, &path).unwrap();
            let mut zip = zip::ZipArchive::new(File::open(&path).unwrap()).unwrap();
            assert_eq!(zip.len(), 3);
            let mut json = String::new();
            zip.by_name("manifest.json")
                .unwrap()
                .read_to_string(&mut json)
                .unwrap();
            let manifest: serde_json::Value = serde_json::from_str(&json).unwrap();
            assert_eq!(manifest["metadata"]["summary"], project.metadata.summary);
        }
        assert_eq!(fs::metadata(&path).unwrap().len(), initial_size);
        let restored = load_project(&path, Some(root.path())).unwrap();
        assert_eq!(
            fs::read(&restored.audio_sources[0].source_path).unwrap(),
            b"original audio"
        );
        remove_cache(&path);
    }

    #[test]
    fn reopening_populates_index_even_when_native_client_drops_stored_paths() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        remove_cache(&path);
        let mut loaded = load_project(&path, Some(root.path())).unwrap();
        let old_name = loaded.audio_sources[0].stored_path.take().unwrap();
        loaded.metadata.artwork_stored_path = None;
        loaded.active_mode = WorkspaceMode::Transcript;
        let cache = SaveCache::read(&path).unwrap();
        let mut plan = MediaPlan::new(Some(&cache));
        assert_eq!(
            plan.add(&loaded.audio_sources[0].source_path, "audio/new.wav".into())
                .unwrap(),
            old_name
        );
        save_project(&loaded, &path).unwrap();
        let restored = load_project(&path, Some(root.path())).unwrap();
        assert_eq!(
            restored.audio_sources[0].stored_path.as_deref(),
            Some(old_name.as_str())
        );
        assert_eq!(restored.active_mode, WorkspaceMode::Transcript);
        remove_cache(&path);
    }

    #[test]
    fn same_length_media_edits_and_removed_artwork_are_saved() {
        let root = tempfile::tempdir().unwrap();
        let mut project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        fs::write(&project.audio_sources[0].source_path, b"modified audio").unwrap();
        fs::write(
            project.metadata.artwork_path.as_ref().unwrap(),
            b"modified image",
        )
        .unwrap();
        save_project(&project, &path).unwrap();
        let restored = load_project(&path, Some(root.path())).unwrap();
        assert_eq!(
            fs::read(&restored.audio_sources[0].source_path).unwrap(),
            b"modified audio"
        );
        assert_eq!(
            fs::read(restored.metadata.artwork_path.unwrap()).unwrap(),
            b"modified image"
        );
        project.metadata.artwork_path = None;
        save_project(&project, &path).unwrap();
        let restored = load_project(&path, Some(root.path())).unwrap();
        assert!(restored.metadata.artwork_path.is_none());
        let zip = zip::ZipArchive::new(File::open(&path).unwrap()).unwrap();
        assert_eq!(zip.len(), 2);
        remove_cache(&path);
    }

    #[test]
    fn missing_media_does_not_replace_previous_save() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        let before = fs::read(&path).unwrap();
        fs::remove_file(&project.audio_sources[0].source_path).unwrap();
        assert!(save_project(&project, &path).is_err());
        assert_eq!(fs::read(&path).unwrap(), before);
        remove_cache(&path);
    }

    #[test]
    fn changed_artwork_preserves_existing_compressed_audio_without_reencoding() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        let mut original = zip::ZipArchive::new(File::open(&path).unwrap()).unwrap();
        let legacy = root.path().join("legacy.encap");
        let mut writer = zip::ZipWriter::new(File::create(&legacy).unwrap());
        // Simulate the previous version's deflated media archive.
        for index in 0..original.len() {
            let mut entry = original.by_index(index).unwrap();
            writer
                .start_file(
                    entry.name(),
                    SimpleFileOptions::default()
                        .compression_method(zip::CompressionMethod::Deflated),
                )
                .unwrap();
            std::io::copy(&mut entry, &mut writer).unwrap();
        }
        writer.finish().unwrap();
        let loaded = load_project(&legacy, Some(root.path())).unwrap();
        fs::write(
            loaded.metadata.artwork_path.as_ref().unwrap(),
            b"changed artwork",
        )
        .unwrap();
        save_project(&loaded, &legacy).unwrap();
        let mut zip = zip::ZipArchive::new(File::open(&legacy).unwrap()).unwrap();
        let mut audio = zip
            .by_name(loaded.audio_sources[0].stored_path.as_ref().unwrap())
            .unwrap();
        assert_eq!(audio.compression(), zip::CompressionMethod::Deflated);
        let mut bytes = Vec::new();
        audio.read_to_end(&mut bytes).unwrap();
        assert_eq!(bytes, b"original audio");
        drop(audio);
        let mut artwork = zip
            .by_name(loaded.metadata.artwork_stored_path.as_ref().unwrap())
            .unwrap();
        bytes.clear();
        artwork.read_to_end(&mut bytes).unwrap();
        assert_eq!(bytes, b"changed artwork");
        remove_cache(&path);
        remove_cache(&legacy);
    }

    #[test]
    fn cache_loss_and_external_archive_replacement_fall_back_to_complete_save() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let path = save_project(&project, &root.path().join("project.encap")).unwrap();
        fs::write(&path, b"externally replaced").unwrap();
        assert!(SaveCache::read(&path).is_none());
        save_project(&project, &path).unwrap();
        remove_cache(&path);
        save_project(&project, &path).unwrap();
        let restored = load_project(&path, Some(root.path())).unwrap();
        assert_eq!(
            fs::read(&restored.audio_sources[0].source_path).unwrap(),
            b"original audio"
        );
        remove_cache(&path);
    }

    #[test]
    fn changing_media_during_save_is_rejected_before_commit() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let mut plan = MediaPlan::new(None);
        plan.add(
            &project.audio_sources[0].source_path,
            "audio/source.wav".into(),
        )
        .unwrap();
        fs::write(&project.audio_sources[0].source_path, b"modified audio").unwrap();
        assert!(write_archive(&root.path().join("staged"), b"{}", &plan, None).is_err());
    }

    #[test]
    fn save_cache_respects_env_override() {
        let temp = tempfile::tempdir().unwrap();
        let archive = temp.path().join("test.encap");
        fs::write(&archive, b"dummy").unwrap();

        let custom_cache = temp.path().join("custom-cache");
        std::env::set_var("ENCAP_SAVE_CACHE_DIR", &custom_cache);

        let cache_path = SaveCache::path(&archive).unwrap();
        assert!(cache_path.starts_with(&custom_cache));

        std::env::remove_var("ENCAP_SAVE_CACHE_DIR");
    }

    #[test]
    #[ignore = "writes a 256 MiB fixture; run in release mode to measure save latency"]
    fn benchmark_large_project_saves() {
        let root = tempfile::tempdir().unwrap();
        let mut project = fixture(root.path());
        let mut source = File::create(&project.audio_sources[0].source_path).unwrap();
        let mut state = 42u64;
        let chunk: Vec<u8> = (0..1024 * 1024)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                state as u8
            })
            .collect();
        for _ in 0..256 {
            source.write_all(&chunk).unwrap();
        }
        source.sync_all().unwrap();
        drop(source);
        let start = Instant::now();
        let mut baseline =
            zip::ZipWriter::new(File::create(root.path().join("old-save.zip")).unwrap());
        add_file(
            &mut baseline,
            &project.audio_sources[0].source_path,
            "audio/source.wav",
            SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated),
        )
        .unwrap();
        baseline.finish().unwrap().sync_all().unwrap();
        eprintln!(
            "256 MiB previous full-deflate save path: {:?}",
            start.elapsed()
        );
        let start = Instant::now();
        let path = save_project(&project, &root.path().join("large.encap")).unwrap();
        eprintln!("256 MiB first save: {:?}", start.elapsed());
        for mode in [
            WorkspaceMode::Video,
            WorkspaceMode::Transcript,
            WorkspaceMode::Audio,
        ] {
            project.active_mode = mode;
            let start = Instant::now();
            save_project(&project, &path).unwrap();
            eprintln!("256 MiB metadata save ({mode:?}): {:?}", start.elapsed());
        }
        let mut loaded = load_project(&path, Some(root.path())).unwrap();
        loaded.active_mode = WorkspaceMode::Video;
        let start = Instant::now();
        save_project(&loaded, &path).unwrap();
        eprintln!("256 MiB first save after reopen: {:?}", start.elapsed());
        remove_cache(&path);
    }
}
