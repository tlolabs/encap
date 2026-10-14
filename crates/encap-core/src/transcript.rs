use crate::TranscriptSegment;
use std::fmt::Write;

pub fn render_transcript_text(segments: &[TranscriptSegment]) -> String {
    let mut output = String::with_capacity(segments.len() * 48);
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
    let mut output = String::with_capacity(segments.len() * 80);
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
