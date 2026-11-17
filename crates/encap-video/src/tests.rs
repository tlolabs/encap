use super::*;
use avid_core::{Codec, Composition, Encoding};
use encap_core::{AudioSource, EpisodeMetadata};
use std::fs;

// Container headers only; decoding in these tests is explicitly injected.
fn png_header(animated: bool) -> Vec<u8> {
    fn chunk(output: &mut Vec<u8>, name: &[u8; 4], data: &[u8]) {
        output.extend_from_slice(&(data.len() as u32).to_be_bytes());
        output.extend_from_slice(name);
        output.extend_from_slice(data);
        output.extend_from_slice(&[0; 4]);
    }
    let mut output = b"\x89PNG\r\n\x1a\n".to_vec();
    chunk(&mut output, b"IHDR", &[0; 13]);
    if animated {
        chunk(&mut output, b"acTL", &[0; 8]);
    }
    chunk(&mut output, b"IDAT", &[0]);
    chunk(&mut output, b"IEND", &[]);
    output
}

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

#[test]
fn automatic_mode_preserves_animation_unknown_formats_and_cached_frame_budget() {
    let root = tempfile::tempdir().unwrap();
    let mut project = project(root.path());
    let token = CancellationToken::default();
    let output = root.path().join("out.mp4");
    let main = project.metadata.artwork_path.clone().unwrap();
    // Filename suffix does not decide staticness.
    assert_eq!(
        automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
        RenderMode::PerFrame
    );
    for image in [
        png_header(false),
        vec![0xff, 0xd8, 0xff, 0xda, 0, 2, 1, 0xff, 0xd9],
    ] {
        fs::write(&main, image).unwrap();
        assert_eq!(
            automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
            RenderMode::Simple
        );
    }
    for image in [
        png_header(true),
        b"GIF89a".to_vec(),
        b"RIFFxxxxWEBP".to_vec(),
        [[0xff, 0xd8, 0xff, 0xda, 0xff, 0xd9]; 2].concat(),
    ] {
        fs::write(&main, image).unwrap();
        assert_eq!(
            automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
            RenderMode::PerFrame
        );
    }
    fs::write(&main, png_header(false)).unwrap();
    let animated = root.path().join("animated.png");
    fs::write(&animated, png_header(true)).unwrap();
    project.chapters[1].image_path = Some(animated);
    assert_eq!(
        automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
        RenderMode::PerFrame
    );
    project.video.export_settings.selected_chapter_ids = vec!["0".into()];
    assert_eq!(
        automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
        RenderMode::Simple
    );
    project.video.export_settings.selected_chapter_ids.clear();
    project.chapters[1].image_path = None;
    project.video.export_settings.width = 7680;
    project.video.export_settings.height = 4320;
    let mut chapter = project.chapters[0].clone();
    chapter.id = "third".into();
    chapter.start_time_seconds = 5.0;
    chapter.chapter_number = 3;
    project.chapters.push(chapter);
    project.audio_sources.push(project.audio_sources[0].clone());
    assert_eq!(
        automatic_mode(&render_request(&project, &output).unwrap(), &token).unwrap(),
        RenderMode::PerFrame
    );
}

#[test]
fn completion_confirmation_is_required_and_forwarded() {
    #[derive(Default)]
    struct Events(std::sync::Mutex<Vec<avid_core::Stage>>);
    impl EventSink for Events {
        fn stage(&self, stage: avid_core::Stage) {
            self.0.lock().unwrap().push(stage);
        }
    }
    let events = Events::default();
    let completion = CompletionEvents::new(&events);
    assert!(completion.require_complete().is_err());
    completion.stage(avid_core::Stage::Publishing);
    assert!(completion.require_complete().is_err());
    completion.stage(avid_core::Stage::Complete);
    completion.require_complete().unwrap();
    assert_eq!(
        *events.0.lock().unwrap(),
        [avid_core::Stage::Publishing, avid_core::Stage::Complete]
    );
}

// Real linked media fixtures replace the obsolete fake-process graph tests.
// No external media executable creates or decodes these inputs.
mod linked {
    use super::*;
    use std::io::Write;

    fn image(path: &Path, width: u32, height: u32) {
        let file = fs::File::create(path).unwrap();
        let mut encoder = png::Encoder::new(file, width, height);
        encoder.set_color(png::ColorType::Rgb);
        encoder.set_depth(png::BitDepth::Eight);
        encoder
            .write_header()
            .unwrap()
            .write_image_data(&vec![128; (width * height * 3) as usize])
            .unwrap();
    }
    fn wave(path: &Path, rate: u32) {
        let samples = rate / 2;
        let bytes = samples * 2;
        let mut file = fs::File::create(path).unwrap();
        file.write_all(b"RIFF").unwrap();
        file.write_all(&(36 + bytes).to_le_bytes()).unwrap();
        file.write_all(b"WAVEfmt ").unwrap();
        for value in [16u32, 0x0001_0001, rate, rate * 2, 0x0010_0002] {
            file.write_all(&value.to_le_bytes()).unwrap();
        }
        file.write_all(b"data").unwrap();
        file.write_all(&bytes.to_le_bytes()).unwrap();
        for index in 0..samples {
            let sample = ((index as f64 / rate as f64 * 440.0 * std::f64::consts::TAU).sin()
                * 5000.0) as i16;
            file.write_all(&sample.to_le_bytes()).unwrap();
        }
    }
    fn fixture(root: &Path) -> ProjectDocument {
        let mut project = project(root);
        image(project.metadata.artwork_path.as_deref().unwrap(), 32, 48);
        for (index, source) in project.audio_sources.iter_mut().enumerate() {
            wave(&source.source_path, if index == 0 { 44100 } else { 48000 });
            source.duration_seconds = 0.5;
            project.chapters[index].start_time_seconds = index as f64 * 0.25;
            project.chapters[index].duration_seconds = 0.25;
        }
        // Fixtures deliberately select software; production preserves explicit
        // project settings and separately uses Core's profile-aware defaults.
        project.video.export_settings.encoding = "software".into();
        project.video.export_settings.fps = 24;
        project
    }

