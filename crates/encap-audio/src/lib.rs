//! Audio-mode ingest, chapter editing, and final encode support.

use encap_core::{conflicts_with_path, replace_staged_file, EncapError, ProjectDocument, Result};
use encap_ffmpeg::{os, CancellationToken, MediaTools};
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::Builder;

pub fn inspect(folder: &Path) -> Result<ProjectDocument> {
    encap_core::inspect_folder(folder)
}

pub fn export(
    project: &ProjectDocument,
    destination: &Path,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    validate_export(project, destination)?;
    let tools = MediaTools::discover_with_cancellation(cancellation)?;
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let suffix = format!(".{}", project.export_settings.extension());
    let staging_dir = Builder::new()
        .prefix(".encap-export-")
        .tempdir_in(parent)
        .map_err(|source| EncapError::Write {
            path: destination.to_path_buf(),
            source,
        })?;
    let staged_output = staging_dir.path().join(format!("output{suffix}"));
    let metadata_path = staging_dir.path().join("ffmetadata.txt");
    fs::write(&metadata_path, ffmetadata(project)).map_err(|source| EncapError::Write {
        path: metadata_path.clone(),
        source,
    })?;
    let arguments = export_arguments(project, &metadata_path, &staged_output);
    encap_ffmpeg::run(tools.ffmpeg(), &arguments, cancellation, "Audio export")?;
    replace_staged_file(&staged_output, destination)?;
    Ok(destination.to_path_buf())
}

pub fn export_arguments(
    project: &ProjectDocument,
    metadata: &Path,
    output: &Path,
) -> Vec<OsString> {
    let mut args = vec![os("-hide_banner"), os("-nostdin"), os("-y")];
    for source in &project.audio_sources {
        args.extend([os("-i"), file_argument(&source.source_path)]);
    }
    let artwork_index = project.metadata.artwork_path.as_ref().map(|artwork| {
        let index = project.audio_sources.len();
        args.extend([os("-i"), file_argument(artwork)]);
        index
    });
    let metadata_index = project.audio_sources.len() + usize::from(artwork_index.is_some());
    args.extend([
        os("-f"),
        os("ffmetadata"),
        os("-i"),
        file_argument(metadata),
    ]);
    let normalized = (0..project.audio_sources.len()).map(|index| {
        format!("[{index}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}];")
    }).collect::<String>();
    let inputs = (0..project.audio_sources.len())
        .map(|index| format!("[a{index}]"))
        .collect::<String>();
    args.extend([
        os("-filter_complex"),
        os(format!(
            "{normalized}{inputs}concat=n={}:v=0:a=1[outa]",
            project.audio_sources.len()
        )),
        os("-map"),
        os("[outa]"),
        os("-map_metadata"),
        os(metadata_index.to_string()),
        os("-map_chapters"),
        os(metadata_index.to_string()),
        os("-ac"),
        os(project.export_settings.channels.to_string()),
    ]);
    if let Some(index) = artwork_index {
        // A readable image such as PSD or TIFF cannot be copied directly into
        // an audio container. Embed one PNG frame and keep oversized artwork
        // out of the exported file without modifying the project's original.
        // Trim the image stream; an output frame limit can truncate the audio.
        args.extend([
            os("-map"),
            os(format!("{index}:v:0")),
            os("-c:v"),
            os("png"),
            os("-filter:v"),
            os("trim=end_frame=1,scale=w='min(3000,iw)':h='min(3000,ih)':force_original_aspect_ratio=decrease"),
            os("-disposition:v"),
            os("attached_pic"),
        ]);
    }
    match project
        .export_settings
        .output_format
        .to_ascii_lowercase()
        .as_str()
    {
        "aac" | "m4a" => args.extend([
            os("-c:a"),
            os(if project.export_settings.encoder == "audio_toolbox" {
                "aac_at"
            } else {
                "aac"
            }),
            os("-b:a"),
            os(&project.export_settings.quality_preset),
            os("-movflags"),
            os("+faststart"),
        ]),
        _ => args.extend([
            os("-c:a"),
            os("libmp3lame"),
            os("-b:a"),
            os(&project.export_settings.quality_preset),
            os("-id3v2_version"),
            os("3"),
        ]),
    }
    args.push(file_argument(output));
    args
}

