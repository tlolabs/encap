import AVIDTranscription
import Foundation
@preconcurrency import MLX
@preconcurrency import MLXAudioSTT

public actor QwenASRProvider: TranscriptionProvider {
    public nonisolated let engineID = "mlx"
    public init() {}

    public func transcribe(
        _ request: RecognitionRequest,
        progress: @escaping @Sendable (AVIDTranscription.TranscriptionProgress) -> Void
    ) async throws -> Transcript {
        try request.validate()
        try Task.checkCancellation()
        let language = try QwenLanguages.recognitionName(request.language)
        progress(.init(stage: "Loading Qwen ASR", fraction: 0))
        let staged = try LocalModelFiles.stageQwen(request.modelDirectory)
        defer { try? FileManager.default.removeItem(at: staged) }
        let model = try await Qwen3ASRModel.fromModelDirectory(staged)
        try Task.checkCancellation()
        let reader = try await PCMChunkReader(url: request.audioURL)
        var segments: [TranscriptSegment] = []
        var detectedLanguage: String?
        while let chunk = try reader.next() {
            try Task.checkCancellation()
            var result: STTOutput?
            // Upstream's stream cancels its producer when the consumer terminates.
            for try await event in model.generateStream(
                audio: MLXArray(chunk.samples), maxTokens: 2048,
                language: language, chunkDuration: 30
            ) {
                try Task.checkCancellation()
                if case .result(let output) = event { result = output }
            }
            guard let result else { throw TranscriptionError.unavailable("Qwen returned no final transcription") }
            guard result.generationTokens < 2048 else {
                throw TranscriptionError.unavailable("Qwen reached its decode limit; retry with a shorter audio segment")
            }
            detectedLanguage = detectedLanguage ?? result.language
            let end = chunk.start + Double(chunk.samples.count) / 16_000
            if !result.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                // Chunk bounds identify the audio region; they are not word timing.
                segments.append(try TranscriptSegment(text: result.text, startSeconds: chunk.start, endSeconds: end))
            }
            progress(.init(stage: "Transcribing", fraction: end / reader.durationSeconds))
        }
        try Task.checkCancellation()
        return try QwenTranscriptOutput.recognized(
            segments: segments, detectedLanguage: detectedLanguage, request: request, engineID: engineID
        )
    }
}

/// Qwen alignment is a separate, optional model. Text recognition supports more
/// languages than this aligner; unsupported alignment must remain explicit.
public actor QwenAlignmentProvider: AlignmentProvider {
    public nonisolated let engineID = "mlx"
    public init() {}

    public func align(
        _ request: AlignmentRequest,
        progress: @escaping @Sendable (AVIDTranscription.TranscriptionProgress) -> Void
    ) async throws -> Transcript {
        try request.validate()
        try Task.checkCancellation()
        let language = try QwenLanguages.alignmentName(request.language ?? request.transcript.language)
        progress(.init(stage: "Loading Qwen aligner", fraction: 0))
        let staged = try LocalModelFiles.stageQwen(request.modelDirectory)
        defer { try? FileManager.default.removeItem(at: staged) }
        let model = try await Qwen3ForcedAlignerModel.fromModelDirectory(staged)
        var aligned: [TranscriptSegment] = []
        let segments = request.transcript.segments
        for (index, segment) in segments.enumerated() {
            try Task.checkCancellation()
            if segment.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                aligned.append(segment)
                continue
            }
            let start: Double
            let end: Double?
            if let segmentStart = segment.startSeconds, let segmentEnd = segment.endSeconds {
                start = segmentStart - request.sourceStartSeconds
                end = segmentEnd - request.sourceStartSeconds
            } else {
                guard segments.count == 1 else {
                    throw TranscriptionError.invalidInput("alignment of multiple segments requires audio bounds for each segment")
                }
                start = 0
                end = nil
            }
            let reader = try await PCMChunkReader(url: request.audioURL, startSeconds: start, endSeconds: end)
            guard reader.durationSeconds <= 240 else {
                throw TranscriptionError.invalidInput("alignment requires transcript segments no longer than 240 seconds")
            }
            guard let audio = try reader.next(maxSeconds: 240, preferPause: false) else {
                throw TranscriptionError.invalidInput("the segment contains no audio samples")
            }
            // This forward pass is synchronous; cancellation is honored before and
            // after the bounded segment rather than interrupting a Metal kernel.
            let result = model.generate(audio: MLXArray(audio.samples), text: segment.text, language: language)
            try Task.checkCancellation()
            guard !result.items.isEmpty else { throw TranscriptionError.missingWordTiming }
            let restored = try AlignmentText.restore(source: segment.text, items: result.items.map(\.text))
            let sourceOffset = start + request.sourceStartSeconds
            let words = try zip(result.items, restored).map { item, text in
                guard item.startTime >= 0, item.endTime <= reader.durationSeconds + 0.1 else {
                    throw TranscriptionError.invalidTimestamp("aligner returned a word outside its audio segment")
                }
                return try TranscriptWord(
                    text: text, startSeconds: item.startTime + sourceOffset,
                    endSeconds: item.endTime + sourceOffset, timingMethod: .forcedAlignment
                )
            }
            aligned.append(try TranscriptSegment(
                text: segment.text, words: words,
                startSeconds: segment.startSeconds ?? sourceOffset,
                endSeconds: segment.endSeconds ?? (sourceOffset + reader.durationSeconds)
            ))
            progress(.init(stage: "Aligning", fraction: Double(index + 1) / Double(max(1, segments.count))))
        }
        return try QwenTranscriptOutput.aligned(
            segments: aligned, request: request, engineID: engineID
        )
    }
}

