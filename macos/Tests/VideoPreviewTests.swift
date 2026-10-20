import AppKit
import XCTest
@testable import EnCap

final class VideoPreviewTests: XCTestCase {
    func testProductionClientComposesCorePNGWithPackagedRuntime() async throws {
        guard let sourceRoot = ProcessInfo.processInfo.environment["ENCAP_SOURCE_ROOT"],
              FileManager.default.fileExists(atPath: sourceRoot + "/target/release/ffmpeg-runtime/SHA256SUMS") else {
            throw XCTSkip("Set ENCAP_SOURCE_ROOT to a staged production engine with its authenticated runtime")
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let pixels = try XCTUnwrap(NSBitmapImageRep(
            bitmapDataPlanes: nil, pixelsWide: 24, pixelsHigh: 40,
            bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false,
            isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
        ))
        let bytes = try XCTUnwrap(pixels.bitmapData)
        for y in 0..<40 {
            for x in 0..<24 {
                let offset = y * pixels.bytesPerRow + x * 3
                bytes[offset] = x < 12 ? 255 : 0
                bytes[offset + 1] = 0
                bytes[offset + 2] = x < 12 ? 0 : 255
            }
        }
        let artwork = root.appendingPathComponent("表紙 portrait.png")
        try XCTUnwrap(pixels.representation(using: .png, properties: [:])).write(to: artwork)
        var project = ProjectDocument()
        project.metadata.artworkPath = artwork.path
        project.chapters = [Chapter(id: "one", startTimeSeconds: 0, durationSeconds: 1, chapterNumber: 1, title: "One")]
        project.video.exportSettings.width = 160
        project.video.exportSettings.height = 90
        project.video.exportSettings.flipHorizontal = true
        let engine = EngineClient()
        defer { engine.cleanupSession() }
        let destination = root.appendingPathComponent("Core composition.png")
        let rendered = try await engine.previewVideo(project, chapterID: "one", to: destination)
        XCTAssertEqual(rendered, destination)
        let bitmap = try XCTUnwrap(NSBitmapImageRep(data: Data(contentsOf: rendered)))
        XCTAssertEqual(bitmap.pixelsWide, 160)
        XCTAssertEqual(bitmap.pixelsHigh, 90)
        XCTAssertGreaterThan(bitmap.colorAt(x: 70, y: 45)?.blueComponent ?? 0, 0.8)
        XCTAssertGreaterThan(bitmap.colorAt(x: 90, y: 45)?.redComponent ?? 0, 0.8)
    }

    func testPreviewIdentityTracksArtworkAndCompositionChanges() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let artwork = root.appendingPathComponent("表紙.png")
        try Data([1]).write(to: artwork)
        var settings = VideoSettings()
        let original = VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings)
        XCTAssertEqual(original, VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings))
        XCTAssertNotEqual(original, VideoPreviewIdentity(chapterID: "two", artwork: artwork, settings: settings))
        settings.flipHorizontal = true
        XCTAssertNotEqual(original, VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings))
        try Data([1, 2]).write(to: artwork)
        XCTAssertNotEqual(original, VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: VideoSettings()))
        let main = root.appendingPathComponent("main.png")
        try Data([1]).write(to: main)
        let withMain = VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings, mainArtwork: main, projectIdentity: "first")
        XCTAssertNotEqual(withMain, VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings, mainArtwork: main, projectIdentity: "second"))
        try Data([1, 2]).write(to: main)
        XCTAssertNotEqual(withMain, VideoPreviewIdentity(chapterID: "one", artwork: artwork, settings: settings, mainArtwork: main, projectIdentity: "first"))
    }

    func testTaskCancellationTerminatesAndJoinsItsEngineProcess() async throws {
        let marker = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: marker) }
        let joined = expectation(description: "Cancelled child was terminated and joined")
        let task = Task {
            try await EngineClient.runProcess(
                executable: URL(fileURLWithPath: "/bin/sh"),
                arguments: ["-c", "/usr/bin/touch \"$ENCAP_CANCEL_TEST_MARKER\"; exec /bin/sleep 10"],
                environment: ["ENCAP_CANCEL_TEST_MARKER": marker.path],
                processChanged: { process, started in
                    if !started {
                        XCTAssertEqual(process.terminationReason, .uncaughtSignal)
                        joined.fulfill()
                    }
                }
            )
        }
        // Wait for the actual child before cancelling, rather than testing only
        // Swift task state. exec keeps the sleeping process under the same PID.
        for _ in 0..<100 where !FileManager.default.fileExists(atPath: marker.path) {
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTAssertTrue(FileManager.default.fileExists(atPath: marker.path))
        task.cancel()
        await fulfillment(of: [joined], timeout: 2)
        do {
            _ = try await task.value
            XCTFail("A cancelled engine task must not return a successful response")
        } catch {
            XCTAssertTrue(task.isCancelled)
        }
    }
}
