import Foundation
import XCTest
@testable import EnCap

final class TranscriptionClientTests: XCTestCase {
    @MainActor
    func testDelayedStartupRecoveryDoesNotOverwriteNewlyOpenedProject() async {
        let store = AppStore()
        var opened = ProjectDocument()
        opened.metadata.episodeTitle = "Newly opened project"
        var recovered = ProjectDocument()
        recovered.metadata.episodeTitle = "Stale recovery"
        await store.restoreRecoveryIfAvailable {
            // Model the main-actor reentrancy at the engine await boundary.
            store.project = opened
            return recovered
        }
        XCTAssertEqual(store.project, opened)
    }

    func testProgressEventsSurviveSplitUnicodeAndKeepDiagnosticTailBounded() async throws {
        let pipe = Pipe()
        let event = Data("{\"event\":\"progress\",\"stage\":\"verification\",\"message\":\"Vérification 日本語\",\"completed_bytes\":12,\"total_bytes\":24}\n".utf8)
        let observed = ProgressEvents()
        let writer = Task.detached {
            let handle = pipe.fileHandleForWriting
            try handle.write(contentsOf: Data(repeating: 120, count: 80_000))
            try handle.write(contentsOf: Data([10]))
            // Splitting inside arbitrary UTF-8 bytes must not discard the line.
            try handle.write(contentsOf: event.prefix(79))
            try handle.write(contentsOf: event.dropFirst(79))
            try handle.close()
        }
        let tail = EngineClient.readDiagnostics(pipe.fileHandleForReading) { observed.append($0) }
        try await writer.value
        XCTAssertLessThanOrEqual(tail.count, 65_536)
        XCTAssertEqual(observed.values.count, 1)
        XCTAssertEqual(observed.values.first?.message, "Vérification 日本語")
        XCTAssertEqual(observed.values.first?.completedBytes, 12)
        XCTAssertTrue(observed.values.first?.status.contains("Vérification") == true)
    }

    func testLargeFinalJSONAndVerboseProgressDoNotDeadlockPipes() async throws {
        let observed = ProgressEvents()
        let program = #"BEGIN { for (i=0;i<5000;i++) print "backend diagnostic line" > "/dev/stderr"; print "{\"event\":\"progress\",\"stage\":\"recognition\",\"fraction\":0.5}" > "/dev/stderr"; printf "{\"text\":\""; for (i=0;i<180000;i++) printf "x"; print "\"}"; }"#
        let output = try await EngineClient.runProcess(
            executable: URL(fileURLWithPath: "/usr/bin/awk"), arguments: [program],
            environment: [:], progress: { observed.append($0) }
        )
        let value = try XCTUnwrap(JSONSerialization.jsonObject(with: output) as? [String: String])
        XCTAssertEqual(value["text"]?.count, 180_000)
        XCTAssertEqual(observed.values.first?.stage, "recognition")
        XCTAssertEqual(observed.values.first?.status, "recognition · 50%")
    }

