import AVIDTranscription
@preconcurrency import AVFoundation
import Foundation
import Testing
@testable import AVIDTranscriptionEngines

@Test func alignmentRetainsEditedTextAndPunctuation() throws {
    #expect(try AlignmentText.restore(source: "\"Hello, world!\"", items: ["Hello", "world"]) == ["\"Hello,", "world!\""])
    #expect(try AlignmentText.restore(source: "Don’t stop—now!", items: ["Dont", "stopnow"]) == ["Don’t", "stop—now!"])
    #expect(try AlignmentText.restore(source: "Save 1,000 dollars.", items: ["Save", "1000", "dollars"]) == ["Save", "1,000", "dollars."])
    #expect(throws: (any Error).self) {
        try AlignmentText.restore(source: "Hello missing world", items: ["Hello", "world"])
    }
}

@Test func alignmentLanguageIsMoreRestrictedThanRecognition() throws {
    #expect(try QwenLanguages.recognitionName("ar") == "Arabic")
    #expect(throws: TranscriptionError.unsupportedLanguage("ar")) { try QwenLanguages.alignmentName("ar") }
    #expect(try QwenLanguages.alignmentName("en-US") == "English")
}

@Test func missingLocalModelsFailWithoutDownloads() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    #expect(throws: (any Error).self) { try LocalModelFiles.require(["config.json"], in: directory) }
}

@Test func decodesRealStereoRecordingIntoBoundedMonoWindows() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("stereo.wav")
    let format = try #require(AVAudioFormat(standardFormatWithSampleRate: 48_000, channels: 2))
    let buffer = try #require(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 96_000))
    buffer.frameLength = 96_000
    let channels = try #require(buffer.floatChannelData)
    for frame in 0..<96_000 {
        let value = Float(sin(Double(frame) * 2 * .pi * 440 / 48_000)) * 0.25
        channels[0][frame] = value
        channels[1][frame] = value
    }
    do {
        var settings = format.settings
        settings[AVLinearPCMIsNonInterleaved] = false
        let file = try AVAudioFile(forWriting: url, settings: settings)
        try file.write(from: buffer)
    }
    let reader = try await PCMChunkReader(url: url)
    let first = try #require(try reader.next(maxSeconds: 1, preferPause: false))
    let second = try #require(try reader.next(maxSeconds: 1, preferPause: false))
    #expect(first.samples.count == 16_000)
    // AVFoundation's resampler can trim its filter tail by a few frames.
    #expect(abs(second.samples.count - 16_000) <= 16)
    #expect(first.start == 0)
    #expect(second.start == 1)
    #expect(first.samples.contains { abs($0) > 0.1 })
    #expect(try reader.next(maxSeconds: 1, preferPause: false) == nil)
}

@Test func qwenStagingExcludesUnlistedWeightsAndPreservesCache() throws {
    let source = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: source) }
    for name in ["config.json", "tokenizer_config.json", "vocab.json", "merges.txt", "model.safetensors", "evil.safetensors", "tokenizer.json"] {
        try Data("fixture".utf8).write(to: source.appendingPathComponent(name))
    }
    let staged = try LocalModelFiles.stageQwen(source)
    defer { try? FileManager.default.removeItem(at: staged) }
    #expect(!FileManager.default.fileExists(atPath: staged.appendingPathComponent("evil.safetensors").path))
    #expect(!FileManager.default.fileExists(atPath: staged.appendingPathComponent("tokenizer.json").path))
    try Data("generated".utf8).write(to: staged.appendingPathComponent("tokenizer.json"))
    #expect(try String(contentsOf: source.appendingPathComponent("tokenizer.json"), encoding: .utf8) == "fixture")
}

