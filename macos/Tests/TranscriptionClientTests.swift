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

    func testLinkedProgressCopiesUnicodeEventAndKeepsFormatting() throws {
        let borrowed = Data("{\"event\":\"progress\",\"stage\":\"verification\",\"message\":\"Vérification 日本語\",\"completed_bytes\":12,\"total_bytes\":24}".utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let copied = Data(borrowed)
        let event = try decoder.decode(EngineProgress.self, from: copied)
        XCTAssertEqual(event.message, "Vérification 日本語")
        XCTAssertEqual(event.completedBytes, 12)
        XCTAssertTrue(event.status.contains("Vérification"))
    }

    func testTranscriptionRequestUsesTypedFieldsAndPreservesExplicitProvider() throws {
        let bytes = try EngineClient.applicationRequest([
            "transcribe", "/tmp/日本語 project.json", "whisper-large-v3",
            "--word-timestamps", "--language", "pt-BR", "--alignment-model", "qwen-aligner"
        ])
        let request = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: Any])
        XCTAssertEqual(request["schema_version"] as? Int, 1)
        XCTAssertEqual(request["operation"] as? String, "transcribe")
        XCTAssertEqual(request["provider"] as? String, "whisper-large-v3")
        XCTAssertEqual(request["word_timestamps"] as? Bool, true)
        XCTAssertEqual(request["alignment_model"] as? String, "qwen-aligner")
        XCTAssertEqual(request["language"] as? String, "pt-BR")
        XCTAssertEqual(request["payload"] as? String, "/tmp/日本語 project.json")
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
