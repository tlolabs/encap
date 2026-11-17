import AppKit
import XCTest
@testable import EnCap

final class VideoPreviewTests: XCTestCase {
    private static func waitForSignal(_ signal: DispatchSemaphore) -> Bool {
        signal.wait(timeout: .now() + 5) == .success
    }
    func testLinkedClientComposesCorePNGWithoutMediaExecutables() async throws {
        guard let library = ProcessInfo.processInfo.environment["ENCAP_APP_LIBRARY"],
              FileManager.default.fileExists(atPath: library) else {
            throw XCTSkip("Set ENCAP_APP_LIBRARY to the locally built linked application library")
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

    func testShutdownCountsPreparationAndRejectsLaterNativeWork() async throws {
        let entered = DispatchSemaphore(value: 0)
        let proceed = DispatchSemaphore(value: 0)
        let engine = EngineClient(operationPreparationHook: {
            XCTAssertFalse(Thread.isMainThread)
            entered.signal()
            proceed.wait()
        })
        let operation = Task { try await engine.waveform(path: "/unavailable/preparing.wav") }
        let started = await Task.detached { Self.waitForSignal(entered) }.value
        XCTAssertTrue(started)
        guard started else { proceed.signal(); _ = try? await operation.value; return }
        XCTAssertTrue(engine.hasActiveOperations)
        let returned = expectation(description: "Shutdown waits for preparation cleanup")
        returned.isInverted = true
        let shutdown = Task { await engine.shutdown(); returned.fulfill() }
        await fulfillment(of: [returned], timeout: 0.05)
        XCTAssertTrue(engine.hasActiveOperations)
        proceed.signal()
        do { _ = try await operation.value; XCTFail("Shutdown must cancel a preparing operation") }
        catch { XCTAssertTrue(error is CancellationError) }
        await shutdown.value
        XCTAssertFalse(engine.hasActiveOperations)
        do { _ = try await engine.waveform(path: "/unavailable/after-shutdown.wav"); XCTFail("Closed clients must reject new work") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertFalse(engine.hasActiveOperations)
    }

    func testCancellationAfterNativeCompletionPreservesSuccessfulResult() async throws {
        guard let library = ProcessInfo.processInfo.environment["ENCAP_APP_LIBRARY"],
              FileManager.default.fileExists(atPath: library) else {
            throw XCTSkip("Set ENCAP_APP_LIBRARY to exercise native completion cancellation")
        }
        let completed = DispatchSemaphore(value: 0)
        let returnFromNative = DispatchSemaphore(value: 0)
        let engine = EngineClient()
        let task = Task {
            try await engine.linkedOperationForTesting(["build-info"]) { event in
                if event.event == "complete" {
                    completed.signal()
                    _ = Self.waitForSignal(returnFromNative)
                }
            }
        }
        let didComplete = await Task.detached { Self.waitForSignal(completed) }.value
        XCTAssertTrue(didComplete)
        task.cancel()
        returnFromNative.signal()
        let data = try await task.value
        let value = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertNotNil(value["encap_version"])
        XCTAssertTrue(task.isCancelled)
        await engine.drain()
        XCTAssertFalse(engine.hasActiveOperations)
    }

    func testTaskCancellationAwaitsLinkedWorkerCleanup() async throws {
        guard let library = ProcessInfo.processInfo.environment["ENCAP_APP_LIBRARY"],
              FileManager.default.fileExists(atPath: library) else {
            throw XCTSkip("Set ENCAP_APP_LIBRARY to exercise cooperative linked cancellation")
        }
        let engine = EngineClient()
        defer { engine.cleanupSession() }
        let task = Task { try await engine.waveform(path: "/nonexistent/cancelled-source.wav") }
        task.cancel()
        do { _ = try await task.value; XCTFail("A cancelled task must not return success") }
        catch { XCTAssertTrue(task.isCancelled) }
        await engine.drain()
        XCTAssertFalse(engine.hasActiveOperations)
        await engine.shutdown()
        XCTAssertFalse(engine.hasActiveOperations)
    }
}