    #[test]
    fn session_inspection_invalidates_changed_source_and_has_profile_defaults() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let path = project.metadata.artwork_path.as_deref().unwrap();
        let token = CancellationToken::default();
        let renderer = VideoRenderer::discover(&token).unwrap();
        assert_eq!(renderer.inspect_image(path, &token).unwrap(), (32, 48));
        assert_eq!(
            renderer.clone().inspect_image(path, &token).unwrap(),
            (32, 48)
        );
        image(path, 64, 32);
        assert_eq!(renderer.inspect_image(path, &token).unwrap(), (64, 32));
        let capabilities = renderer.capabilities(&token).unwrap();
        assert!(!capabilities.linked_version.is_empty());
        assert_eq!(renderer.default_settings().width, 1920);
        assert!(
            (renderer
                .probe_audio_duration(&project.audio_sources[0].source_path, &token)
                .unwrap()
                .unwrap()
                - 0.5)
                .abs()
                < 0.001
        );
    }

    #[test]
    fn linked_preview_both_modes_publish_and_preserve_project() {
        let root = tempfile::tempdir().unwrap();
        let project = fixture(root.path());
        let before = project.clone();
        let token = CancellationToken::default();
        let renderer = VideoRenderer::discover(&token).unwrap();
        let output = root.path().join("new folder/預覽.png");
        renderer
            .preview(&project, &output, Some("1"), &token)
            .unwrap();
        assert!(fs::read(&output).unwrap().starts_with(b"\x89PNG"));
        assert_eq!(renderer.inspect_image(&output, &token).unwrap(), (160, 90));
        for mode in [RenderMode::Simple, RenderMode::PerFrame] {
            let output = root.path().join(format!("{mode:?}.mp4"));
            renderer
                .export_with_mode(&project, &output, mode, &token)
                .unwrap();
            assert!(fs::metadata(&output).unwrap().len() > 100);
            let duration = renderer
                .probe_audio_duration(&output, &token)
                .unwrap()
                .unwrap();
            assert!((duration - 0.5).abs() < 0.05, "{duration}");
        }
        assert_eq!(project, before);
    }

    #[test]
    fn linked_failure_precancel_and_aliases_preserve_destinations() {
        let root = tempfile::tempdir().unwrap();
        let mut project = fixture(root.path());
        let token = CancellationToken::default();
        let renderer = VideoRenderer::discover(&token).unwrap();
        let output = root.path().join("old.mp4");
        fs::write(&output, b"existing destination").unwrap();
        let cancelled = CancellationToken::default();
        cancelled.cancel();
        assert!(renderer.export(&project, &output, &cancelled).is_err());
        assert_eq!(fs::read(&output).unwrap(), b"existing destination");
        let main = project.metadata.artwork_path.as_deref().unwrap();
        fs::write(main, b"corrupt image").unwrap();
        assert!(renderer.export(&project, &output, &token).is_err());
        assert_eq!(fs::read(&output).unwrap(), b"existing destination");
        image(main, 32, 48);
        for protected in protected_paths(&project) {
            assert!(renderer
                .preview(&project, &protected, None, &token)
                .is_err());
            let alias = root.path().join("alias.mp4");
            fs::hard_link(&protected, &alias).unwrap();
            assert!(renderer.export(&project, &alias, &token).is_err());
            fs::remove_file(&alias).unwrap();
        }
        project.video.export_settings.selected_chapter_ids.clear();
        project.video.export_settings.selection_initialized = true;
        assert!(renderer.export(&project, &output, &token).is_err());
        assert_eq!(fs::read(&output).unwrap(), b"existing destination");
    }

    #[test]
    fn progress_cancellation_drains_worker_and_keeps_other_token_live() {
        struct Cancel<'a>(&'a CancellationToken);
        impl EventSink for Cancel<'_> {
            fn progress(&self, _: avid_core::Progress) {
                self.0.cancel();
            }
        }
        let root = tempfile::tempdir().unwrap();
        let mut project = fixture(root.path());
        // A long requested timeline ensures a progress callback precedes EOF.
        project.chapters[0].duration_seconds = 30.0;
        project.chapters[1].start_time_seconds = 30.0;
        let output = root.path().join("cancel.mp4");
        fs::write(&output, b"old").unwrap();
        let token = CancellationToken::default();
        let renderer = VideoRenderer::discover(&token).unwrap();
        assert!(renderer
            .export_with_events(
                &project,
                &output,
                Some(RenderMode::PerFrame),
                &token,
                &Cancel(&token)
            )
            .is_err());
        assert!(token.is_cancelled());
        assert_eq!(fs::read(&output).unwrap(), b"old");
        let independent = CancellationToken::default();
        let preview = root.path().join("independent.png");
        renderer
            .preview(&fixture(root.path()), &preview, None, &independent)
            .unwrap();
        assert!(!independent.is_cancelled());
    }
}
