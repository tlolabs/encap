import AVIDTranscription
import Foundation
import Testing
@testable import AVIDTranscriber

@Test func transcriptWireRetainsSourceTimesAndIndependentProvenance() throws {
    let original = try Transcript(segments: [
        .init(text: "Hello, 世界!", words: [
            .init(text: "Hello,", startSeconds: 12.5, endSeconds: 12.9, confidence: 0.8, timingMethod: .forcedAlignment),
            .init(text: "世界!", startSeconds: 13, endSeconds: 13.5, timingMethod: .forcedAlignment),
        ], startSeconds: 12.5, endSeconds: 13.5),
    ], language: "en", provenance: .init(engineID: "mlx", modelID: "recognizer"),
       alignmentProvenance: .init(engineID: "mlx", modelID: "aligner"))
    let data = try BridgeCommand.encode(TranscriptWire(original))
    let json = String(decoding: data, as: UTF8.self)
    #expect(json.contains("\"start_seconds\":12.5"))
    #expect(json.contains("\"engine_id\":\"mlx\""))
    #expect(!json.contains("startSeconds"))
    #expect(try JSONDecoder().decode(TranscriptWire.self, from: data).core() == original)
    let preserved = TranscriptWire(original, recognitionSegments: [try .init(text: "Original recognition")])
    let preservedJSON = try BridgeCommand.encode(preserved)
    let restored = try JSONDecoder().decode(TranscriptWire.self, from: preservedJSON)
    #expect(restored.recognitionSegments?.first?.text == "Original recognition")
    #expect(try restored.core() == original)
    let descriptor = try ModelCatalog.bundled().model(id: "whisper-large-v3")
    let identity = TranscriptWire.Provenance(original.provenance, descriptor: descriptor)
    let enriched = TranscriptWire(original, recognitionProvenance: identity)
    let enrichedData = try BridgeCommand.encode(enriched)
    let enrichedRestored = try JSONDecoder().decode(TranscriptWire.self, from: enrichedData)
    #expect(enrichedRestored.provenance.modelInstallationID == descriptor.installationID)
    #expect(enrichedRestored.provenance.sourceBundleSHA256 == SharedSource.bundleSHA256)
    #expect(try enrichedRestored.core() == original)
}

@Test func untimedTextHasNoFabricatedWordsOrTimes() throws {
    let original = try Transcript(segments: [.init(text: "Text without alignment")],
        provenance: .init(engineID: "mlx", modelID: "qwen3-asr-1.7b-4bit"))
    let wire = TranscriptWire(original)
    #expect(wire.segments[0].words == [])
    #expect(wire.segments[0].startSeconds == nil)
    #expect(try wire.core() == original)
}

@Test func malformedTimingIsRejectedWhenReadingRealignmentInput() throws {
    let json = """
    {"segments":[{"text":"bad","start_seconds":2,"end_seconds":1}],
     "provenance":{"engine_id":"test","model_id":"test"}}
    """
    let wire = try JSONDecoder().decode(TranscriptWire.self, from: Data(json.utf8))
    #expect(throws: (any Error).self) { try wire.core() }
}

@Test func optionsRejectAmbiguousOrUnsupportedInput() throws {
    for arguments in [["transcribe", "--input"], ["models", "--model", "anything"],
                      ["transcribe", "--source-offset", "nan"], ["transcribe", "--source-offset", "-1"],
                      ["transcribe", "--model", "one", "--model", "two"], ["unknown"]] {
        #expect(throws: (any Error).self) { try Options(arguments) }
    }
    let options = try Options(["transcribe", "--input", "/tmp/space;$(test) 'quoted'.wav", "--source-offset", "12.5"])
    #expect(options["--input"] == "/tmp/space;$(test) 'quoted'.wav")
    #expect(options.offset == 12.5)
}

@Test func languageValidationDoesNotConfuseRecognitionAndAlignment() throws {
    try BridgeCommand.validateLanguage(" EN_us ", supported: ["en"])
    #expect(throws: (any Error).self) {
        try BridgeCommand.validateLanguage("fil", supported: ["en", "fr"])
    }
}

@Test func modelsProtocolUsesSharedCatalogAndExplicitInstallState() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let data = try await BridgeCommand.execute(["models", "--cache", directory.path])
    let models = try #require(JSONSerialization.jsonObject(with: data) as? [[String: Any]])
    #expect(models.count == 5)
    let quality = try #require(models.first { $0["id"] as? String == "whisper-large-v3" })
    #expect(quality["is_default"] as? Bool == true)
    #expect(quality["download_size_bytes"] as? Int64 == 3_093_084_631)
    #expect(quality["installation_state"] as? String == "missing")
    #expect(quality["installed"] as? Bool == false)
    #expect(models.filter { $0["role"] as? String == "aligner" }.count == 1)
}

@Test func captionsUseSharedGroupingWithoutMutatingRecognition() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: directory) }
    let transcript = try Transcript(segments: [.init(text: "Hello, world!", words: [
        .init(text: "Hello,", startSeconds: 5, endSeconds: 5.4),
        .init(text: "world!", startSeconds: 5.5, endSeconds: 6),
    ])], language: "en", provenance: .init(engineID: "test", modelID: "test"))
    let file = directory.appendingPathComponent("record.json")
    let original = try BridgeCommand.encode(TranscriptWire(transcript))
    try original.write(to: file)
    for format in ["srt", "vtt"] {
        let data = try await BridgeCommand.execute(["captions", "--transcript", file.path, "--format", format])
        let output = try JSONDecoder().decode(String.self, from: data)
        #expect(output.contains("Hello, world!"))
        #expect(output.contains(format == "srt" ? "00:00:05,000 --> 00:00:06,000" : "00:00:05.000 --> 00:00:06.000"))
    }
    #expect(try Data(contentsOf: file) == original)
    try BridgeCommand.encode(TranscriptWire(try Transcript(segments: [.init(text: "No alignment")],
        provenance: .init(engineID: "test", modelID: "test")))).write(to: file)
    await #expect(throws: TranscriptionError.missingWordTiming) {
        try await BridgeCommand.execute(["captions", "--transcript", file.path, "--format", "vtt"])
    }
}