fn file_argument(path: &Path) -> OsString {
    // FFmpeg parses a colon in a relative name as a protocol separator
    // ("10:01" is shown as "10/01" by Finder). Explicitly select local files
    // without changing the path bytes or applying URL/shell escaping.
    let mut argument = OsString::from("file:");
    argument.push(path);
    argument
}

pub fn ffmetadata(project: &ProjectDocument) -> String {
    let mut output = String::from(";FFMETADATA1\n");
    output.push_str(&format!(
        "album={}\n",
        escape(&project.metadata.podcast_title)
    ));
    output.push_str(&format!(
        "artist={}\n",
        escape(&project.metadata.podcast_title)
    ));
    output.push_str(&format!(
        "title={}\n",
        escape(&project.metadata.episode_title)
    ));
    output.push_str(&format!("comment={}\n", escape(&project.metadata.summary)));
    for chapter in &project.chapters {
        let start = (chapter.start_time_seconds * 1000.0).round() as u64;
        let end = ((chapter.start_time_seconds + chapter.duration_seconds) * 1000.0).round() as u64;
        output.push_str("\n[CHAPTER]\nTIMEBASE=1/1000\n");
        output.push_str(&format!(
            "START={start}\nEND={end}\ntitle={}\n",
            escape(&chapter.title)
        ));
        if !chapter.link_url.trim().is_empty() {
            output.push_str(&format!("url={}\n", escape(&chapter.link_url)));
        }
    }
    output
}

fn validate_export(project: &ProjectDocument, destination: &Path) -> Result<()> {
    project.validate()?;
    if project.metadata.podcast_title.trim().is_empty() {
        return Err(EncapError::Message("Podcast title is required.".into()));
    }
    if project.metadata.episode_title.trim().is_empty() {
        return Err(EncapError::Message("Episode title is required.".into()));
    }
    if project.audio_sources.is_empty() {
        return Err(EncapError::Message("Import audio before exporting.".into()));
    }
    if project.chapters.is_empty() {
        return Err(EncapError::Message(
            "At least one chapter is required.".into(),
        ));
    }
    for chapter in &project.chapters {
        if chapter.title.trim().is_empty() {
            return Err(EncapError::Message(
                "Every chapter must have a title.".into(),
            ));
        }
        if !chapter.link_url.trim().is_empty() && !chapter.link_url.contains("://") {
            return Err(EncapError::Message(format!(
                "Chapter link must be a full URL: {}",
                chapter.link_url
            )));
        }
    }
    if project
        .chapters
        .iter()
        .any(|chapter| chapter.image_path.is_some())
    {
        return Err(EncapError::Message(
            "Per-chapter artwork cannot be embedded safely yet. Remove chapter images before exporting audio.".into(),
        ));
    }
    for source in &project.audio_sources {
        if conflicts_with_path(destination, &source.source_path) {
            return Err(EncapError::Message(
                "The export destination must not overwrite source media.".into(),
            ));
        }
        if !source.source_path.is_file() {
            return Err(EncapError::Message(format!(
                "Audio source is missing: {}",
                source.source_path.display()
            )));
        }
    }
    if let Some(artwork) = &project.metadata.artwork_path {
        if conflicts_with_path(destination, artwork) {
            return Err(EncapError::Message(
                "The export destination must not overwrite project artwork.".into(),
            ));
        }
        if !artwork.is_file() {
            return Err(EncapError::Message(format!(
                "Episode artwork is missing: {}",
                artwork.display()
            )));
        }
    }
    for chapter in &project.chapters {
        if let Some(image) = &chapter.image_path {
            if conflicts_with_path(destination, image) {
                return Err(EncapError::Message(
                    "The export destination must not overwrite chapter artwork.".into(),
                ));
            }
        }
    }
    if let Some(proj_path) = &project.project_path {
        if conflicts_with_path(destination, proj_path) {
            return Err(EncapError::Message(
                "The export destination must not overwrite the project file.".into(),
            ));
        }
    }
    Ok(())
}

