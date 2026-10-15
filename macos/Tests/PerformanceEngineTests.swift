import Foundation
import XCTest
@testable import EnCap

final class PerformanceEngineTests: XCTestCase {
    func testProductionClientImportsPreviewsSavesAndReopensWithCurrentEngine() async throws {
        guard ProcessInfo.processInfo.environment["ENCAP_SOURCE_ROOT"] != nil else {
            throw XCTSkip("Set ENCAP_SOURCE_ROOT to exercise the locally built engine")
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let engine = EngineClient()
        defer { engine.cleanupSession(); try? FileManager.default.removeItem(at: root) }
        var wave = Data("RIFF".utf8)
        func append<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { wave.append(contentsOf: $0) }
        }
        append(UInt32(36 + 48000 * 2))
        wave.append(Data("WAVEfmt ".utf8))
        append(UInt32(16)); append(UInt16(1)); append(UInt16(1))
        append(UInt32(48000)); append(UInt32(96000)); append(UInt16(2)); append(UInt16(16))
        wave.append(Data("data".utf8)); append(UInt32(48000 * 2))
        for _ in 0..<48000 { append(Int16(-32768)) }
        let audio = root.appendingPathComponent("音声02.wav")
        try wave.write(to: audio)
        let project = try await engine.inspect(files: [audio])
        XCTAssertEqual(project.audioSources.count, 1)
        XCTAssertEqual(project.audioSources[0].durationSeconds, 1)
        let preview = try await engine.waveform(path: audio.path)
        XCTAssertEqual(preview.peaks, Array(repeating: 1.0, count: 64))
        let destination = root.appendingPathComponent("roundtrip.encap")
        _ = try await engine.save(project, to: destination)
        let reopened = try await engine.open(project: destination)
        XCTAssertEqual(reopened.audioSources.count, 1)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: reopened.audioSources[0].sourcePath)), wave)
        engine.cleanup(project: reopened)
    }
}