@Test func movieAudioKeepsItsLeadingTimelineGap() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("delayed-audio.mov")
    let format = try #require(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: true))
    let pcm = try #require(AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 32_000))
    pcm.frameLength = 32_000
    let samples = try #require(pcm.floatChannelData)
    for index in 0..<32_000 { samples[0][index] = 0.25 }
    var timing = CMSampleTimingInfo(duration: CMTime(value: 1, timescale: 16_000), presentationTimeStamp: CMTime(seconds: 1, preferredTimescale: 16_000), decodeTimeStamp: .invalid)
    var sample: CMSampleBuffer?
    #expect(CMSampleBufferCreate(
        allocator: kCFAllocatorDefault, dataBuffer: nil, dataReady: false,
        makeDataReadyCallback: nil, refcon: nil, formatDescription: format.formatDescription,
        sampleCount: 32_000, sampleTimingEntryCount: 1, sampleTimingArray: &timing,
        sampleSizeEntryCount: 0, sampleSizeArray: nil, sampleBufferOut: &sample
    ) == noErr)
    let buffer = try #require(sample)
    #expect(CMSampleBufferSetDataBufferFromAudioBufferList(
        buffer, blockBufferAllocator: kCFAllocatorDefault, blockBufferMemoryAllocator: kCFAllocatorDefault,
        flags: 0, bufferList: pcm.audioBufferList
    ) == noErr)
    #expect(CMSampleBufferSetDataReady(buffer) == noErr)
    let writer = try AVAssetWriter(outputURL: url, fileType: .mov)
    var settings = format.settings
    settings[AVLinearPCMIsNonInterleaved] = false
    let input = AVAssetWriterInput(mediaType: .audio, outputSettings: settings)
    writer.add(input)
    #expect(writer.startWriting())
    writer.startSession(atSourceTime: .zero)
    #expect(input.append(buffer))
    input.markAsFinished()
    await writer.finishWriting()
    #expect(writer.status == .completed)
    let reader = try await PCMChunkReader(url: url)
    let leading = try #require(try reader.next(maxSeconds: 1, preferPause: false))
    let speech = try #require(try reader.next(maxSeconds: 1, preferPause: false))
    #expect(leading.start == 0)
    #expect(leading.samples.count == 16_000)
    #expect(leading.samples.allSatisfy { abs($0) < 0.001 })
    #expect(speech.start == 1)
    #expect(speech.samples.contains { abs($0) > 0.1 })
}

@Test func providerInputsNormalizeRegionalLanguageTags() throws {
    for (input, code, name) in [
        ("pt-BR", "pt", "Portuguese"), ("pt_BR", "pt", "Portuguese"),
        ("en-US", "en", "English"), ("EN_us", "en", "English"),
        ("  PT_br\n", "pt", "Portuguese"),
    ] {
        #expect(try WhisperKitProvider.prepareLanguage(input) == code)
        #expect(try WhisperKitProvider.decodingOptions(language: input).language == code)
        #expect(try FluidAudioProvider.prepareLanguage(input) == code)
        #expect(try QwenLanguages.recognitionName(input) == name)
        #expect(try QwenLanguages.alignmentName(input) == name)
        #expect(QwenLanguages.code(for: input) == code)
    }
    #expect(try WhisperKitProvider.prepareLanguage(nil) == nil)
    #expect(try FluidAudioProvider.prepareLanguage(nil) == nil)
    #expect(try QwenLanguages.recognitionName(nil) == nil)
    #expect(try QwenLanguages.recognitionName(" Portuguese ") == "Portuguese")
}

@Test func whisperDetectsLanguageOnlyWhenNoLanguageIsSelected() throws {
    let automatic = try WhisperKitProvider.decodingOptions(language: nil)
    #expect(automatic.language == nil)
    #expect(automatic.detectLanguage)
    let selected = try WhisperKitProvider.decodingOptions(language: "pt-BR")
    #expect(selected.language == "pt")
    #expect(!selected.detectLanguage)
    #expect(selected.wordTimestamps)
    #expect(selected.skipSpecialTokens)
}

@Test func unsupportedProviderLanguagesFailBeforeLoadingModels() async throws {
    let missing = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    let request = RecognitionRequest(
        audioURL: missing.appendingPathComponent("recording.wav"), modelID: "fixture",
        modelDirectory: missing, language: "xx-ZZ"
    )
    let providers: [any TranscriptionProvider] = [WhisperKitProvider(), FluidAudioProvider(), QwenASRProvider()]
    for provider in providers {
        do {
            _ = try await provider.transcribe(request, progress: { _ in })
            Issue.record("Unsupported explicit language was accepted by \(provider.engineID)")
        } catch let error as TranscriptionError {
            #expect(error == .unsupportedLanguage("xx-ZZ"))
        }
    }
}

