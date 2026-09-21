use super::*;
use avid_core::{Codec, Composition, Encoding};
use encap_core::{AudioSource, EpisodeMetadata};
use std::fs;

fn project(root: &Path) -> ProjectDocument {
    let art = root.join("cover.png");
    fs::write(&art, b"image").unwrap();
    let mut project = ProjectDocument {
        metadata: EpisodeMetadata {
            artwork_path: Some(art),
            ..Default::default()
        },
        project_path: Some(root.join("project.encap")),
        ..Default::default()
    };
    fs::write(project.project_path.as_ref().unwrap(), b"project").unwrap();
    for (index, duration) in [2.0, 3.0].into_iter().enumerate() {
        let audio = root.join(format!("source {index}.wav"));
        fs::write(&audio, b"audio").unwrap();
        project.audio_sources.push(AudioSource {
            source_path: audio,
            display_name: index.to_string(),
            duration_seconds: duration,
            stored_path: None,
            extensions: Default::default(),
        });
        project.chapters.push(Chapter {
            id: index.to_string(),
            start_time_seconds: if index == 0 { 0.0 } else { 2.0 },
            duration_seconds: duration,
            chapter_number: index as u32 + 1,
            title: index.to_string(),
            link_url: String::new(),
            image_path: None,
            image_stored_path: None,
            extensions: Default::default(),
        });
    }
    project.video.export_settings.width = 160;
    project.video.export_settings.height = 90;
    project.video.export_settings.flip_horizontal = true;
    project
}

#[test]
fn selection_order_is_video_only_and_maps_canonical_sources() {
    let root = tempfile::tempdir().unwrap();
    let mut project = project(root.path());
    let override_art = root.path().join("chapter.png");
    project.chapters[1].image_path = Some(override_art.clone());
    project.video.export_settings.selected_chapter_ids = vec!["1".into(), "0".into()];
    let before = project.clone();
    let request = render_request(&project, Path::new("out.mp4")).unwrap();
    let Input::Timeline(timeline) = request.input else {
        panic!()
    };
    assert_eq!(
        timeline.clips()[0].audio,
        project.audio_sources[1].source_path
    );
    assert_eq!(timeline.clips()[0].image, override_art);
    assert_eq!(
        timeline.clips()[1].image,
        *project.metadata.artwork_path.as_ref().unwrap()
    );
    assert_eq!(timeline.position(3.0).unwrap().index, 1);
    assert_eq!(timeline.duration_seconds(), 5.0);
    assert_eq!(project, before);
    for path in project
        .audio_sources
        .iter()
        .map(|source| &source.source_path)
        .chain(project.metadata.artwork_path.iter())
        .chain(project.project_path.iter())
        .chain([&override_art])
    {
        assert!(request.protected_paths.contains(path));
    }
    project.video.export_settings.selected_chapter_ids = vec!["1".into()];
    project.chapters[0].chapter_number = 0; // Unselected records are never mapped.
    assert!(render_request(&project, Path::new("out.mp4")).is_ok());
    for bad in [0, 3, u32::MAX] {
        project.chapters[1].chapter_number = bad;
        assert!(render_request(&project, Path::new("out.mp4")).is_err());
    }
}

#[test]
fn shared_selection_and_execution_settings_preserve_host_policy() {
    let root = tempfile::tempdir().unwrap();
    let mut project = project(root.path());
    assert_eq!(selected_chapters(&project).unwrap().len(), 2);
    project.video.export_settings.selection_initialized = true;
    assert!(selected_chapters(&project).unwrap().is_empty());
    for ids in [vec!["0", "0"], vec!["missing"]] {
        project.video.export_settings.selected_chapter_ids =
            ids.into_iter().map(String::from).collect();
        assert!(selected_chapters(&project).is_err());
    }
    project.video.export_settings.selected_chapter_ids = vec!["0".into()];
    for (codec, expected) in [("h264", Codec::H264), ("hevc", Codec::Hevc)] {
        for (encoding, mode) in [
            ("automatic", Encoding::Automatic),
            ("hardware", Encoding::Hardware),
            ("software", Encoding::Software),
        ] {
            project.video.export_settings.codec = codec.into();
            project.video.export_settings.encoding = encoding.into();
            let request = render_request(&project, Path::new("out.mp4")).unwrap();
            assert_eq!(request.settings.codec, expected);
            assert_eq!(request.settings.encoding, mode);
            assert_eq!(request.settings.composition, Composition::SquarePadded);
            assert!(request.settings.flip_horizontal);
        }
    }
    for patch in [
        serde_json::json!({"width": 1}),
        serde_json::json!({"width": 10000}),
        serde_json::json!({"height": 0}),
        serde_json::json!({"fps": 0}),
        serde_json::json!({"fps": 121}),
        serde_json::json!({"audio_bitrate": "224k"}),
        serde_json::json!({"codec": "future"}),
        serde_json::json!({"encoding": "future"}),
    ] {
        let mut invalid = project.clone();
        let mut settings = serde_json::to_value(&invalid.video.export_settings).unwrap();
        settings
            .as_object_mut()
            .unwrap()
            .extend(patch.as_object().unwrap().clone());
        invalid.video.export_settings = serde_json::from_value(settings).unwrap();
        assert!(render_request(&invalid, Path::new("out.mp4")).is_err());
    }
    for duration in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        let mut invalid = project.clone();
        invalid.chapters[0].duration_seconds = duration;
        assert!(render_request(&invalid, Path::new("out.mp4")).is_err());
    }
    project.video.schema_version = 2;
    assert!(render_request(&project, Path::new("out.mp4")).is_err());
}

