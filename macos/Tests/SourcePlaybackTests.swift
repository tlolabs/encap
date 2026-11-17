import AVFoundation
import XCTest
@testable import EnCap

final class SourcePlaybackTests: XCTestCase {
    func testShuttleConventionAcrossPlatforms() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let cases = try String(contentsOf: root.appendingPathComponent("tests/fixtures/source-shuttle.tsv"))
        for line in cases.split(separator: "\n") where !line.hasPrefix("#") {
            let values = line.split(separator: " ").compactMap { Float($0) }
            XCTAssertEqual(values.count, 4)
            XCTAssertEqual(SourceShuttle.rate(current: values[0], direction: values[1], slow: values[2] != 0), values[3], String(line))
        }
    }

    @MainActor
    func testRealWAVPauseResumeReverseAndSwitch() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("encap-playback-\(UUID().uuidString).wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480000))
        buffer.frameLength = 480000
        buffer.floatChannelData?[0].initialize(repeating: 0, count: 480000)
        do { let file = try AVAudioFile(forWriting: url, settings: format.settings); try file.write(from: buffer) }
        let source = AudioSource(sourcePath: url.path, displayName: "Playback test", durationSeconds: 10)
        let store = AppStore()
        defer { store.stopPlayback() }
        store.play(source: source, at: 3)
        try await waitUntil { store.sourcePlaybackPosition > 3.05 }
        store.pauseSourcePlayback()
        let paused = store.sourcePlaybackPosition
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(store.sourcePlaybackPosition, paused, accuracy: 0.02)
        XCTAssertFalse(store.isPlaying(source: source))
        store.resumePlayback(source: source)
        try await waitUntil { store.sourcePlaybackPosition > paused + 0.05 }
        store.shuttle(source: source, direction: -1, slow: false)
        let reverseStart = store.sourcePlaybackPosition
        try await waitUntil { store.sourcePlaybackPosition < reverseStart - 0.05 }
        XCTAssertEqual(store.sourcePlaybackRate, -1)
        store.shuttle(source: source, direction: -1, slow: false)
        XCTAssertEqual(store.sourcePlaybackRate, -2)
        store.shuttle(source: source, direction: 1, slow: true)
        XCTAssertEqual(store.sourcePlaybackRate, 0.5)
        let other = AudioSource(sourcePath: "/missing.wav", displayName: "Other", durationSeconds: 1)
        store.resumePlayback(source: other)
        XCTAssertFalse(store.isPlaying(source: source))
        XCTAssertEqual(store.playingSourceID, other.id)
    }

    @MainActor
    func testVideoPlaybackReplacesAudioSessionAndRetainsChapterObservers() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let format = try XCTUnwrap(AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 1))
        let buffer = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480000))
        buffer.frameLength = 480000
        buffer.floatChannelData?[0].initialize(repeating: 0, count: 480000)
        let first = root.appendingPathComponent("first.wav")
        let second = root.appendingPathComponent("second.wav")
        for url in [first, second] {
            let file = try AVAudioFile(forWriting: url, settings: format.settings)
            try file.write(from: buffer)
        }
        let source = AudioSource(sourcePath: first.path, displayName: "First", durationSeconds: 10)
        var project = ProjectDocument()
        project.audioSources = [source,
            AudioSource(sourcePath: second.path, displayName: "Second", durationSeconds: 10)]
        project.chapters = [
            Chapter(id: "second", startTimeSeconds: 0, durationSeconds: 0.6, chapterNumber: 2, title: "Second"),
            Chapter(id: "first", startTimeSeconds: 0.6, durationSeconds: 0.6, chapterNumber: 1, title: "First")
        ]
        project.video.exportSettings.selectedChapterIds = ["second", "first"]
        project.video.exportSettings.selectionInitialized = true
        let store = AppStore()
        store.project = project
        defer { store.stopPlayback() }
        store.play(source: source, at: 3)
        try await waitUntil { store.sourcePlaybackPosition > 3.05 }
        XCTAssertEqual(store.playingSourceID, source.id)

        store.videoCurrentTime = 0.2
        store.toggleVideoPlayback()

        XCTAssertNil(store.playingSourceID)
        XCTAssertEqual(store.sourcePlaybackRate, 0)
        XCTAssertTrue(store.isVideoPlaying)
        try await waitUntil { store.videoCurrentTime > 0.3 }
        store.toggleVideoPlayback()
        let paused = store.videoCurrentTime
        try await Task.sleep(nanoseconds: 100_000_000)
        XCTAssertEqual(store.videoCurrentTime, paused, accuracy: 0.02)
        XCTAssertFalse(store.isVideoPlaying)
        store.toggleVideoPlayback()
        try await waitUntil { store.videoCurrentTime > 0.6 }
        try await waitUntil { !store.isVideoPlaying }
        XCTAssertEqual(store.videoCurrentTime, 1.2, accuracy: 0.02)
    }

    @MainActor
    private func waitUntil(_ condition: () -> Bool) async throws {
        for _ in 0..<100 {
            if condition() { return }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Playback did not reach the expected position within five seconds.")
    }
}