private actor CleanupEvents {
    private(set) var values: [String] = []
    func append(_ value: String) { values.append(value) }
}

private enum OperationFailure: Error, Equatable { case failed }

@Test func modelCleanupIsAwaitedBeforeSuccessReturns() async {
    let events = CleanupEvents()
    let result = await withModelCleanup(operation: {
        await events.append("operation")
        return 7
    }, cleanup: {
        await events.append("cleanup-start")
        await Task.yield()
        await events.append("cleanup-end")
    })
    #expect(result == 7)
    #expect(await events.values == ["operation", "cleanup-start", "cleanup-end"])
}

@Test func modelCleanupIsAwaitedAndPreservesOperationError() async throws {
    let events = CleanupEvents()
    do {
        let _: Int = try await withModelCleanup(operation: {
            throw OperationFailure.failed
        }, cleanup: {
            await events.append("cleanup-start")
            await Task.yield()
            await events.append("cleanup-end")
        })
        Issue.record("The original operation error was swallowed")
    } catch let error as OperationFailure {
        #expect(error == .failed)
    }
    #expect(await events.values == ["cleanup-start", "cleanup-end"])
}

@Test func modelCleanupIsAwaitedOnCancellation() async throws {
    let events = CleanupEvents()
    let task = Task {
        try await withModelCleanup(operation: {
            while !Task.isCancelled { await Task.yield() }
            try Task.checkCancellation()
        }, cleanup: {
            await events.append("cleanup-start")
            await Task.yield()
            await events.append("cleanup-end")
        })
    }
    task.cancel()
    do {
        try await task.value
        Issue.record("Cancellation was swallowed")
    } catch is CancellationError { }
    #expect(await events.values == ["cleanup-start", "cleanup-end"])
}

@Test func alignedQwenTranscriptPersistsSelectedLanguageAndProvenance() throws {
    let originalProvenance = TranscriptProvenance(engineID: "fixture", modelID: "original-recognizer")
    let originalSegment = try TranscriptSegment(text: "Hello.", startSeconds: 0, endSeconds: 1)
    let alignedSegment = try TranscriptSegment(text: "Hello.", words: [
        TranscriptWord(text: "Hello.", startSeconds: 0, endSeconds: 0.5, timingMethod: .forcedAlignment)
    ], startSeconds: 0, endSeconds: 1)
    let directory = FileManager.default.temporaryDirectory
    for (originalLanguage, override, expected) in [
        (nil as String?, "EN_us" as String?, "en"),
        ("pt", "EN_us", "en"),
        ("pt_BR", nil, "pt"),
    ] {
        let original = try Transcript(segments: [originalSegment], language: originalLanguage, provenance: originalProvenance)
        let request = AlignmentRequest(
            audioURL: directory.appendingPathComponent("fixture.wav"), modelID: "aligner",
            modelDirectory: directory, transcript: original, language: override
        )
        let result = try QwenTranscriptOutput.aligned(segments: [alignedSegment], request: request, engineID: "mlx")
        #expect(result.language == expected)
        #expect(result.text == original.text)
        #expect(result.provenance == originalProvenance)
        #expect(result.alignmentProvenance == .init(engineID: "mlx", modelID: "aligner"))
        #expect(result.hasCompleteWordTiming)
    }
}

@Test func recognizedQwenTranscriptNormalizesFallbackLanguageMetadata() throws {
    let directory = FileManager.default.temporaryDirectory
    let request = RecognitionRequest(
        audioURL: directory.appendingPathComponent("fixture.wav"), modelID: "recognizer",
        modelDirectory: directory, language: "PT_br", sourceStartSeconds: 12.5
    )
    let segment = try TranscriptSegment(text: "Hello.", startSeconds: 0, endSeconds: 1)
    let result = try QwenTranscriptOutput.recognized(segments: [segment], detectedLanguage: nil, request: request, engineID: "mlx")
    #expect(result.language == "pt")
    #expect(result.text == "Hello.")
    #expect(result.provenance == .init(engineID: "mlx", modelID: "recognizer"))
    #expect(result.segments.first?.startSeconds == 12.5)
    let detected = try QwenTranscriptOutput.recognized(segments: [segment], detectedLanguage: "English", request: request, engineID: "mlx")
    #expect(detected.language == "en")
}
