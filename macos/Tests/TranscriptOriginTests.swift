import XCTest
@testable import EnCap

final class TranscriptOriginTests: XCTestCase {
    private func segment() throws -> TranscriptSegment {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(TranscriptSegment.self, from: Data("""
        {"id":"segment","start_time_seconds":30.5,"end_time_seconds":31.5,
         "speaker":"Edited speaker","text":"Edited text",
         "words":[{"id":"word","start_time_seconds":30.5,"end_time_seconds":31.5,"text":"Original"}],
         "avid_core":{"version":1,"source_id":"c","source_duration_seconds":30,
         "source_timeline_offset_seconds":30,"source_offset_seconds":12.5,"segment_index":0,
         "timing_status":"timed","future_origin":{"key_with_underscores":true},
         "transcript":{"language":"en","recognition":{"model_id":"whisper-large-v3"},
         "segments":[{"start":13,"end":14,"text":"Original"}]}}}
        """.utf8))
    }

    func testNativeEditInvalidatesAlignmentAndKeepsOriginalRecord() throws {
        var segment = try segment()
        let original = segment.avidCore
        segment.replaceText(segment.text)
        XCTAssertEqual(segment.words.count, 1)
        segment.replaceText("New edit")
        XCTAssertTrue(segment.words.isEmpty)
        XCTAssertEqual(segment.avidCore?.timingStatus, "invalidated")
        XCTAssertEqual(segment.id, "segment")
        XCTAssertEqual(segment.speaker, "Edited speaker")
        XCTAssertEqual(segment.startTimeSeconds, 30.5)
        guard case .object(let before)? = original?.payload,
              case .object(let after)? = segment.avidCore?.payload else { return XCTFail("Missing provenance") }
        XCTAssertEqual(after["transcript"], before["transcript"])
        XCTAssertEqual(after["future_origin"], before["future_origin"])
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(segment)) as? [String: Any])
        let origin = try XCTUnwrap(object["avid_core"] as? [String: Any])
        let future = try XCTUnwrap(origin["future_origin"] as? [String: Any])
        XCTAssertEqual(future["key_with_underscores"] as? Bool, true)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        XCTAssertEqual(try decoder.decode(TranscriptSegment.self, from: encoder.encode(segment)), segment)
    }

    func testNativeRemovalPreservesSourceRecordAndShiftsProjectionOnce() throws {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/b.wav", displayName: "B", durationSeconds: 30, avidSourceId: "b"),
            AudioSource(sourcePath: "/c.wav", displayName: "C", durationSeconds: 30, avidSourceId: "c")
        ]
        let timed = try segment()
        var untimed = timed
        untimed.id = "untimed"
        untimed.startTimeSeconds = 0
        untimed.endTimeSeconds = 0
        untimed.words = []
        guard case .object(var fields)? = untimed.avidCore?.payload else { return XCTFail("Missing record") }
        fields["source_id"] = .string("b")
        fields["timing_status"] = .string("untimed")
        untimed.avidCore?.payload = .object(fields)
        project.transcriptSegments = [untimed, timed]
        project.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(project.transcriptSegments.map(\.id), ["segment"])
        XCTAssertEqual(project.transcriptSegments[0].startTimeSeconds, 0.5)
        XCTAssertEqual(project.transcriptSegments[0].words[0].startTimeSeconds, 0.5)
        XCTAssertEqual(project.transcriptSegments[0].avidCore?.sourceTimelineOffsetSeconds, 0)
        guard case .object(let before)? = timed.avidCore?.payload,
              case .object(let after)? = project.transcriptSegments[0].avidCore?.payload else { return XCTFail("Missing record") }
        XCTAssertEqual(after["transcript"], before["transcript"])
    }

    func testLegacyMissingWordsAndSettingsRemainCompatible() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let segment = try decoder.decode(TranscriptSegment.self, from: Data("""
        {"id":"legacy","start_time_seconds":0,"end_time_seconds":2,"text":"User edit","speaker":"Host"}
        """.utf8))
        XCTAssertTrue(segment.words.isEmpty)
        XCTAssertNil(segment.avidCore)
        let settings = try decoder.decode(TranscriptSettings.self, from: Data("{}".utf8))
        XCTAssertFalse(settings.includeWordTimestamps)
        XCTAssertNil(settings.recognitionModelId)
        var project = ProjectDocument()
        project.transcriptSegments = [segment]
        project.transcriptSettings.recognitionModelId = "whisper-large-v3"
        project.transcriptSettings.alignmentModelId = "qwen3-forced-aligner-0.6b-4bit"
        project.transcriptSettings.language = "pt-BR"
        let recovery = try JSONDecoder().decode(ProjectDocument.self, from: JSONEncoder().encode(project))
        XCTAssertEqual(recovery, project)
    }

    func testRetainedSourceOvershootKeepsTextAndClipsHostTimingOnly() throws {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/a.wav", displayName: "A", durationSeconds: 10, avidSourceId: "a"),
            AudioSource(sourcePath: "/b.wav", displayName: "B", durationSeconds: 20, avidSourceId: "b")
        ]
        var original = try segment()
        original.startTimeSeconds = 9.5
        original.endTimeSeconds = 10.2
        original.words[0].startTimeSeconds = 9.5
        original.words[0].endTimeSeconds = 10.2
        guard case .object(var fields)? = original.avidCore?.payload else { return XCTFail("Missing source") }
        fields["source_id"] = .string("a")
        fields["source_timeline_offset_seconds"] = .number(0)
        fields["source_duration_seconds"] = .number(10)
        original.avidCore?.payload = .object(fields)
        let legacy = TranscriptSegment(id: "legacy-crossing", startTimeSeconds: 9.5, endTimeSeconds: 10.2, speaker: "", text: "Legacy crossing")
        project.transcriptSegments = [original, legacy]
        project.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(project.transcriptSegments.count, 1)
        let retained = project.transcriptSegments[0]
        XCTAssertEqual(retained.id, original.id)
        XCTAssertEqual(retained.text, original.text)
        XCTAssertEqual(retained.speaker, original.speaker)
        XCTAssertEqual(retained.startTimeSeconds, 9.5)
        XCTAssertEqual(retained.endTimeSeconds, 10)
        XCTAssertEqual(retained.words[0].endTimeSeconds, 10)
        XCTAssertEqual(retained.avidCore, original.avidCore)
    }

    func testRemovedCarrierTransfersCompleteHistoryAndWarningWithoutDuplicates() throws {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/a.wav", displayName: "A", durationSeconds: 30, avidSourceId: "a"),
            AudioSource(sourcePath: "/c.wav", displayName: "C", durationSeconds: 30, avidSourceId: "c")
        ]
        let historical: JSONValue = .object([
            "id": .string("old-c"), "text": .string("User edited C"), "speaker": .string("Custom C"),
            "future_history": .object(["key_with_underscores": .array([.boolean(true), .null])])
        ])
        var a = try segment()
        let c = a
        a.id = "a-carrier"
        a.startTimeSeconds = 0.5
        a.endTimeSeconds = 1.5
        a.words = []
        guard case .object(var fields)? = a.avidCore?.payload else { return XCTFail("Missing source") }
        fields["source_id"] = .string("a")
        fields["source_timeline_offset_seconds"] = .number(0)
        fields["previous_transcript"] = .array([historical])
        fields["reconciliation_warning"] = .string("Review speaker assignments")
        a.avidCore?.payload = .object(fields)
        guard case .object(let cFields)? = c.avidCore?.payload else { return XCTFail("Missing source") }
        project.transcriptSegments = [a, c]
        var duplicateHistory = project
        var duplicateFields = cFields
        duplicateFields["previous_transcript"] = .array([historical])
        duplicateHistory.transcriptSegments[1].avidCore?.payload = .object(duplicateFields)
        duplicateHistory.removeAudioSources(ids: ["/a.wav"])
        guard case .object(let deduplicated)? = duplicateHistory.transcriptSegments[0].avidCore?.payload else { return XCTFail("Missing carrier") }
        XCTAssertEqual(deduplicated["previous_transcript"], .array([historical]))
        var carrierRetained = project
        carrierRetained.removeAudioSources(ids: ["/c.wav"])
        guard case .object(let carrierFields)? = carrierRetained.transcriptSegments.first?.avidCore?.payload else { return XCTFail("Missing retained carrier") }
        XCTAssertEqual(carrierFields["previous_transcript"], .array([historical]))
        project.removeAudioSources(ids: ["/a.wav"])
        XCTAssertEqual(project.transcriptSegments.count, 1)
        guard case .object(let retained)? = project.transcriptSegments[0].avidCore?.payload else { return XCTFail("Missing retained source") }
        XCTAssertEqual(retained["previous_transcript"], .array([historical]))
        XCTAssertEqual(retained["reconciliation_warning"], .string("Review speaker assignments"))
        XCTAssertEqual(retained["transcript"], cFields["transcript"])
        project.removeAudioSources(ids: ["/c.wav"])
        XCTAssertTrue(project.transcriptSegments.isEmpty)
    }

    func testSilentSourceRetainsProjectHistoryThroughRecoveryAndClearTombstone() throws {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/a.wav", displayName: "A", durationSeconds: 30, avidSourceId: "a"),
            AudioSource(sourcePath: "/c.wav", displayName: "Silent C", durationSeconds: 30, avidSourceId: "c")
        ]
        let historical: JSONValue = .object(["id": .string("old-c"), "text": .string("Edited C"),
            "speaker": .string("Custom C"), "future": .object(["keep_me": .boolean(true)])])
        var a = try segment()
        a.words = []
        a.startTimeSeconds = 0
        a.endTimeSeconds = 1
        guard case .object(var fields)? = a.avidCore?.payload else { return XCTFail("Missing source") }
        fields["source_id"] = .string("a")
        fields["source_timeline_offset_seconds"] = .number(0)
        fields["previous_transcript"] = .array([historical])
        fields["reconciliation_warning"] = .string("Review history for C")
        a.avidCore?.payload = .object(fields)
        project.transcriptSegments = [a]
        project.removeAudioSources(ids: ["/a.wav"])
        XCTAssertTrue(project.transcriptSegments.isEmpty)
        XCTAssertEqual(project.avidTranscriptHistory, [historical])
        XCTAssertEqual(project.avidReconciliationWarning, "Review history for C")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        var recovered = try decoder.decode(ProjectDocument.self, from: encoder.encode(project))
        XCTAssertEqual(recovered.avidTranscriptHistory, [historical])
        recovered.removeAudioSources(ids: ["/c.wav"])
        XCTAssertNil(recovered.avidTranscriptHistory)
        XCTAssertNil(recovered.avidReconciliationWarning)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(recovered)) as? [String: Any])
        XCTAssertTrue(object["avid_transcript_history"] is NSNull)
        XCTAssertTrue(object["avid_reconciliation_warning"] is NSNull)
    }
}
