use crate::{inspect_files, ProjectDocument, Result};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

#[derive(Debug, Default, Deserialize)]
#[serde(default)]
pub struct AudioEdits {
    pub add_files: Vec<PathBuf>,
    pub remove_files: Vec<PathBuf>,
}

/// Apply triage atomically to project records. Original media is never deleted.
pub fn edit_audio(project: &ProjectDocument, edits: AudioEdits) -> Result<ProjectDocument> {
    let mut result = project.clone();
    let removed: BTreeSet<_> = edits.remove_files.into_iter().collect();
    if result
        .audio_sources
        .iter()
        .any(|source| removed.contains(&source.source_path))
    {
        let mut numbers = BTreeMap::new();
        let mut cuts = Vec::new();
        let mut starts = Vec::new();
        let mut position = 0.0;
        let mut kept = Vec::new();
        for (index, source) in project.audio_sources.iter().enumerate() {
            starts.push(position);
            let end = position + source.duration_seconds;
            if removed.contains(&source.source_path) {
                cuts.push(position..end);
            } else {
                kept.push(source.clone());
                numbers.insert(index as u32 + 1, kept.len() as u32);
            }
            position = end;
        }
        let adjusted = |time: f64| {
            time - cuts
                .iter()
                .map(|cut| (time.min(cut.end) - cut.start).max(0.0))
                .sum::<f64>()
        };
        result.chapters.retain_mut(|chapter| {
            let old =
                if chapter.chapter_number > 0 && chapter.chapter_number as usize <= starts.len() {
                    chapter.chapter_number
                } else {
                    starts
                        .iter()
                        .rposition(|start| *start <= chapter.start_time_seconds)
                        .unwrap_or(0) as u32
                        + 1
                };
            let Some(&number) = numbers.get(&old) else {
                return false;
            };
            let end = adjusted(chapter.start_time_seconds + chapter.duration_seconds);
            chapter.start_time_seconds = adjusted(chapter.start_time_seconds);
            chapter.duration_seconds = (end - chapter.start_time_seconds).max(0.0);
            chapter.chapter_number = number;
            if chapter.title == format!("Chapter {old}") {
                chapter.title = format!("Chapter {number}");
            }
            true
        });
        result.transcript_segments.retain_mut(|segment| {
            if cuts.iter().any(|cut| {
                segment.start_time_seconds < cut.end && segment.end_time_seconds > cut.start
            }) {
                return false;
            }
            segment.start_time_seconds = adjusted(segment.start_time_seconds);
            segment.end_time_seconds = adjusted(segment.end_time_seconds);
            for word in &mut segment.words {
                word.start_time_seconds = adjusted(word.start_time_seconds);
                word.end_time_seconds = adjusted(word.end_time_seconds);
            }
            true
        });
        result.audio_sources = kept;
        if result.audio_sources.is_empty() {
            result.chapters.clear();
            result.transcript_segments.clear();
        }
        let known: BTreeSet<_> = result.chapters.iter().map(|chapter| &chapter.id).collect();
        result
            .video
            .export_settings
            .selected_chapter_ids
            .retain(|id| known.contains(id));
    }
    let mut known: BTreeSet<_> = result
        .audio_sources
        .iter()
        .map(|source| source.source_path.clone())
        .collect();
    let added: Vec<_> = edits
        .add_files
        .into_iter()
        .filter(|path| known.insert(path.clone()))
        .collect();
    // Inspect the entire selection before committing any additions.
    let imported = inspect_files(&added)?;
    let select_new = !result.video.export_settings.selection_initialized
        || result
            .chapters
            .iter()
            .map(|chapter| &chapter.id)
            .collect::<BTreeSet<_>>()
            == result
                .video
                .export_settings
                .selected_chapter_ids
                .iter()
                .collect::<BTreeSet<_>>();
    let mut start: f64 = result
        .audio_sources
        .iter()
        .map(|source| source.duration_seconds)
        .sum();
    for (source, mut chapter) in imported.audio_sources.into_iter().zip(imported.chapters) {
        result.audio_sources.push(source);
        chapter.chapter_number = result.audio_sources.len() as u32;
        chapter.start_time_seconds = start;
        start += chapter.duration_seconds;
        if select_new && result.video.export_settings.selection_initialized {
            result
                .video
                .export_settings
                .selected_chapter_ids
                .push(chapter.id.clone());
        }
        result.chapters.push(chapter);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn fixture() -> ProjectDocument {
        serde_json::from_value(json!({
            "audio_sources": [
                {"source_path":"a.wav", "display_name":"A", "duration_seconds":10},
                {"source_path":"b.wav", "display_name":"B", "duration_seconds":20},
                {"source_path":"c.wav", "display_name":"C", "duration_seconds":30}
            ],
            "chapters": [
                {"id":"a", "chapter_number":1, "title":"Chapter 1", "start_time_seconds":0, "duration_seconds":10},
                {"id":"b", "chapter_number":2, "title":"Chapter 2", "start_time_seconds":10, "duration_seconds":20},
                {"id":"c", "chapter_number":3, "title":"Chapter 3", "start_time_seconds":30, "duration_seconds":20},
                {"id":"custom", "chapter_number":3, "title":"Closing", "start_time_seconds":50, "duration_seconds":10, "link_url":"https://example.com", "image_path":"art.png"}
            ],
            "transcript_segments": [
                {"id":"gone", "start_time_seconds":10, "end_time_seconds":15, "text":"B"},
                {"id":"kept", "start_time_seconds":30, "end_time_seconds":35, "text":"C", "words":[{"id":"w", "start_time_seconds":31,"end_time_seconds":32,"text":"C"}]}
            ],
            "video":{"export_settings":{"selected_chapter_ids":["c","b"],"selection_initialized":true}}
        })).unwrap()
    }

    #[test]
    fn triage_preserves_source_mapping_custom_metadata_and_transcript_timing() {
        let project = fixture();
        let result = edit_audio(
            &project,
            AudioEdits {
                remove_files: vec!["b.wav".into()],
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(result.audio_sources.len(), 2);
        assert_eq!(
            result
                .chapters
                .iter()
                .map(|c| c.chapter_number)
                .collect::<Vec<_>>(),
            [1, 2, 2]
        );
        assert_eq!(
            result
                .chapters
                .iter()
                .map(|c| c.start_time_seconds)
                .collect::<Vec<_>>(),
            [0.0, 10.0, 30.0]
        );
        assert_eq!(result.chapters[1].title, "Chapter 2");
        assert_eq!(result.chapters[2].title, "Closing");
        assert_eq!(result.chapters[2].image_path, Some("art.png".into()));
        assert_eq!(result.chapters[2].link_url, "https://example.com");
        assert_eq!(result.transcript_segments.len(), 1);
        assert_eq!(
            result.transcript_segments[0].words[0].start_time_seconds,
            11.0
        );
        assert_eq!(result.video.export_settings.selected_chapter_ids, ["c"]);
        assert_eq!(project, fixture());
    }

    #[test]
    fn multiple_removal_and_all_removal_leave_no_dangling_chapters() {
        let project = fixture();
        let result = edit_audio(
            &project,
            AudioEdits {
                remove_files: vec!["a.wav".into(), "c.wav".into()],
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(result.chapters.len(), 1);
        assert_eq!(result.chapters[0].title, "Chapter 1");
        assert_eq!(result.chapters[0].start_time_seconds, 0.0);
        let empty = edit_audio(
            &project,
            AudioEdits {
                remove_files: project
                    .audio_sources
                    .iter()
                    .map(|s| s.source_path.clone())
                    .collect(),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(
            empty.audio_sources.is_empty()
                && empty.chapters.is_empty()
                && empty.transcript_segments.is_empty()
        );
        assert!(empty.video.export_settings.selected_chapter_ids.is_empty());
    }

    #[test]
    fn unknown_removal_and_duplicate_addition_are_noops() {
        let project = fixture();
        let result = edit_audio(
            &project,
            AudioEdits {
                remove_files: vec!["unknown".into()],
                add_files: vec!["a.wav".into()],
            },
        )
        .unwrap();
        assert_eq!(result, project);
        assert!(edit_audio(
            &project,
            AudioEdits {
                add_files: vec!["missing-file.wav".into()],
                ..Default::default()
            }
        )
        .is_err());
        assert_eq!(project, fixture());
    }
}
