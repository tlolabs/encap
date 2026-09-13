//! Video-mode presets, capability detection, timeline construction, and MP4 export.

use encap_core::{
    replace_staged_file, Chapter, EncapError, ProjectDocument, Result, VideoSettings,
};
use encap_ffmpeg::{os, CancellationToken, MediaTools};
use serde::Serialize;
use std::collections::HashSet;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::Builder;

const MAX_OUTPUT_DIMENSION: u32 = 8192;
const MAX_OUTPUT_PIXELS: u64 = 33_177_600;
const MAX_SOURCE_IMAGE_DIMENSION: u64 = 32_768;
const MAX_SOURCE_IMAGE_PIXELS: u64 = 50_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct VideoPreset {
    pub platform: &'static str,
    pub aspect: &'static str,
    pub width: u32,
    pub height: u32,
    pub fps: u32,
}

pub const PRESETS: &[VideoPreset] = &[
    VideoPreset {
        platform: "Instagram",
        aspect: "Horizontal video (16:9)",
        width: 1920,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Instagram",
        aspect: "Square (1:1)",
        width: 1080,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Instagram",
        aspect: "4:5",
        width: 1080,
        height: 1350,
        fps: 30,
    },
    VideoPreset {
        platform: "Instagram",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "TikTok",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "TikTok",
        aspect: "Vertical video (9:16)",
        width: 720,
        height: 1280,
        fps: 30,
    },
    VideoPreset {
        platform: "Facebook",
        aspect: "Horizontal video (16:9)",
        width: 1280,
        height: 720,
        fps: 30,
    },
    VideoPreset {
        platform: "Facebook",
        aspect: "Square (1:1)",
        width: 1080,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Facebook",
        aspect: "Vertical video (9:16)",
        width: 720,
        height: 1280,
        fps: 30,
    },
    VideoPreset {
        platform: "Facebook",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "Facebook",
        aspect: "4:5",
        width: 1080,
        height: 1350,
        fps: 30,
    },
    VideoPreset {
        platform: "Twitter / X",
        aspect: "Horizontal video (16:9)",
        width: 1280,
        height: 720,
        fps: 30,
    },
    VideoPreset {
        platform: "Twitter / X",
        aspect: "Square (1:1)",
        width: 720,
        height: 720,
        fps: 30,
    },
    VideoPreset {
        platform: "Twitter / X",
        aspect: "Vertical video (9:16)",
        width: 720,
        height: 1280,
        fps: 30,
    },
    VideoPreset {
        platform: "YouTube",
        aspect: "Horizontal video (16:9)",
        width: 1920,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "YouTube",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "YouTube",
        aspect: "Square (1:1)",
        width: 1080,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "YouTube",
        aspect: "4:3",
        width: 1440,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "LinkedIn",
        aspect: "Horizontal video (16:9)",
        width: 1920,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "LinkedIn",
        aspect: "Square (1:1)",
        width: 1080,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Snapchat",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "Pinterest",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "Generic",
        aspect: "Horizontal video (16:9)",
        width: 1920,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Generic",
        aspect: "Vertical video (9:16)",
        width: 1080,
        height: 1920,
        fps: 30,
    },
    VideoPreset {
        platform: "Generic",
        aspect: "Square (1:1)",
        width: 1080,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Generic",
        aspect: "4:3",
        width: 1440,
        height: 1080,
        fps: 30,
    },
    VideoPreset {
        platform: "Generic",
        aspect: "4:5",
        width: 1080,
        height: 1350,
        fps: 30,
    },
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct VideoEncoderCapability {
    pub codec: String,
    pub encoder: String,
    pub hardware: bool,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct VideoCapabilities {
    pub encoders: Vec<VideoEncoderCapability>,
}

pub fn capabilities() -> Result<VideoCapabilities> {
    let tools = MediaTools::discover()?;
    let output = encap_ffmpeg::run(
        tools.ffmpeg(),
        &[os("-hide_banner"), os("-encoders")],
        &CancellationToken::default(),
        "Video encoder detection",
    )?;
    Ok(parse_capabilities(&String::from_utf8_lossy(&output.stdout)))
}

pub fn export(
    project: &ProjectDocument,
    destination: &Path,
    cancellation: &CancellationToken,
) -> Result<PathBuf> {
    project.validate()?;
    validate_destination(project, destination)?;
    let tools = MediaTools::discover()?;
    let main_artwork = project.metadata.artwork_path.as_ref().ok_or_else(|| {
        EncapError::Message("Add project artwork in Audio before using Video.".into())
    })?;
    validate_source_image(&tools, main_artwork, cancellation)?;
    let detected = capabilities()?;
    let encoder = select_encoder(&project.video.export_settings, &detected)?;
    let chapters = selected_chapters(project)?;
    let mut checked_artwork = HashSet::new();
    for chapter in &chapters {
        let artwork = chapter
            .image_path
            .as_ref()
            .or(project.metadata.artwork_path.as_ref())
            .ok_or_else(|| {
                EncapError::Message("Add project artwork in Audio before using Video.".into())
            })?;
        if checked_artwork.insert(artwork.clone()) {
            validate_source_image(&tools, artwork, cancellation)?;
        }
    }
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|source| EncapError::Write {
        path: parent.to_path_buf(),
        source,
    })?;
    let temporary = Builder::new()
        .prefix(".encap-video-")
        .suffix(".mp4")
        .tempfile_in(parent)
        .map_err(|source| EncapError::Write {
            path: destination.to_path_buf(),
            source,
        })?;
    let staged = temporary.path().to_path_buf();
    drop(temporary);
    let arguments = export_arguments(project, &chapters, &encoder, &staged)?;
    if let Err(hardware_error) =
        encap_ffmpeg::run(tools.ffmpeg(), &arguments, cancellation, "Video export")
    {
        let automatic_hardware = project
            .video
            .export_settings
            .encoding
            .eq_ignore_ascii_case("automatic")
            && !encoder.starts_with("libx");
        if automatic_hardware && !cancellation.is_cancelled() {
            let mut software_settings = project.video.export_settings.clone();
            software_settings.encoding = "software".into();
            let _ = fs::remove_file(&staged);
            let software = select_encoder(&software_settings, &detected).map_err(|fallback_error| {
                EncapError::Message(format!(
                    "Automatic hardware encoding failed ({hardware_error}); software fallback is unavailable ({fallback_error})."
                ))
            })?;
            let retry = export_arguments(project, &chapters, &software, &staged)?;
            if let Err(software_error) =
                encap_ffmpeg::run(tools.ffmpeg(), &retry, cancellation, "Video export")
            {
                let _ = fs::remove_file(&staged);
                return Err(EncapError::Message(format!(
                    "Automatic hardware encoding failed ({hardware_error}); software fallback also failed ({software_error})."
                )));
            }
        } else {
            let _ = fs::remove_file(&staged);
            return Err(hardware_error);
        }
    }
    replace_staged_file(&staged, destination)?;
    Ok(destination.to_path_buf())
}

pub fn selected_chapters(project: &ProjectDocument) -> Result<Vec<&Chapter>> {
    let ids = &project.video.export_settings.selected_chapter_ids;
    if ids.is_empty() && !project.video.export_settings.selection_initialized {
        return Ok(project.chapters.iter().collect());
    }
    let mut seen = HashSet::new();
    let mut output = Vec::with_capacity(ids.len());
    for id in ids {
        if !seen.insert(id) {
            return Err(EncapError::Message(
                "A Video chapter was selected more than once.".into(),
            ));
        }
        let chapter = project
            .chapters
            .iter()
            .find(|chapter| chapter.id == *id)
            .ok_or_else(|| {
                EncapError::Message("The Video selection refers to a missing chapter.".into())
            })?;
        output.push(chapter);
    }
    Ok(output)
}

pub fn export_arguments(
    project: &ProjectDocument,
    chapters: &[&Chapter],
    encoder: &str,
    output: &Path,
) -> Result<Vec<OsString>> {
    let settings = &project.video.export_settings;
    validate_settings(settings)?;
    if chapters.is_empty() {
        return Err(EncapError::Message(
            "Select at least one chapter for Video export.".into(),
        ));
    }
    let mut args = vec![os("-hide_banner"), os("-nostdin"), os("-y")];
    for chapter in chapters {
        let source_index = chapter
            .chapter_number
            .checked_sub(1)
            .map(|value| value as usize)
            .filter(|index| *index < project.audio_sources.len())
            .ok_or_else(|| {
                EncapError::Message(format!(
                    "Chapter {} has no source audio.",
                    chapter.chapter_number
                ))
            })?;
        let artwork = chapter
            .image_path
            .as_ref()
            .or(project.metadata.artwork_path.as_ref())
            .ok_or_else(|| {
                EncapError::Message("Add project artwork in Audio before using Video.".into())
            })?;
        if !artwork.is_file() {
            return Err(EncapError::Message(format!(
                "Artwork is missing: {}",
                artwork.display()
            )));
        }
        let source = &project.audio_sources[source_index].source_path;
        if !source.is_file() {
            return Err(EncapError::Message(format!(
                "Audio source is missing: {}",
                source.display()
            )));
        }
        args.extend([
            os("-loop"),
            os("1"),
            os("-framerate"),
            os(settings.fps.to_string()),
            os("-t"),
            os(seconds(chapter.duration_seconds)),
            os("-protocol_whitelist"),
            os("file,pipe"),
            os("-i"),
            os(artwork),
            os("-t"),
            os(seconds(chapter.duration_seconds)),
            os("-protocol_whitelist"),
            os("file,pipe"),
            os("-i"),
            os(source),
        ]);
    }
    args.extend([
        os("-filter_complex"),
        os(filter_graph(chapters, settings)),
        os("-map"),
        os("[outv]"),
        os("-map"),
        os("[outa]"),
        os("-c:v"),
        os(encoder),
    ]);
    if encoder == "libx264" {
        args.extend([os("-tune"), os("stillimage")]);
    }
    if settings.codec.eq_ignore_ascii_case("hevc") {
        args.extend([os("-tag:v"), os("hvc1")]);
    }
    args.extend([
        os("-pix_fmt"),
        os("yuv420p"),
        os("-r"),
        os(settings.fps.to_string()),
        os("-c:a"),
        os("aac"),
        os("-b:a"),
        os(&settings.audio_bitrate),
        os("-movflags"),
        os("+faststart"),
        os("-shortest"),
        os("-f"),
        os("mp4"),
        os(output),
    ]);
    Ok(args)
}

fn filter_graph(chapters: &[&Chapter], settings: &VideoSettings) -> String {
    let square = settings.width.min(settings.height);
    let flips = match (settings.flip_horizontal, settings.flip_vertical) {
        (true, true) => "hflip,vflip,",
        (true, false) => "hflip,",
        (false, true) => "vflip,",
        (false, false) => "",
    };
    let mut filters = String::new();
    for (index, chapter) in chapters.iter().enumerate() {
        let image = index * 2;
        let audio = image + 1;
        filters.push_str(&format!(
            "[{image}:v]{flips}split=2[bgsrc{index}][fgsrc{index}];\
             [bgsrc{index}]scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},gblur=sigma=20[bg{index}];\
             [fgsrc{index}]scale={square}:{square}:force_original_aspect_ratio=decrease,pad={square}:{square}:(ow-iw)/2:(oh-ih)/2[fg{index}];\
             [bg{index}][fg{index}]overlay=(W-w)/2:(H-h)/2,trim=duration={},setpts=PTS-STARTPTS,format=yuv420p[v{index}];\
             [{audio}:a:0]atrim=duration={},aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{index}];",
            settings.width, settings.height, settings.width, settings.height,
            seconds(chapter.duration_seconds), seconds(chapter.duration_seconds),
        ));
    }
    let inputs = (0..chapters.len())
        .map(|index| format!("[v{index}][a{index}]"))
        .collect::<String>();
    filters.push_str(&format!(
        "{inputs}concat=n={}:v=1:a=1[outv][outa]",
        chapters.len()
    ));
    filters
}

fn validate_destination(project: &ProjectDocument, destination: &Path) -> Result<()> {
    if destination
        .extension()
        .and_then(|value| value.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
        != Some("mp4")
    {
        return Err(EncapError::Message(
            "Video 2.0 exports MP4 files only.".into(),
        ));
    }
    let destination = absolute(destination)?;
    for source in &project.audio_sources {
        if absolute(&source.source_path)? == destination {
            return Err(EncapError::Message(
                "The video destination must not overwrite source audio.".into(),
            ));
        }
    }
    Ok(())
}

fn validate_settings(settings: &VideoSettings) -> Result<()> {
    let pixels = u64::from(settings.width) * u64::from(settings.height);
    if settings.width < 2
        || settings.height < 2
        || settings.width % 2 != 0
        || settings.height % 2 != 0
        || settings.width > MAX_OUTPUT_DIMENSION
        || settings.height > MAX_OUTPUT_DIMENSION
        || pixels > MAX_OUTPUT_PIXELS
    {
        return Err(EncapError::Message("Video dimensions must be even and stay within the 8192-pixel/33-megapixel safety limit.".into()));
    }
    if !(1..=120).contains(&settings.fps) {
        return Err(EncapError::Message(
            "Video frame rate must be between 1 and 120 fps.".into(),
        ));
    }
    if !matches!(
        settings.codec.to_ascii_lowercase().as_str(),
        "h264" | "hevc"
    ) {
        return Err(EncapError::Message(
            "Video codec must be H.264 or HEVC.".into(),
        ));
    }
    if !matches!(
        settings.encoding.to_ascii_lowercase().as_str(),
        "automatic" | "hardware" | "software"
    ) {
        return Err(EncapError::Message(
            "Video encoding must be Automatic, Hardware, or Software.".into(),
        ));
    }
    if !matches!(
        settings.audio_bitrate.as_str(),
        "64k" | "96k" | "128k" | "160k" | "192k" | "256k" | "320k"
    ) {
        return Err(EncapError::Message(
            "Video audio bitrate must use a supported preset from 64k through 320k.".into(),
        ));
    }
    Ok(())
}

fn validate_source_image(
    tools: &MediaTools,
    path: &Path,
    cancellation: &CancellationToken,
) -> Result<()> {
    if !path.is_file() {
        return Err(EncapError::Message(format!(
            "Artwork is missing: {}",
            path.display()
        )));
    }
    let output = encap_ffmpeg::run(
        tools.ffprobe(),
        &[
            os("-v"),
            os("error"),
            os("-select_streams"),
            os("v:0"),
            os("-show_entries"),
            os("stream=width,height"),
            os("-of"),
            os("csv=p=0:s=x"),
            os("-protocol_whitelist"),
            os("file,pipe"),
            os(path),
        ],
        cancellation,
        "Artwork inspection",
    )?;
    let dimensions = String::from_utf8_lossy(&output.stdout);
    let (width, height) = dimensions
        .trim()
        .split_once('x')
        .and_then(|(width, height)| Some((width.parse::<u64>().ok()?, height.parse::<u64>().ok()?)))
        .ok_or_else(|| {
            EncapError::Message("The selected artwork is damaged or unsupported.".into())
        })?;
    if width == 0
        || height == 0
        || width > MAX_SOURCE_IMAGE_DIMENSION
        || height > MAX_SOURCE_IMAGE_DIMENSION
        || width.saturating_mul(height) > MAX_SOURCE_IMAGE_PIXELS
    {
        return Err(EncapError::Message(
            "Artwork exceeds the 32,768-pixel/50-megapixel source safety limit.".into(),
        ));
    }
    Ok(())
}

fn select_encoder(settings: &VideoSettings, capabilities: &VideoCapabilities) -> Result<String> {
    let codec = settings.codec.to_ascii_lowercase();
    let mode = settings.encoding.to_ascii_lowercase();
    let available = |name: &str| {
        capabilities
            .encoders
            .iter()
            .any(|item| item.encoder == name)
    };
    let hardware_candidates: &[&str] = if codec == "hevc" {
        &[
            "hevc_videotoolbox",
            "hevc_nvenc",
            "hevc_qsv",
            "hevc_amf",
            "hevc_vaapi",
        ]
    } else {
        &[
            "h264_videotoolbox",
            "h264_nvenc",
            "h264_qsv",
            "h264_amf",
            "h264_vaapi",
        ]
    };
    let software = if codec == "hevc" {
        "libx265"
    } else {
        "libx264"
    };
    if mode != "software" {
        if let Some(encoder) = hardware_candidates.iter().find(|name| available(name)) {
            return Ok((*encoder).to_string());
        }
        if mode == "hardware" {
            return Err(EncapError::Message(format!(
                "Hardware {} encoding was requested, but this FFmpeg build exposes no compatible hardware encoder.",
                if codec == "hevc" { "HEVC" } else { "H.264" }
            )));
        }
    }
    if available(software) {
        Ok(software.into())
    } else {
        Err(EncapError::Message(format!(
            "This FFmpeg build does not provide the required {software} software encoder."
        )))
    }
}

fn parse_capabilities(output: &str) -> VideoCapabilities {
    let mut encoders = Vec::new();
    for (codec, names) in [
        (
            "h264",
            &[
                "libx264",
                "h264_videotoolbox",
                "h264_nvenc",
                "h264_qsv",
                "h264_amf",
                "h264_vaapi",
            ][..],
        ),
        (
            "hevc",
            &[
                "libx265",
                "hevc_videotoolbox",
                "hevc_nvenc",
                "hevc_qsv",
                "hevc_amf",
                "hevc_vaapi",
            ][..],
        ),
    ] {
        for name in names {
            if output
                .lines()
                .any(|line| line.split_whitespace().any(|field| field == *name))
            {
                encoders.push(VideoEncoderCapability {
                    codec: codec.into(),
                    encoder: (*name).into(),
                    hardware: !name.starts_with("libx"),
                });
            }
        }
    }
    VideoCapabilities { encoders }
}

fn seconds(value: f64) -> String {
    format!("{value:.6}")
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

#[cfg(test)]
mod tests {
    use super::*;
    use encap_core::{AudioSource, EpisodeMetadata};
    use std::collections::BTreeMap;

    fn project(root: &Path) -> ProjectDocument {
        let audio = root.join("one.wav");
        let art = root.join("cover.png");
        fs::write(&audio, b"audio").unwrap();
        fs::write(&art, b"image").unwrap();
        ProjectDocument {
            metadata: EpisodeMetadata {
                artwork_path: Some(art),
                ..Default::default()
            },
            audio_sources: vec![AudioSource {
                source_path: audio,
                display_name: "One".into(),
                duration_seconds: 2.0,
                stored_path: None,
                extensions: BTreeMap::new(),
            }],
            chapters: vec![Chapter {
                id: "one".into(),
                start_time_seconds: 0.0,
                duration_seconds: 2.0,
                chapter_number: 1,
                title: "One".into(),
                link_url: String::new(),
                image_path: None,
                image_stored_path: None,
                extensions: BTreeMap::new(),
            }],
            ..Default::default()
        }
    }

    #[test]
    fn selection_order_is_video_only() {
        let root = tempfile::tempdir().unwrap();
        let mut project = project(root.path());
        project.video.export_settings.selected_chapter_ids = vec!["one".into()];
        let selected = selected_chapters(&project).unwrap();
        assert_eq!(selected[0].id, "one");
        assert_eq!(project.chapters[0].chapter_number, 1);
    }

    #[test]
    fn graph_uses_direct_audio_and_hard_concat() {
        let root = tempfile::tempdir().unwrap();
        let project = project(root.path());
        let chapters = selected_chapters(&project).unwrap();
        let args = export_arguments(&project, &chapters, "libx264", Path::new("out.mp4")).unwrap();
        let joined = args
            .iter()
            .map(|value| value.to_string_lossy())
            .collect::<Vec<_>>()
            .join(" ");
        assert!(joined.contains("gblur=sigma=20"));
        assert!(joined.contains("concat=n=1:v=1:a=1"));
        assert!(!joined.contains("mp3"));
        assert!(!joined.contains("-map_chapters"));
    }

    #[test]
    fn hardware_choice_is_explicit_and_capability_based() {
        let capabilities = parse_capabilities(
            " V..... h264_videotoolbox VideoToolbox H.264 Encoder\n V..... libx264 H.264",
        );
        let mut settings = VideoSettings {
            encoding: "automatic".into(),
            ..VideoSettings::default()
        };
        assert_eq!(
            select_encoder(&settings, &capabilities).unwrap(),
            "h264_videotoolbox"
        );
        settings.codec = "hevc".into();
        settings.encoding = "hardware".into();
        assert!(select_encoder(&settings, &capabilities)
            .unwrap_err()
            .to_string()
            .contains("Hardware HEVC"));
    }
}
