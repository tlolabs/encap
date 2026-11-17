import AVIDTranscription
import Foundation
import Testing
@testable import EnCAPTranscription

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

@Test func segmentSubtitlesPreserveSpeakersAndBoundariesWithoutWordTiming() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: directory) }
    let input = Data(#"{"segments":[{"start_seconds":5,"end_seconds":6.5,"text":" Hello <world> & friends\nagain ","speaker":" Host "},{"start_seconds":7,"end_seconds":8,"text":" 世界! ","speaker":" "}]}"#.utf8)
    let file = directory.appendingPathComponent("segments.json")
    try input.write(to: file)
    let srt = try JSONDecoder().decode(String.self, from: await BridgeCommand.execute(
        ["subtitles", "--transcript", file.path, "--format", "srt"]))
    #expect(srt == "1\n00:00:05,000 --> 00:00:06,500\nHost: Hello &lt;world&gt; &amp; friends again\n\n2\n00:00:07,000 --> 00:00:08,000\n世界!\n")
    let vtt = try BridgeCommand.segmentSubtitles(input, format: "vtt")
    #expect(vtt == "WEBVTT\n\n00:00:05.000 --> 00:00:06.500\nHost: Hello &lt;world&gt; &amp; friends again\n\n00:00:07.000 --> 00:00:08.000\n世界!\n")
    #expect(try Data(contentsOf: file) == input)
}

@Test func segmentSubtitlesUseCoreValidationAndMillisecondQuantization() throws {
    for invalid in [
        #"{"segments":[{"start_seconds":1,"end_seconds":1,"text":"Legacy zero duration","speaker":""}]}"#,
        #"{"segments":[{"start_seconds":2,"end_seconds":3,"text":"First","speaker":""},{"start_seconds":0,"end_seconds":1,"text":"Unordered","speaker":""}]}"#,
    ] {
        #expect(throws: (any Error).self) {
            try BridgeCommand.segmentSubtitles(Data(invalid.utf8), format: "srt")
        }
    }
    let brief = Data(#"{"segments":[{"start_seconds":0.0001,"end_seconds":0.0002,"text":"Brief","speaker":""}]}"#.utf8)
    #expect(try BridgeCommand.segmentSubtitles(brief, format: "srt")
        == "1\n00:00:00,000 --> 00:00:00,001\nBrief\n")
    #expect(throws: (any Error).self) { try BridgeCommand.segmentSubtitles(brief, format: "txt") }
}