#[cfg(unix)]
mod processes {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    use std::time::{Duration, Instant};

    fn shell(path: &Path, body: &str) {
        fs::write(path, format!("#!/bin/sh\n{body}\n")).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
    }

    fn fake(root: &Path, mode: &str) -> Renderer {
        let ffmpeg = root.join("ffmpeg");
        let ffprobe = root.join("ffprobe");
        shell(
            &ffprobe,
            &format!(
                r#"
if [ "$1" = -version ]; then echo 'ffprobe version 9.0.1'; exit; fi
printf '%s\n' "$@" >> '{root}/probes'
if [ '{mode}' = probe_sleep ]; then exec /bin/sleep 20; fi
if [ '{mode}' = corrupt ]; then echo 'private path and stderr' >&2; exit 1; fi
echo 100x100
"#,
                root = root.display()
            ),
        );
        shell(
            &ffmpeg,
            &format!(
                r#"
if [ "$1" = -version ]; then echo 'ffmpeg version 9.0.1'; exit; fi
if [ "$2" = -encoders ]; then
 echo ' V..... h264_videotoolbox hardware'
 echo ' V..... libx264 software'
 echo ' V..... libx265 software'
 exit
fi
printf '%s\n' "$@" >> '{root}/arguments'
for last do :; done
printf partial > "$last"
if [ '{mode}' = encode_sleep ]; then exec /bin/sleep 20; fi
if [ '{mode}' = fail ]; then echo 'private stderr' >&2; exit 1; fi
case " $* " in *h264_videotoolbox*) exit 1;; esac
printf complete > "$last"
"#,
                root = root.display()
            ),
        );
        let tools = avid_core::MediaTools::discover(
            ToolDiscovery {
                ffmpeg: Some(ffmpeg),
                ffprobe: Some(ffprobe),
                ..Default::default()
            },
            &CancellationToken::default(),
        )
        .unwrap();
        Renderer::new(tools)
    }

    fn assert_clean(root: &Path, project: &ProjectDocument, output: &Path) {
        assert_eq!(fs::read(output).unwrap(), b"old output");
        for source in &project.audio_sources {
            assert_eq!(fs::read(&source.source_path).unwrap(), b"audio");
        }
        assert_eq!(
            fs::read(project.metadata.artwork_path.as_ref().unwrap()).unwrap(),
            b"image"
        );
        assert_eq!(
            fs::read(project.project_path.as_ref().unwrap()).unwrap(),
            b"project"
        );
        assert!(!fs::read_dir(root).unwrap().any(|entry| entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".avid-")));
    }

    #[test]
    fn graph_uses_shared_reference_and_automatic_fallback() {
        let root = tempfile::tempdir().unwrap();
        let mut project = project(root.path());
        let renderer = fake(root.path(), "success");
        let output = root.path().join("out.mp4");
        project.video.export_settings.encoding = "automatic".into();
        let before = project.clone();
        let request = render_request(&project, &output).unwrap();
        export_with_renderer(&project, &request, &renderer, &CancellationToken::default()).unwrap();
        let arguments = fs::read_to_string(root.path().join("arguments")).unwrap();
        let graph = include_str!("../tests/fixtures/encap-graph.txt").trim();
        assert!(arguments.lines().any(|line| line == graph));
        assert!(arguments.contains("h264_videotoolbox\n"));
        assert!(arguments.contains("libx264\n"));
        assert!(!arguments.contains("\n-ss\n"));
        assert!(!arguments.contains("\n-map_chapters\n"));
        assert_eq!(fs::read(&output).unwrap(), b"complete");
        assert_eq!(project, before);
        project.video.export_settings.codec = "hevc".into();
        project.video.export_settings.encoding = "software".into();
        export_with_renderer(
            &project,
            &render_request(&project, &output).unwrap(),
            &renderer,
            &CancellationToken::default(),
        )
        .unwrap();
        assert!(fs::read_to_string(root.path().join("arguments"))
            .unwrap()
            .contains("-tag:v\nhvc1\n"));
    }

    #[test]
    fn failure_cancellation_timeout_and_artwork_preflight_preserve_files() {
        for mode in ["fail", "corrupt", "probe_sleep", "encode_sleep", "success"] {
            let root = tempfile::tempdir().unwrap();
            let mut project = project(root.path());
            let output = root.path().join("out.mp4");
            fs::write(&output, b"old output").unwrap();
            let renderer = fake(root.path(), mode).with_options(avid_core::OperationOptions {
                probe_timeout: Some(Duration::from_millis(80)),
                render_timeout: Some(Duration::from_millis(80)),
                ..Default::default()
            });
            project.video.export_settings.encoding = "automatic".into();
            if mode == "success" {
                project.video.export_settings.encoding = "hardware".into();
            }
            let request = render_request(&project, &output).unwrap();
            let error =
                export_with_renderer(&project, &request, &renderer, &CancellationToken::default())
                    .unwrap_err()
                    .to_string();
            assert!(!error.contains("private"));
            if mode.ends_with("sleep") {
                assert!(error.contains("timed out"));
            }
            if mode == "fail" {
                assert!(error.contains("software fallback also failed"));
            }
            assert_clean(root.path(), &project, &output);
        }
        for mode in ["probe_sleep", "encode_sleep"] {
            let root = tempfile::tempdir().unwrap();
            let project = project(root.path());
            let output = root.path().join("out.mp4");
            fs::write(&output, b"old output").unwrap();
            let renderer = fake(root.path(), mode);
            let token = CancellationToken::default();
            let signal = token.clone();
            let cancel = std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(100));
                signal.cancel();
            });
            let start = Instant::now();
            let error = export_with_renderer(
                &project,
                &render_request(&project, &output).unwrap(),
                &renderer,
                &token,
            )
            .unwrap_err();
            cancel.join().unwrap();
            assert!(error.to_string().contains("cancelled"));
            assert!(start.elapsed() < Duration::from_secs(2));
            assert_clean(root.path(), &project, &output);
        }
    }

    #[test]
    fn main_artwork_empty_selection_and_all_protected_aliases() {
        let root = tempfile::tempdir().unwrap();
        let mut project = project(root.path());
        let renderer = fake(root.path(), "success");
        let output = root.path().join("out.mp4");
        fs::write(&output, b"old output").unwrap();
        let chapter_art = root.path().join("override.png");
        fs::write(&chapter_art, b"image").unwrap();
        project.chapters[0].image_path = Some(chapter_art.clone());
        project.video.export_settings.selected_chapter_ids = vec!["0".into()];
        // Even with a selected override, the main artwork must be inspected first.
        let request = render_request(&project, &output).unwrap();
        export_with_renderer(&project, &request, &renderer, &CancellationToken::default()).unwrap();
        let probes = fs::read_to_string(root.path().join("probes")).unwrap();
        assert!(probes.find("cover.png").unwrap() < probes.find("override.png").unwrap());
        fs::write(&output, b"old output").unwrap();
        for source in request.protected_paths {
            let alias = root.path().join("alias.mp4");
            fs::hard_link(&source, &alias).unwrap();
            assert!(export_with_renderer(
                &project,
                &render_request(&project, &alias).unwrap(),
                &renderer,
                &CancellationToken::default()
            )
            .is_err());
            fs::remove_file(&alias).unwrap();
            std::os::unix::fs::symlink(&source, &alias).unwrap();
            assert!(export_with_renderer(
                &project,
                &render_request(&project, &alias).unwrap(),
                &renderer,
                &CancellationToken::default()
            )
            .is_err());
            fs::remove_file(&alias).unwrap();
        }
        project.video.export_settings.selected_chapter_ids.clear();
        project.video.export_settings.selection_initialized = true;
        assert!(export_with_renderer(
            &project,
            &render_request(&project, &output).unwrap(),
            &renderer,
            &CancellationToken::default()
        )
        .is_err());
        assert_clean(root.path(), &project, &output);
        project.metadata.artwork_path = None;
        assert!(render_request(&project, &output)
            .unwrap_err()
            .to_string()
            .contains("Add project artwork"));
    }
}
