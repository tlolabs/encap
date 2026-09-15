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
    private func waitUntil(_ condition: () -> Bool) async throws {
        for _ in 0..<100 {
            if condition() { return }
            try await Task.sleep(nanoseconds: 50_000_000)
        }
        XCTFail("Playback did not reach the expected position within five seconds.")
    }
}