@Test func linkedABIRejectsInvalidHandlesSchemasAndCopiesOwnedBuffers() throws {
    #expect(transcriptionABIVersion() == 1)
    #expect(transcriptionCancel(0) == 0)
    #expect(transcriptionResultSize(0) == 0)
    let token = transcriptionTokenCreate()
    #expect(token != 0)
    defer { transcriptionRelease(token) }
    func invoke(_ token: UInt64, _ request: String) throws -> [String: Any] {
        let bytes = Array(request.utf8)
        let result = bytes.withUnsafeBufferPointer {
            transcriptionExecute(token, $0.baseAddress, $0.count, nil, nil)
        }
        #expect(result != 0)
        defer { transcriptionRelease(result) }
        let size = transcriptionResultSize(result)
        #expect(size > 0)
        var copied = [UInt8](repeating: 0, count: size)
        #expect(transcriptionResultCopy(result, nil, size) == 0)
        let success = copied.withUnsafeMutableBufferPointer {
            transcriptionResultCopy(result, $0.baseAddress, $0.count)
        }
        #expect(success == 1)
        return try #require(JSONSerialization.jsonObject(with: Data(copied)) as? [String: Any])
    }
    let invalid = try invoke(0, #"{"schema_version":1,"arguments":["status"]}"#)
    #expect((invalid["error"] as? [String: Any])?["code"] as? String == "invalid_handle")
    let wrongSchema = try invoke(token, #"{"schema_version":2,"arguments":["status"]}"#)
    #expect((wrongSchema["error"] as? [String: Any])?["code"] as? String == "invalid_request")
    #expect(transcriptionCancel(token) == 1)
    let cancelled = try invoke(token, #"{"schema_version":1,"arguments":["status"]}"#)
    #expect((cancelled["error"] as? [String: Any])?["code"] as? String == "cancelled")
}

@Test func wireKeepsVerifiedInstalledIdentityAndRuntimePinsAndLegacyUnknowns() throws {
    let descriptor = try ModelCatalog.bundled().model(id: "whisper-large-v3")
    let identity = try descriptor.provenanceIdentity()
    let revision = "9f99b5cb6a907730543823ad271b82532782a899"
    let original = try Transcript(segments: [.init(text: "Words")], provenance: .init(
        engineID: "whisperkit", modelID: descriptor.id, modelIdentity: identity,
        runtimeRevisions: ["whisperkit": revision], runtimeBuildSHA256: String(repeating: "a", count: 64)))
    let wire = TranscriptWire(original, recognitionProvenance: .init(original.provenance, descriptor: descriptor))
    let restored = try JSONDecoder().decode(TranscriptWire.self, from: BridgeCommand.encode(wire))
    #expect(restored.provenance.modelIdentity == identity)
    #expect(restored.provenance.runtimeRevisions == ["whisperkit": revision])
    #expect(try restored.core() == original)
    let legacy = #"{"segments":[{"text":"Old"}],"provenance":{"engine_id":"old","model_id":"old"}}"#
    let historic = try JSONDecoder().decode(TranscriptWire.self, from: Data(legacy.utf8))
    #expect(historic.provenance.modelIdentity == nil)
    #expect(historic.provenance.runtimeRevisions == nil)
    #expect(historic.provenance.sourceBundleSHA256 == nil)
}

private final class CallbackThreadProbe: @unchecked Sendable {
    var threads: [UInt64] = []
    var events: [Data] = []
}
@Test func progressQueueKeepsNewestEventsInOrderAcrossWrapAndDrain() {
    let probe = CallbackThreadProbe()
    let callback: TranscriptionEventCallback = { context, bytes, length in
        guard let context, let bytes else { return }
        let probe = Unmanaged<CallbackThreadProbe>.fromOpaque(context).takeUnretainedValue()
        probe.events.append(Data(bytes: bytes, count: length))
    }
    let delivery = ProgressDelivery(callback, Unmanaged.passUnretained(probe).toOpaque())
    let events = (0..<2500).map { Data(String($0).utf8) }
    for event in events { delivery.send(event) }
    delivery.drain()
    #expect(probe.events == Array(events.suffix(1024)))
    delivery.drain()
    #expect(probe.events.count == 1024)
    probe.events.removeAll()
    for event in events.prefix(3) { delivery.send(event) }
    delivery.drain()
    #expect(probe.events == Array(events.prefix(3)))
}
@Test func linkedProgressIsCopiedAndDeliveredOnTheExecutingHostWorker() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    defer { try? FileManager.default.removeItem(at: directory) }
    let input = directory.appendingPathComponent("empty.wav")
    try Data().write(to: input)
    let probe = CallbackThreadProbe()
    let expected = UInt64(pthread_mach_thread_np(pthread_self()))
    let callback: TranscriptionEventCallback = { context, bytes, length in
        guard let context, let bytes else { return }
        let probe = Unmanaged<CallbackThreadProbe>.fromOpaque(context).takeUnretainedValue()
        probe.threads.append(UInt64(pthread_mach_thread_np(pthread_self())))
        probe.events.append(Data(bytes: bytes, count: length))
    }
    let request: [String: Any] = ["schema_version": 1, "arguments": [
        "transcribe", "--input", input.path, "--model", "whisper-large-v3", "--cache", directory.appendingPathComponent("models").path,
    ]]
    let data = try JSONSerialization.data(withJSONObject: request)
    let token = transcriptionTokenCreate()
    defer { transcriptionRelease(token) }
    let result = data.withUnsafeBytes { bytes in
        transcriptionExecute(token, bytes.baseAddress?.assumingMemoryBound(to: UInt8.self), bytes.count,
            callback, Unmanaged.passUnretained(probe).toOpaque())
    }
    defer { transcriptionRelease(result) }
    #expect(!probe.events.isEmpty)
    #expect(probe.threads.allSatisfy { $0 == expected })
    #expect(String(decoding: probe.events[0], as: UTF8.self).contains("verifying"))
}
