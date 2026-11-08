import XCTest
@testable import AVIDTranscription

final class CaptioningTests: XCTestCase {
    private func transcript(_ words: [TranscriptWord], language: String? = "en") throws -> Transcript {
        try Transcript(
            segments: [TranscriptSegment(text: words.map(\.text).joined(separator: " "), words: words)],
            language: language, provenance: TranscriptProvenance(engineID: "test", modelID: "fixture")
        )
    }

    func testTrimmingMapsWordsExactlyOnceToTimeline() throws {
        let original = try transcript([
            TranscriptWord(text: "before", startSeconds: 9, endSeconds: 10),
            TranscriptWord(text: "first", startSeconds: 10, endSeconds: 10.5),
            TranscriptWord(text: "last", startSeconds: 10.8, endSeconds: 12),
            TranscriptWord(text: "after", startSeconds: 12, endSeconds: 13),
        ])
        let cues = try CaptionBuilder.cues(
            from: original,
            window: CaptionWindow(sourceStartSeconds: 10, sourceEndSeconds: 11, timelineStartSeconds: 5)
        )
        XCTAssertEqual(cues.count, 1)
        XCTAssertEqual(cues[0].text, "first last")
        XCTAssertEqual(cues[0].startSeconds, 5)
        XCTAssertEqual(cues[0].endSeconds, 6)
        XCTAssertEqual(cues[0].words[1].startSeconds!, 5.8, accuracy: 0.000001)
        XCTAssertEqual(cues[0].words[1].endSeconds, 6)
        XCTAssertEqual(original.segments[0].words[1].startSeconds, 10)
    }

    func testGroupingBreaksAtPauseSentenceAndWordLimit() throws {
        let source = try transcript([
            TranscriptWord(text: "One", startSeconds: 0, endSeconds: 0.2),
            TranscriptWord(text: "two", startSeconds: 0.2, endSeconds: 0.4),
            TranscriptWord(text: "three.", startSeconds: 0.4, endSeconds: 0.6),
            TranscriptWord(text: "Four", startSeconds: 2, endSeconds: 2.2),
            TranscriptWord(text: "five", startSeconds: 2.3, endSeconds: 2.5),
        ])
        let cues = try CaptionBuilder.cues(from: source, options: CaptionOptions(maximumWords: 2))
        XCTAssertEqual(cues.map(\.text), ["One two", "three.", "Four five"])
    }

    func testUnicodePunctuationAndUnspacedLanguages() throws {
        let japanese = try transcript([
            TranscriptWord(text: "今日は", startSeconds: 0, endSeconds: 0.4),
            TranscriptWord(text: "晴れ", startSeconds: 0.4, endSeconds: 0.8),
            TranscriptWord(text: "。", startSeconds: 0.8, endSeconds: 0.9),
        ], language: "ja")
        XCTAssertEqual(try CaptionBuilder.cues(from: japanese).first?.text, "今日は晴れ。")
        let emoji = try transcript([
            TranscriptWord(text: "👨‍👩‍👧‍👦", startSeconds: 0, endSeconds: 0.2),
            TranscriptWord(text: "hi!", startSeconds: 0.2, endSeconds: 0.4),
        ])
        XCTAssertEqual(try CaptionBuilder.cues(from: emoji, options: CaptionOptions(maximumCharacters: 5)).count, 1)
        let punctuation = try transcript([
            TranscriptWord(text: "Hello", startSeconds: 0, endSeconds: 0.2),
            TranscriptWord(text: ",", startSeconds: 0.2, endSeconds: 0.2),
            TranscriptWord(text: "world!", startSeconds: 0.2, endSeconds: 0.5),
        ])
        XCTAssertEqual(try CaptionBuilder.cues(from: punctuation).first?.text, "Hello, world!")
    }

    func testMissingOrUnorderedTimingIsRejected() throws {
        let unaligned = try transcript([TranscriptWord(text: "missing")])
        XCTAssertThrowsError(try CaptionBuilder.cues(from: unaligned))
        let unordered = try transcript([
            TranscriptWord(text: "second", startSeconds: 1, endSeconds: 2),
            TranscriptWord(text: "first", startSeconds: 0, endSeconds: 1),
        ])
        XCTAssertThrowsError(try CaptionBuilder.cues(from: unordered))
        let source = try transcript([TranscriptWord(text: "ok", startSeconds: 0, endSeconds: 1)])
        XCTAssertThrowsError(try CaptionBuilder.cues(from: source, options: CaptionOptions(maximumWords: 0)))
        XCTAssertThrowsError(try CaptionBuilder.cues(from: source, window: CaptionWindow(sourceStartSeconds: 2, sourceEndSeconds: 1)))
    }

    func testSubtitleExportUsesCorrectClockAndEscapesCueInjection() throws {
        let cues = [try CaptionCue(startSeconds: 3661.025, endSeconds: 3662.5, text: "<b>A</b> & B\n\n00:00:00 --> nope")]
        let srt = try CaptionExporter.srt(cues)
        XCTAssertTrue(srt.contains("01:01:01,025 --> 01:01:02,500"))
        XCTAssertTrue(srt.contains("&lt;b&gt;A&lt;/b&gt; &amp; B 00:00:00 --&gt; nope"))
        XCTAssertFalse(srt.contains("\n\n00:00:00"))
        let vtt = try CaptionExporter.webVTT(cues)
        XCTAssertTrue(vtt.hasPrefix("WEBVTT\n\n"))
        XCTAssertTrue(vtt.contains("01:01:01.025 --> 01:01:02.500"))
        XCTAssertEqual(try CaptionExporter.webVTT([]), "WEBVTT\n\n")
        XCTAssertThrowsError(try CaptionCue(startSeconds: 1, endSeconds: 1, text: "zero"))
        let tiny = try CaptionCue(startSeconds: 0.0001, endSeconds: 0.0002, text: "short")
        XCTAssertTrue(try CaptionExporter.srt([tiny]).contains("00:00:00,000 --> 00:00:00,001"))
    }
}
