import AVIDTranscription
import Foundation
import NaturalLanguage
@preconcurrency import WhisperKit

/// Accepts either full Large-v3 or Turbo Core ML files from the verified cache.
/// Neither weights nor tokenizer loading may fall back to the network.
public actor WhisperKitProvider: TranscriptionProvider {
    public nonisolated let engineID = "whisperKit"
    public init() {}

    nonisolated static func prepareLanguage(_ value: String?) throws -> String? {
        guard let value else { return nil }
        let code = LanguageInput.baseCode(value)
        guard Constants.languageCodes.contains(code) else {
            throw TranscriptionError.unsupportedLanguage(value)
        }
        return code
    }

    nonisolated static func decodingOptions(language value: String?) throws -> DecodingOptions {
        let language = try prepareLanguage(value)
        return DecodingOptions(
            language: language, detectLanguage: language == nil,
            skipSpecialTokens: true, wordTimestamps: true, concurrentWorkerCount: 1
        )
    }

    public func transcribe(
        _ request: RecognitionRequest,
        progress: @escaping @Sendable (AVIDTranscription.TranscriptionProgress) -> Void
    ) async throws -> Transcript {
        try request.validate()
        try Task.checkCancellation()
        let options = try Self.decodingOptions(language: request.language)
        let language = options.language
        let tokenizerDirectory = request.modelDirectory.appendingPathComponent("tokenizer", isDirectory: true)
        try LocalModelFiles.require(["tokenizer.json", "tokenizer_config.json", "config.json"], in: tokenizerDirectory)
        try LocalModelFiles.require(["MelSpectrogram.mlmodelc", "AudioEncoder.mlmodelc", "TextDecoder.mlmodelc"], in: request.modelDirectory)
        progress(.init(stage: "Loading Whisper", fraction: 0))
        let pipeline = try await WhisperKit(WhisperKitConfig(
            modelFolder: request.modelDirectory.path,
            tokenizerFolder: tokenizerDirectory,
            verbose: false, prewarm: false, load: false, download: false
        ))
        do {
            // Upstream's tokenizer helper catches local errors and downloads a fallback.
            // Supply a fully local implementation before loading the model instead.
            pipeline.tokenizer = try LocalWhisperTokenizer(
                tokenizer: await AutoTokenizerWrapper.from(modelFolder: tokenizerDirectory)
            )
            pipeline.textDecoder.isModelMultilingual = true
            try await pipeline.loadModels()
            let audio = try await PCMChunkReader(url: request.audioURL)
            var segments: [TranscriptSegment] = []
            var detectedLanguage: String?
            while let chunk = try audio.next() {
                try Task.checkCancellation()
                let results = try await pipeline.transcribe(
                    audioArray: chunk.samples, decodeOptions: options,
                    callback: { _ in !Task.isCancelled }
                )
                for result in results {
                    detectedLanguage = detectedLanguage ?? result.language
                    for segment in result.segments {
                        let words = try (segment.words ?? []).map { word in
                            try TranscriptWord(
                                text: word.word.trimmingCharacters(in: .whitespacesAndNewlines),
                                startSeconds: Double(word.start) + chunk.start,
                                endSeconds: Double(word.end) + chunk.start,
                                confidence: Double(word.probability), timingMethod: .recognizer
                            )
                        }
                        if !segment.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && words.isEmpty {
                            throw TranscriptionError.missingWordTiming
                        }
                        segments.append(try TranscriptSegment(
                            text: segment.text.trimmingCharacters(in: .whitespacesAndNewlines), words: words,
                            startSeconds: Double(segment.start) + chunk.start,
                            endSeconds: Double(segment.end) + chunk.start
                        ))
                    }
                }
                let completed = chunk.start + Double(chunk.samples.count) / 16_000
                progress(.init(stage: "Transcribing", fraction: completed / audio.durationSeconds))
            }
            try Task.checkCancellation()
            let result = try Transcript(
                segments: segments, language: detectedLanguage ?? language,
                provenance: .init(engineID: engineID, modelID: request.modelID)
            ).offsettingTimes(by: request.sourceStartSeconds)
            await pipeline.unloadModels()
            return result
        } catch {
            await pipeline.unloadModels()
            throw error
        }
    }
}

// Word splitting is adapted from Argmax's MIT-licensed WhisperTokenizerWrapper.
// Copyright 2024 Argmax, Inc. See THIRD_PARTY_NOTICES.md in this package.
private struct LocalWhisperTokenizer: WhisperTokenizer {
    let tokenizer: TokenizerWrapper
    let specialTokens: SpecialTokens
    let allLanguageTokens: Set<Int>

    init(tokenizer: TokenizerWrapper) throws {
        self.tokenizer = tokenizer
        func token(_ text: String) throws -> Int {
            guard let id = tokenizer.convertTokenToId(text) else {
                throw TranscriptionError.unavailable("local Whisper tokenizer lacks \(text)")
            }
            return id
        }
        specialTokens = try SpecialTokens(
            endToken: token("<|endoftext|>"), englishToken: token("<|en|>"),
            noSpeechToken: token("<|nospeech|>"), noTimestampsToken: token("<|notimestamps|>"),
            specialTokenBegin: token("<|endoftext|>"), startOfPreviousToken: token("<|startofprev|>"),
            startOfTranscriptToken: token("<|startoftranscript|>"), timeTokenBegin: token("<|0.00|>"),
            transcribeToken: token("<|transcribe|>"), translateToken: token("<|translate|>"),
            whitespaceToken: tokenizer.convertTokenToId(" ") ?? 220
        )
        allLanguageTokens = Set(Constants.languages.values.compactMap { tokenizer.convertTokenToId("<|\($0)|>") })
    }

    func encode(text: String) -> [Int] { tokenizer.encode(text: text) }
    func decode(tokens: [Int]) -> String { tokenizer.decode(tokens: tokens) }
    func convertTokenToId(_ token: String) -> Int? { tokenizer.convertTokenToId(token) }
    func convertIdToToken(_ id: Int) -> String? { tokenizer.convertIdToToken(id) }

    func splitToWordTokens(tokenIds: [Int]) -> (words: [String], wordTokens: [[Int]]) {
        let text = decode(tokens: tokenIds.filter { $0 < specialTokens.specialTokenBegin })
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(text)
        let language = recognizer.dominantLanguage.flatMap { Locale(identifier: $0.rawValue).language.languageCode?.identifier }
        let separateUnicode = ["zh", "ja", "th", "lo", "my", "yue"].contains(language)
        var pieces: [(String, [Int])] = []
        var current: [Int] = []
        for id in tokenIds {
            current.append(id)
            let decoded = decode(tokens: current)
            // Byte-pair tokens can end halfway through a UTF-8 scalar.
            if !decoded.contains("\u{fffd}") || text.contains("\u{fffd}") {
                pieces.append((decoded, current))
                current = []
            }
        }
        if !current.isEmpty { pieces.append((decode(tokens: current), current)) }
        var words: [String] = []
        var tokens: [[Int]] = []
        for (piece, ids) in pieces {
            let punctuation = UnicodeScalar(piece.trimmingCharacters(in: .whitespaces))
                .map { CharacterSet.punctuationCharacters.contains($0) } ?? false
            if separateUnicode || words.isEmpty || piece.hasPrefix(" ") || punctuation || (ids.first ?? 0) >= specialTokens.specialTokenBegin {
                words.append(piece); tokens.append(ids)
            } else {
                words[words.count - 1] += piece
                tokens[tokens.count - 1].append(contentsOf: ids)
            }
        }
        return (words, tokens)
    }
}