enum QwenLanguages {
    static let names = [
        "zh": "Chinese", "en": "English", "yue": "Cantonese", "ar": "Arabic",
        "de": "German", "fr": "French", "es": "Spanish", "pt": "Portuguese",
        "id": "Indonesian", "it": "Italian", "ko": "Korean", "ru": "Russian",
        "th": "Thai", "vi": "Vietnamese", "ja": "Japanese", "tr": "Turkish",
        "hi": "Hindi", "ms": "Malay", "nl": "Dutch", "sv": "Swedish",
        "da": "Danish", "fi": "Finnish", "pl": "Polish", "cs": "Czech",
        "fil": "Filipino", "fa": "Persian", "el": "Greek", "hu": "Hungarian",
        "mk": "Macedonian", "ro": "Romanian",
    ]
    static let alignmentCodes: Set<String> = ["zh", "en", "yue", "fr", "de", "it", "ja", "ko", "pt", "ru", "es"]

    static func code(for value: String?) -> String? {
        guard let value else { return nil }
        let lower = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if let entry = names.first(where: { $0.value.lowercased() == lower }) { return entry.key }
        let code = LanguageInput.baseCode(value)
        return names[code] == nil ? nil : code
    }

    static func recognitionName(_ value: String?) throws -> String? {
        guard let value else { return nil }
        guard let code = code(for: value) else { throw TranscriptionError.unsupportedLanguage(value) }
        return names[code]
    }

    static func alignmentName(_ value: String?) throws -> String {
        guard let value else { throw TranscriptionError.invalidInput("alignment requires a language") }
        guard let code = code(for: value), alignmentCodes.contains(code), let name = names[code] else {
            throw TranscriptionError.unsupportedLanguage(value)
        }
        return name
    }
}

/// Build the persisted result with the same language selection used for inference.
enum QwenTranscriptOutput {
    static func recognized(
        segments: [TranscriptSegment], detectedLanguage: String?,
        request: RecognitionRequest, engineID: String
    ) throws -> Transcript {
        try Transcript(
            segments: segments,
            language: QwenLanguages.code(for: detectedLanguage) ?? QwenLanguages.code(for: request.language),
            provenance: .init(engineID: engineID, modelID: request.modelID)
        ).offsettingTimes(by: request.sourceStartSeconds)
    }

    static func aligned(
        segments: [TranscriptSegment], request: AlignmentRequest, engineID: String
    ) throws -> Transcript {
        let effectiveLanguage = try QwenLanguages.alignmentName(request.language ?? request.transcript.language)
        return try Transcript(
            segments: segments, language: QwenLanguages.code(for: effectiveLanguage),
            provenance: request.transcript.provenance,
            alignmentProvenance: .init(engineID: engineID, modelID: request.modelID)
        )
    }
}

enum AlignmentText {
    /// The model strips punctuation. Recover the original spelling, punctuation
    /// and inter-word text without silently accepting omitted source words.
    static func restore(source: String, items: [String]) throws -> [String] {
        guard !items.isEmpty else { throw TranscriptionError.missingWordTiming }
        // Match the aligner's exact cleaning rule while retaining original
        // indices. This handles edited curly apostrophes and number separators.
        let kept = source.indices.compactMap { index -> (Character, String.Index)? in
            let character = source[index]
            return character.isLetter || character.isNumber || character == "'" ? (character, index) : nil
        }
        var cursor = 0
        var matches: [Range<String.Index>] = []
        for item in items {
            let characters = Array(item)
            guard !characters.isEmpty, cursor + characters.count <= kept.count,
                  zip(characters, kept[cursor..<(cursor + characters.count)]).allSatisfy({ $0.0 == $0.1.0 }) else {
                throw TranscriptionError.invalidInput("aligner word sequence does not match the corrected transcript")
            }
            let start = kept[cursor].1
            cursor += characters.count
            let end = source.index(after: kept[cursor - 1].1)
            matches.append(start..<end)
        }
        guard cursor == kept.count else { throw TranscriptionError.missingWordTiming }
        return matches.indices.map { index in
            let start = index == 0 ? source.startIndex : matches[index].lowerBound
            let end = index + 1 < matches.count ? matches[index + 1].lowerBound : source.endIndex
            return String(source[start..<end]).trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
}