    func testLegacyModelResponseAndDetailedSharedModelBothDecode() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let legacy = Data(#"{"id":"existing","name":"Existing","download_size":"1 byte","languages":"en","description":"Local","installed":false,"download_allowed":true}"#.utf8)
        let old = try decoder.decode(TranscriptionModelInfo.self, from: legacy)
        XCTAssertNil(old.role)
        XCTAssertFalse(old.isAligner)
        let detailed = Data(#"{"id":"aligner","name":"Aligner","download_size":"975854832 bytes","languages":"en","description":"Alignment","installed":true,"download_allowed":true,"download_size_bytes":975854832,"role":"aligner","recognition_languages":[],"timing_languages":["en","zh"],"installation_state":"present_unverified","license":{"identifier":"Apache-2.0","notice":"Publisher notice","url":"https://example.invalid/license"}}"#.utf8)
        let model = try decoder.decode(TranscriptionModelInfo.self, from: detailed)
        XCTAssertTrue(model.isAligner)
        XCTAssertEqual(model.timingLanguageSummary, "en, zh")
        XCTAssertEqual(model.downloadSizeBytes, 975_854_832)
        XCTAssertEqual(model.license?.identifier, "Apache-2.0")
        XCTAssertEqual(model.installationSummary, "Files present; verified before inference")
    }

    @MainActor
    func testReconciliationWarningIsReadFromPersistedOriginWithoutChangingText() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = Data(#"{"transcript_segments":[{"id":"stable","start_time_seconds":0,"end_time_seconds":1,"speaker":"New speaker","text":"New text","avid_core":{"version":1,"source_id":"source","reconciliation_warning":"Review speaker names; prior transcript is preserved in project history.","previous_transcript":[{"speaker":"Manual label","text":"Edited original"}]}}]}"#.utf8)
        let project = try decoder.decode(ProjectDocument.self, from: payload)
        let store = AppStore()
        store.project = project
        XCTAssertEqual(store.transcriptionReconciliationWarning, "Review speaker names; prior transcript is preserved in project history.")
        XCTAssertEqual(store.project, project)
        XCTAssertEqual(store.project?.transcriptSegments[0].speaker, "New speaker")
        XCTAssertEqual(store.project?.transcriptSegments[0].text, "New text")
    }

    @MainActor
    func testProjectWarningRemainsVisibleWithoutActiveTranscriptAndPreservesHistory() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = Data(#"{"audio_sources":[{"id":"remaining","source_path":"/media/silence.wav","display_name":"Silence","duration_seconds":3}],"transcript_segments":[],"avid_transcript_history":[{"id":"previous","speaker":"Manual name","text":"Retained original edit"}],"avid_reconciliation_warning":"Prior edited transcript is retained in project history."}"#.utf8)
        let project = try decoder.decode(ProjectDocument.self, from: payload)
        let store = AppStore()
        store.project = project
        XCTAssertTrue(store.project?.transcriptSegments.isEmpty == true)
        XCTAssertEqual(store.project?.audioSources.count, 1)
        XCTAssertEqual(store.transcriptionReconciliationWarning, "Prior edited transcript is retained in project history.")
        XCTAssertEqual(store.project?.avidTranscriptHistory?.count, 1)
        XCTAssertEqual(store.project, project)
        store.project?.avidReconciliationWarning = nil
        XCTAssertNil(store.transcriptionReconciliationWarning)
        XCTAssertEqual(store.project?.avidTranscriptHistory, project.avidTranscriptHistory)
    }

    @MainActor
    func testEditedTextDisablesWordCaptionsAndKeepsSpeaker() {
        let store = AppStore()
        store.transcriptionAvailability = TranscriptionAvailability(available: true)
        var project = ProjectDocument()
        project.transcriptSegments = [TranscriptSegment(
            id: "stable", startTimeSeconds: 1, endTimeSeconds: 2, speaker: "Speaker name", text: "Original",
            words: [TranscriptWord(id: "word", startTimeSeconds: 1, endTimeSeconds: 2, text: "Original")]
        )]
        store.project = project
        XCTAssertTrue(store.canExportWordCaptions)
        store.project?.transcriptSegments[0].replaceText("Edited")
        XCTAssertFalse(store.canExportWordCaptions)
        XCTAssertEqual(store.project?.transcriptSegments[0].speaker, "Speaker name")
        XCTAssertEqual(store.project?.transcriptSegments[0].id, "stable")
    }

    @MainActor
    func testModelSelectionLanguageAndAlignmentPersistWithoutTouchingTranscript() {
        let store = AppStore()
        var project = ProjectDocument()
        let segment = TranscriptSegment(id: "edited", startTimeSeconds: 1, endTimeSeconds: 2,
                                        speaker: "Named speaker", text: "Edited text")
        project.transcriptSegments = [segment]
        store.project = project
        XCTAssertEqual(store.selectedProviderID, "whisper-large-v3")
        store.selectedProviderID = "parakeet-tdt-v3"
        store.selectedAlignmentModelID = "qwen3-forced-aligner-0.6b-4bit"
        store.transcriptionLanguage = "pt-BR"
        XCTAssertEqual(store.project?.transcriptSettings.recognitionModelId, "parakeet-tdt-v3")
        XCTAssertEqual(store.project?.transcriptSettings.alignmentModelId, "qwen3-forced-aligner-0.6b-4bit")
        XCTAssertEqual(store.project?.transcriptSettings.language, "pt-BR")
        XCTAssertEqual(store.project?.transcriptSegments, [segment])
        store.selectedAlignmentModelID = ""
        XCTAssertNil(store.project?.transcriptSettings.alignmentModelId)
    }
}

private final class ProgressEvents: @unchecked Sendable {
    private let lock = NSLock()
    private var storage: [EngineProgress] = []
    func append(_ event: EngineProgress) {
        lock.lock()
        storage.append(event)
        lock.unlock()
    }
    var values: [EngineProgress] {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }
}
