use crate::TranscriptSegment;

pub fn render_transcript_text(segments: &[TranscriptSegment]) -> String {
    let mut output = String::new();
    for segment in segments {
        let text = segment.text.trim();
        if text.is_empty() {
            continue;
        }
        if !segment.speaker.trim().is_empty() {
            output.push_str(segment.speaker.trim());
            output.push_str(": ");
        }
        output.push_str(text);
        output.push('\n');
    }
    output
}

pub fn render_srt(segments: &[TranscriptSegment]) -> String {
    let mut output = String::new();
    for (index, segment) in segments.iter().enumerate() {
        output.push_str(&(index + 1).to_string());
        output.push('\n');
        output.push_str(&format_time(segment.start_time_seconds));
        output.push_str(" --> ");
        output.push_str(&format_time(segment.end_time_seconds));
        output.push('\n');
        if !segment.speaker.trim().is_empty() {
            output.push_str(segment.speaker.trim());
            output.push_str(": ");
        }
        output.push_str(segment.text.trim());
        output.push_str("\n\n");
    }
    output
}

fn format_time(seconds: f64) -> String {
    let millis = (seconds.max(0.0) * 1000.0).round() as u64;
    format!(
        "{:02}:{:02}:{:02},{:03}",
        millis / 3_600_000,
        (millis / 60_000) % 60,
        (millis / 1000) % 60,
        millis % 1000
    )
}
