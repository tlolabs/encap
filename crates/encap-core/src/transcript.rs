use crate::{conflicts_with_path, EncapError, ProjectDocument, Result, TranscriptSegment};
use std::fmt::Write;
use std::path::Path;

pub fn validate_transcript_export(project: &ProjectDocument, destination: &Path) -> Result<()> {
    project.validate()?;
    if project.transcript_segments.is_empty() {
        return Err(EncapError::Message(
            "There is no transcript available to export.".into(),
        ));
    }
    for source in &project.audio_sources {
        if conflicts_with_path(destination, &source.source_path) {
            return Err(EncapError::Message(
                "The export destination must not overwrite source media.".into(),
            ));
        }
    }
    if let Some(artwork) = &project.metadata.artwork_path {
        if conflicts_with_path(destination, artwork) {
            return Err(EncapError::Message(
                "The export destination must not overwrite project artwork.".into(),
            ));
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

pub fn render_transcript_text(segments: &[TranscriptSegment]) -> String {
    let mut output = String::with_capacity(segments.len().checked_mul(48).unwrap_or(0));
    for segment in segments {
        let text = segment.text.trim();
        if text.is_empty() {
            continue;
        }
        let speaker = segment.speaker.trim();
        if !speaker.is_empty() {
            output.push_str(speaker);
            output.push_str(": ");
        }
        output.push_str(text);
        output.push('\n');
    }
    output
}

pub fn render_srt(segments: &[TranscriptSegment]) -> String {
    let mut output = String::with_capacity(segments.len().checked_mul(80).unwrap_or(0));
    for (index, segment) in segments.iter().enumerate() {
        let _ = writeln!(output, "{}", index + 1);
        write_time(&mut output, segment.start_time_seconds);
        output.push_str(" --> ");
        write_time(&mut output, segment.end_time_seconds);
        output.push('\n');
        let speaker = segment.speaker.trim();
        if !speaker.is_empty() {
            output.push_str(speaker);
            output.push_str(": ");
        }
        output.push_str(segment.text.trim());
        output.push_str("\n\n");
    }
    output
}

fn write_time(output: &mut String, seconds: f64) {
    let valid = if seconds.is_finite() {
        seconds.max(0.0)
    } else {
        0.0
    };
    let millis = (valid * 1000.0).round() as u64;
    let _ = write!(
        output,
        "{:02}:{:02}:{:02},{:03}",
        millis / 3_600_000,
        (millis / 60_000) % 60,
        (millis / 1000) % 60,
        millis % 1000
    );
}

#[cfg(test)]
mod equivalence_tests {
    use super::*;
    use crate::{AudioSource, Chapter};
    use std::collections::BTreeMap;
    use std::fs;
    fn segment(start: f64, end: f64, speaker: &str, text: &str) -> TranscriptSegment {
        TranscriptSegment {
            id: String::new(),
            start_time_seconds: start,
            end_time_seconds: end,
            speaker: speaker.into(),
            text: text.into(),
            words: vec![],
            extensions: BTreeMap::new(),
        }
    }
    fn reference_time(seconds: f64) -> String {
        let valid = if seconds.is_finite() {
            seconds.max(0.0)
        } else {
            0.0
        };
        let millis = (valid * 1000.0).round() as u64;
        format!(
            "{:02}:{:02}:{:02},{:03}",
            millis / 3_600_000,
            (millis / 60_000) % 60,
            (millis / 1000) % 60,
            millis % 1000
        )
    }
    #[test]
    fn text_and_srt_preserve_established_unicode_trimming_numbering_and_rounding() {
        assert_eq!(render_srt(&[]), "");
        assert_eq!(render_transcript_text(&[]), "");
        let times = [
            -1.0,
            0.0,
            0.0005,
            59.9994,
            59.9996,
            3599.9996,
            360000.0,
            f64::NAN,
            f64::INFINITY,
            f64::MAX,
        ];
        let mut segments = vec![segment(0.0, 0.0, " ", " ")];
        for i in 0..10000 {
            segments.push(segment(
                times[i % times.len()],
                times[(i + 1) % times.len()],
                " 音声 ",
                "  é😀\nline  ",
            ));
        }
        let mut reference_srt = String::new();
        let mut reference_text = String::new();
        for (i, s) in segments.iter().enumerate() {
            let speaker = if s.speaker.trim().is_empty() {
                String::new()
            } else {
                format!("{}: ", s.speaker.trim())
            };
            reference_srt.push_str(&format!(
                "{}\n{} --> {}\n{}{}\n\n",
                i + 1,
                reference_time(s.start_time_seconds),
                reference_time(s.end_time_seconds),
                speaker,
                s.text.trim()
            ));
            if !s.text.trim().is_empty() {
                reference_text.push_str(&format!("{}{}\n", speaker, s.text.trim()));
            }
        }
        assert_eq!(render_srt(&segments), reference_srt);
        assert_eq!(render_transcript_text(&segments), reference_text);
        assert_eq!(reference_time(59.9996), "00:01:00,000");
        assert_eq!(reference_time(3599.9996), "01:00:00,000");
    }

    #[test]
    fn transcript_export_rejects_overwriting_protected_project_files() {
        let dir = tempfile::tempdir().unwrap();
        let source = dir.path().join("source.wav");
        let cover = dir.path().join("cover.png");
        let chapter_art = dir.path().join("chapter.png");
        let project_file = dir.path().join("episode.encap");
        let safe_out = dir.path().join("transcript.txt");
        for path in [&source, &cover, &chapter_art, &project_file] {
            fs::write(path, b"protected").unwrap();
        }
        let mut project = ProjectDocument {
            project_path: Some(project_file.clone()),
            ..Default::default()
        };
        project.metadata.artwork_path = Some(cover.clone());
        project.audio_sources.push(AudioSource {
            source_path: source.clone(),
            display_name: "source".into(),
            duration_seconds: 10.0,
            stored_path: None,
            extensions: BTreeMap::new(),
        });
        project.chapters.push(Chapter {
            id: "c1".into(),
            start_time_seconds: 0.0,
            duration_seconds: 10.0,
            chapter_number: 1,
            title: "Chapter 1".into(),
            link_url: String::new(),
            image_path: Some(chapter_art.clone()),
            image_stored_path: None,
            extensions: BTreeMap::new(),
        });
        assert!(validate_transcript_export(&project, &safe_out).is_err());
        project
            .transcript_segments
            .push(segment(0.0, 5.0, "Host", "Hello"));
        assert!(validate_transcript_export(&project, &safe_out).is_ok());
        for protected in [&source, &cover, &chapter_art, &project_file] {
            assert!(validate_transcript_export(&project, protected).is_err());
        }
        #[cfg(unix)]
        {
            let alias = dir.path().join("alias.txt");
            std::os::unix::fs::symlink(&source, &alias).unwrap();
            assert!(validate_transcript_export(&project, &alias).is_err());
        }
    }
}
