import Foundation
import XCTest
@testable import AVIDTranscription

final class TranscriptTests: XCTestCase {
    private let provenance = TranscriptProvenance(engineID: "test", modelID: "fixture")

    func testTimingValidationAndJSONCannotBypassIt() throws {
        for pair in [(-1.0, 1.0), (2.0, 1.0), (.infinity, .infinity), (.nan, 1.0)] {
            XCTAssertThrowsError(try TranscriptWord(text: "word", startSeconds: pair.0, endSeconds: pair.1))
        }
        XCTAssertThrowsError(try TranscriptWord(text: "word", startSeconds: 1))
        XCTAssertThrowsError(try TranscriptWord(text: "word", confidence: 1.1))
        XCTAssertThrowsError(try TranscriptWord(text: "word", confidence: .nan))
        let invalid = Data(#"{"text":"word","startSeconds":4,"endSeconds":2}"#.utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(TranscriptWord.self, from: invalid))
        let invalidSegment = Data(#"{"text":"word","words":[],"startSeconds":-1,"endSeconds":2}"#.utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(TranscriptSegment.self, from: invalidSegment))
    }

    func testUntimedRecognitionSurvivesRoundTrip() throws {
        let transcript = try Transcript(
            segments: [TranscriptSegment(text: "A corrected thought.")],
            language: "en", provenance: provenance
        )
        XCTAssertFalse(transcript.hasCompleteWordTiming)
        let encoded = try JSONEncoder().encode(transcript)
        XCTAssertEqual(try JSONDecoder().decode(Transcript.self, from: encoded), transcript)
        XCTAssertThrowsError(try CaptionBuilder.cues(from: transcript)) { error in
            XCTAssertEqual(error as? TranscriptionError, .missingWordTiming)
        }
    }

    func testSourceOffsetsPreserveMissingTimesAndProvenance() throws {
        let transcript = try Transcript(
            segments: [TranscriptSegment(
                text: "Hello world",
                words: [
                    TranscriptWord(text: "Hello", startSeconds: 0.2, endSeconds: 0.5, confidence: 0.9),
                    TranscriptWord(text: "world"),
                ], startSeconds: 0, endSeconds: 1
            )], language: "en", provenance: provenance
        )
        let moved = try transcript.offsettingTimes(by: 10)
        XCTAssertEqual(moved.segments[0].startSeconds, 10)
        XCTAssertEqual(moved.segments[0].words[0].startSeconds, 10.2)
        XCTAssertNil(moved.segments[0].words[1].startSeconds)
        XCTAssertEqual(moved.provenance, provenance)
        XCTAssertEqual(transcript.segments[0].words[0].startSeconds, 0.2)
        XCTAssertThrowsError(try transcript.offsettingTimes(by: -2))
        XCTAssertThrowsError(try transcript.offsettingTimes(by: .nan))
    }

    func testManualCorrectionInvalidatesWordAlignment() throws {
        let transcript = try Transcript(
            segments: [TranscriptSegment(
                text: "wrong", words: [TranscriptWord(text: "wrong", startSeconds: 0, endSeconds: 1)],
                startSeconds: 0, endSeconds: 1
            )], language: "en", provenance: provenance,
            alignmentProvenance: TranscriptProvenance(engineID: "aligner", modelID: "alignment")
        )
        let corrected = try transcript.correctingSegment(at: 0, text: "correct")
        XCTAssertEqual(corrected.text, "correct")
        XCTAssertTrue(corrected.segments[0].words.isEmpty)
        XCTAssertEqual(corrected.segments[0].startSeconds, 0)
        XCTAssertNil(corrected.alignmentProvenance)
        XCTAssertFalse(corrected.hasCompleteWordTiming)
        XCTAssertEqual(corrected.provenance, provenance)
        XCTAssertThrowsError(try transcript.correctingSegment(at: 2, text: "invalid"))
    }

    func testRequestValidationRequiresLocalFilesAndValidOffset() throws {
        let audio = URL(fileURLWithPath: "/tmp/audio.wav")
        let model = URL(fileURLWithPath: "/tmp/model")
        XCTAssertNoThrow(try RecognitionRequest(audioURL: audio, modelID: "model", modelDirectory: model).validate())
        XCTAssertThrowsError(try RecognitionRequest(
            audioURL: URL(string: "https://example.com/audio.wav")!, modelID: "model", modelDirectory: model
        ).validate())
        XCTAssertThrowsError(try RecognitionRequest(
            audioURL: audio, modelID: "model", modelDirectory: model, sourceStartSeconds: -1
        ).validate())
    }

    func testBatchCorrectionsValidateWholeTransactionAndKeepUnaffectedWords() throws {
        let transcript = try Transcript(segments: [
            TranscriptSegment(text: "wrong", words: [TranscriptWord(text: "wrong", startSeconds: 0, endSeconds: 1)]),
            TranscriptSegment(text: "kept", words: [TranscriptWord(text: "kept", startSeconds: 1, endSeconds: 2)]),
        ], provenance: provenance, alignmentProvenance: .init(engineID: "aligner", modelID: "fixture"))
        let corrected = try transcript.correctingSegments([.init(index: 0, text: "fixed")])
        XCTAssertTrue(corrected.segments[0].words.isEmpty)
        XCTAssertEqual(corrected.segments[1], transcript.segments[1])
        XCTAssertNil(corrected.alignmentProvenance)
        XCTAssertEqual(try transcript.correctingSegments([]), transcript)
        XCTAssertThrowsError(try transcript.correctingSegments([.init(index: 0, text: "fixed"), .init(index: 2, text: "invalid")]))
        XCTAssertThrowsError(try transcript.correctingSegments([.init(index: 0, text: "first"), .init(index: 0, text: "second")]))
        XCTAssertEqual(transcript.segments[0].text, "wrong")
    }

    func testTranscriptValidationRejectsMissingProvenanceAndOutOfOrderWords() throws {
        let missing = try Transcript(segments: [], provenance: .init(engineID: "", modelID: ""))
        XCTAssertThrowsError(try missing.validate())
        let outOfOrder = try Transcript(segments: [TranscriptSegment(text: "two one", words: [
            TranscriptWord(text: "two", startSeconds: 2, endSeconds: 3),
            TranscriptWord(text: "one", startSeconds: 1, endSeconds: 2),
        ])], provenance: provenance)
        XCTAssertThrowsError(try outOfOrder.validate())
    }
}