fn escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\n', "\\\n")
        .replace('=', "\\=")
        .replace(';', "\\;")
        .replace('#', "\\#")
}

#[cfg(test)]
mod tests {
    use super::*;
    use encap_core::{AudioSource, Chapter, EpisodeMetadata};
    use std::collections::BTreeMap;

    #[test]
    fn command_arguments_do_not_use_a_shell() {
        let mut project = ProjectDocument::default();
        project.audio_sources.push(AudioSource {
            source_path: PathBuf::from("audio;$(touch nope).wav"),
            display_name: "audio".into(),
            duration_seconds: 1.0,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        let args = export_arguments(&project, Path::new("meta file"), Path::new("out.mp3"));
        assert!(args
            .iter()
            .any(|arg| arg == std::ffi::OsStr::new("file:audio;$(touch nope).wav")));
        assert!(!args
            .iter()
            .any(|arg| arg.to_string_lossy().contains("sh -c")));
    }

    #[test]
    fn metadata_contains_chapters() {
        let project = ProjectDocument {
            metadata: EpisodeMetadata {
                podcast_title: "Show".into(),
                episode_title: "A=B".into(),
                ..Default::default()
            },
            chapters: vec![Chapter {
                id: "1".into(),
                start_time_seconds: 0.0,
                duration_seconds: 3.0,
                chapter_number: 1,
                title: "Intro".into(),
                link_url: String::new(),
                image_path: None,
                image_stored_path: None,
                extensions: BTreeMap::new(),
            }],
            ..Default::default()
        };
        let metadata = ffmetadata(&project);
        assert!(metadata.contains("album=Show"));
        assert!(metadata.contains("artist=Show"));
        assert!(metadata.contains("title=A\\=B"));
        assert!(metadata.contains("START=0\nEND=3000"));
    }

    #[test]
    fn test_export_rejects_source_conflict_and_preserves_bytes() {
        let temp = tempfile::tempdir().unwrap();
        let source_file = temp.path().join("original.wav");
        let original_content = b"RIFF....WAVEfmt ....data....test audio bytes";
        fs::write(&source_file, original_content).unwrap();

        let project = ProjectDocument {
            metadata: EpisodeMetadata {
                podcast_title: "Show".into(),
                episode_title: "Ep".into(),
                ..Default::default()
            },
            audio_sources: vec![AudioSource {
                display_name: "Source".into(),
                source_path: source_file.clone(),
                duration_seconds: 5.0,
                stored_path: None,
                extensions: BTreeMap::new(),
            }],
            chapters: vec![Chapter {
                id: "c1".into(),
                chapter_number: 1,
                title: "Chapter 1".into(),
                start_time_seconds: 0.0,
                duration_seconds: 5.0,
                link_url: String::new(),
                image_path: None,
                image_stored_path: None,
                extensions: BTreeMap::new(),
            }],
            ..Default::default()
        };

        // Test direct conflict
        let token = CancellationToken::default();
        let result = export(&project, &source_file, &token);
        assert!(result.is_err());
        assert_eq!(fs::read(&source_file).unwrap(), original_content);

        // Test conflict via parent traversal ..
        let rel_dest = temp.path().join("sub/../original.wav");
        let result2 = export(&project, &rel_dest, &token);
        assert!(result2.is_err());
        assert_eq!(fs::read(&source_file).unwrap(), original_content);

        #[cfg(unix)]
        {
            let symlink = temp.path().join("symlink.wav");
            std::os::unix::fs::symlink(&source_file, &symlink).unwrap();
            let result3 = export(&project, &symlink, &token);
            assert!(result3.is_err());
            assert_eq!(fs::read(&source_file).unwrap(), original_content);
        }
    }
}
