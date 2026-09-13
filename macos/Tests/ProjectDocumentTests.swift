import XCTest
@testable import EnCap

final class ProjectDocumentTests: XCTestCase {
    @MainActor
    func testFileImportUsesOnePresenterWithAnExplicitPurpose() {
        let store = AppStore()

        store.presentFileImporter(.audioFolder)

        XCTAssertTrue(store.isFileImporterPresented)
        guard case .audioFolder? = store.fileImportKind else {
            return XCTFail("Expected an audio-folder import request")
        }
    }

    func testOutputBaseNameIsFileSafe() {
        var project = ProjectDocument()
        project.metadata.episodeTitle = "An Episode: Part 1"
        XCTAssertEqual(project.outputBaseName, "An-Episode--Part-1")
    }

    func testSnakeCaseEnginePayloadDecodes() throws {
        let payload = """
        {
          "schema_version": 1,
          "project_title": "Test",
          "metadata": {"podcast_title":"P","episode_title":"E","summary":"","artwork_path":null},
          "audio_sources": [],
          "chapters": [
            {
              "id":"chapter-1",
              "start_time_seconds":0,
              "duration_seconds":11,
              "chapter_number":1,
              "title":"Chapter 1",
              "link_url":"https://example.com",
              "image_path":null
            }
          ],
          "transcript_segments": [],
          "export_settings": {"output_format":"mp3","quality_preset":"320k","encoder":"lame","channels":2}
        }
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let project = try decoder.decode(ProjectDocument.self, from: payload)
        XCTAssertEqual(project.metadata.podcastTitle, "P")
        XCTAssertEqual(project.chapters.first?.linkUrl, "https://example.com")
    }
}

final class ReviewRegressionTests: XCTestCase {
    func testChangingFormatOrChannelsKeepsEncodingValid() {
        var settings = ExportSettings()
        settings.outputFormat = "aac"
        settings.normalizeSelection()
        XCTAssertEqual(settings.encoder, "ffmpeg")
        settings.channels = 1
        settings.normalizeSelection()
        XCTAssertEqual(settings.qualityPreset, "160k")
        settings.encoder = "audio_toolbox"
        settings.outputFormat = "mp3"
        settings.normalizeSelection()
        XCTAssertEqual(settings.encoder, "lame")
        XCTAssertEqual(settings.qualityPreset, "160k")
    }

    func testEngineDrainsBothPipesBeyondTheirCapacity() async throws {
        let data = try await EngineClient.runProcess(
            executable: URL(fileURLWithPath: "/usr/bin/perl"),
            arguments: ["-e", "alarm 10; print STDERR 'e' x 2000000; print 'x' x 2000000;"],
            environment: ProcessInfo.processInfo.environment
        )
        XCTAssertEqual(data.count, 2_000_000)
        XCTAssertEqual(data.first, Character("x").asciiValue)
    }

    func testEngineReportsStructuredFailureAfterLargeDiagnostics() async {
        do {
            _ = try await EngineClient.runProcess(
                executable: URL(fileURLWithPath: "/usr/bin/perl"),
                arguments: ["-e", "alarm 10; print STDERR 'e' x 2000000; print '{\"error\":\"test failure\"}'; exit 1;"],
                environment: ProcessInfo.processInfo.environment
            )
            XCTFail("Expected an engine failure")
        } catch {
            XCTAssertEqual(error.localizedDescription, "test failure")
        }
    }

    func testSessionCleanupCannotDeleteUnownedDirectories() throws {
        let engine = EngineClient()
        let foreign = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: foreign, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: foreign) }
        var project = ProjectDocument()
        project.workingDir = foreign.path
        engine.cleanup(project: project)
        XCTAssertTrue(FileManager.default.fileExists(atPath: foreign.path))
        let owned = engine.sessionDirectory.appendingPathComponent("encap-project-test")
        try FileManager.default.createDirectory(at: owned, withIntermediateDirectories: true)
        project.workingDir = owned.path
        engine.cleanup(project: project)
        XCTAssertFalse(FileManager.default.fileExists(atPath: owned.path))
        engine.cleanupSession()
        XCTAssertFalse(FileManager.default.fileExists(atPath: engine.sessionDirectory.path))
    }

    @MainActor
    func testBusyStoreDoesNotPresentAnotherImport() {
        let store = AppStore()
        store.isWorking = true
        store.presentFileImporter(.audioFolder)
        XCTAssertFalse(store.isFileImporterPresented)
    }
}
