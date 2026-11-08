import AVIDTranscription
import Foundation
@preconcurrency import FluidAudio

public actor FluidAudioProvider: TranscriptionProvider {
    public enum Family: Sendable { case v3, ultra }
    public nonisolated let engineID = "fluidAudio"
    private let family: Family

    public init(family: Family = .v3) { self.family = family }

    nonisolated static func prepareLanguage(_ value: String?) throws -> String? {
        guard let value else { return nil }
        let code = LanguageInput.baseCode(value)
        let supported = Set(["bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk"])
        guard supported.contains(code) else { throw TranscriptionError.unsupportedLanguage(value) }
        return code
    }

    public func transcribe(
        _ request: RecognitionRequest,
        progress: @escaping @Sendable (AVIDTranscription.TranscriptionProgress) -> Void
    ) async throws -> Transcript {
        try request.validate()
        try Task.checkCancellation()
        let code = try Self.prepareLanguage(request.language)
        progress(.init(stage: "Loading Parakeet", fraction: 0))
        let models = try AsrModels.loadLocal(
            from: request.modelDirectory, version: family == .v3 ? .v3 : .ultra,
            encoderPrecision: family == .v3 ? .int8V2 : .int8
        )
        let manager = AsrManager(config: .default, models: models)
        return try await withModelCleanup(operation: {
            let reader = try await PCMChunkReader(url: request.audioURL)
            var state = try TdtDecoderState()
            var segments: [TranscriptSegment] = []
            while let chunk = try reader.next() {
                try Task.checkCancellation()
                let result = try await manager.transcribe(chunk.samples, decoderState: &state, language: code.flatMap(Language.init(rawValue:)))
                try Task.checkCancellation()
                let words = try buildWordTimings(from: result.tokenTimings ?? []).map { word in
                    try TranscriptWord(
                        text: word.word, startSeconds: word.startTime + chunk.start,
                        endSeconds: word.endTime + chunk.start, timingMethod: .recognizer
                    )
                }
                if !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && words.isEmpty {
                    throw TranscriptionError.missingWordTiming
                }
                let end = chunk.start + Double(chunk.samples.count) / 16_000
                segments.append(try TranscriptSegment(text: result.text, words: words, startSeconds: chunk.start, endSeconds: end))
                progress(.init(stage: "Transcribing", fraction: end / reader.durationSeconds))
            }
            progress(.init(stage: "Finished", fraction: 1))
            return try Transcript(
                segments: segments, language: code,
                provenance: .init(engineID: engineID, modelID: request.modelID)
            ).offsettingTimes(by: request.sourceStartSeconds)
        }, cleanup: {
            await manager.cleanup()
        })
    }
}
