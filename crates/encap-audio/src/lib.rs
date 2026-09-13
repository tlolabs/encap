//! Audio-mode ingest, chapter editing, and final encode support.

use encap_core::{replace_staged_file, EncapError, ProjectDocument, Result};
use encap_ffmpeg::{os, CancellationToken, MediaTools};
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::{Builder, NamedTempFile};

pub fn inspect(folder: &Path) -> Result<ProjectDocument> {
    encap_core::inspect_folder(folder)
}

pub fn export(
    project: &ProjectDocument,
    destination: &Path,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    validate_export(project, destination)?;
    let tools = MediaTools::discover()?;
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let suffix = format!(".{}", project.export_settings.extension());
    let temporary = Builder::new()
        .prefix(".encap-export-")
        .suffix(&suffix)
        .tempfile_in(parent)
        .map_err(|source| EncapError::Write {
            path: destination.to_path_buf(),
            source,
        })?;
    let temporary_path = temporary.path().to_path_buf();
    drop(temporary);
    let metadata = NamedTempFile::new().map_err(|source| EncapError::Write {
        path: destination.to_path_buf(),
        source,
    })?;
    fs::write(metadata.path(), ffmetadata(project)).map_err(|source| EncapError::Write {
        path: metadata.path().to_path_buf(),
        source,
    })?;
    let arguments = export_arguments(project, metadata.path(), &temporary_path);
    if let Err(error) = encap_ffmpeg::run(tools.ffmpeg(), &arguments, cancellation, "Audio export")
    {
        let _ = fs::remove_file(&temporary_path);
        return Err(error);
    }
    replace_staged_file(&temporary_path, destination)?;
    Ok(destination.to_path_buf())
}

pub fn export_arguments(
    project: &ProjectDocument,
    metadata: &Path,
    output: &Path,
) -> Vec<OsString> {
    let mut args = vec![os("-hide_banner"), os("-nostdin"), os("-y")];
    for source in &project.audio_sources {
        args.extend([os("-i"), os(&source.source_path)]);
    }
    let artwork_index = project.metadata.artwork_path.as_ref().map(|artwork| {
        let index = project.audio_sources.len();
        args.extend([os("-i"), os(artwork)]);
        index
    });
    let metadata_index = project.audio_sources.len() + usize::from(artwork_index.is_some());
    args.extend([os("-f"), os("ffmetadata"), os("-i"), os(metadata)]);
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
        args.extend([
            os("-map"),
            os(format!("{index}:v:0")),
            os("-c:v"),
            os("copy"),
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
    args.push(os(output));
    args
}

pub fn ffmetadata(project: &ProjectDocument) -> String {
    let mut output = String::from(";FFMETADATA1\n");
    output.push_str(&format!(
        "album={}\n",
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
    if project.audio_sources.is_empty() {
        return Err(EncapError::Message("Import audio before exporting.".into()));
    }
    if project.chapters.is_empty() {
        return Err(EncapError::Message(
            "At least one chapter is required.".into(),
        ));
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
    let destination = absolute(destination)?;
    for source in &project.audio_sources {
        if absolute(&source.source_path)? == destination {
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
        if !artwork.is_file() {
            return Err(EncapError::Message(format!(
                "Episode artwork is missing: {}",
                artwork.display()
            )));
        }
    }
    Ok(())
}

fn absolute(path: &Path) -> Result<PathBuf> {
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        Ok(std::env::current_dir()
            .map_err(|source| EncapError::Read {
                path: path.to_path_buf(),
                source,
            })?
            .join(path))
    }
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
            .any(|arg| arg == std::ffi::OsStr::new("audio;$(touch nope).wav")));
        assert!(!args
            .iter()
            .any(|arg| arg.to_string_lossy().contains("sh -c")));
    }

    #[test]
    fn metadata_contains_chapters() {
        let project = ProjectDocument {
            metadata: EpisodeMetadata {
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
        assert!(metadata.contains("title=A\\=B"));
        assert!(metadata.contains("START=0\nEND=3000"));
    }
}
