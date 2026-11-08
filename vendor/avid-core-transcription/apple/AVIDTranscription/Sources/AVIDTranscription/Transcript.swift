import Foundation

public enum TranscriptionError: Error, Equatable, Sendable, LocalizedError {
    case invalidTimestamp(String)
    case invalidConfidence
    case invalidInput(String)
    case missingWordTiming
    case unsupportedLanguage(String)
    case unavailable(String)
    case invalidCaptionOptions(String)

    public var errorDescription: String? {
        switch self {
        case .invalidTimestamp(let reason): "Invalid timestamp: \(reason)"
        case .invalidConfidence: "Word confidence must be finite and between zero and one."
        case .invalidInput(let reason): "Invalid input: \(reason)"
        case .missingWordTiming: "Word timing is unavailable. Align the transcript before creating captions."
        case .unsupportedLanguage(let language): "The selected model does not support \(language)."
        case .unavailable(let reason): "Transcription is unavailable: \(reason)"
        case .invalidCaptionOptions(let reason): "Invalid caption settings: \(reason)"
        }
    }
}

public struct TranscriptProvenance: Codable, Equatable, Sendable {
    public let engineID: String
    public let modelID: String

    public init(engineID: String, modelID: String) {
        self.engineID = engineID
        self.modelID = modelID
    }
}

/// Describes how a word was timed, independently of how its text was recognized.
public enum TimingMethod: String, Codable, Sendable {
    case recognizer
    case forcedAlignment
    case manual
    case estimated
}

func validateTimestampPair(_ start: Double?, _ end: Double?) throws {
    switch (start, end) {
    case (nil, nil): return
    case (.some(let start), .some(let end)):
        guard start.isFinite, end.isFinite, start >= 0, end >= start else {
            throw TranscriptionError.invalidTimestamp("times must be finite, nonnegative, and ordered")
        }
    default:
        throw TranscriptionError.invalidTimestamp("start and end must either both be present or both be absent")
    }
}

/// Times are seconds on the original source audio's clock, never caption-layout time.
public struct TranscriptWord: Codable, Equatable, Sendable {
    public let text: String
    public let startSeconds: Double?
    public let endSeconds: Double?
    public let confidence: Double?
    public let timingMethod: TimingMethod?

    public init(
        text: String,
        startSeconds: Double? = nil,
        endSeconds: Double? = nil,
        confidence: Double? = nil,
        timingMethod: TimingMethod? = nil
    ) throws {
        try validateTimestampPair(startSeconds, endSeconds)
        if let confidence, !confidence.isFinite || !(0...1).contains(confidence) {
            throw TranscriptionError.invalidConfidence
        }
        self.text = text
        self.startSeconds = startSeconds
        self.endSeconds = endSeconds
        self.confidence = confidence
        self.timingMethod = startSeconds == nil ? nil : (timingMethod ?? .recognizer)
    }

    private enum CodingKeys: String, CodingKey {
        case text, startSeconds, endSeconds, confidence, timingMethod
    }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            text: container.decode(String.self, forKey: .text),
            startSeconds: container.decodeIfPresent(Double.self, forKey: .startSeconds),
            endSeconds: container.decodeIfPresent(Double.self, forKey: .endSeconds),
            confidence: container.decodeIfPresent(Double.self, forKey: .confidence),
            timingMethod: container.decodeIfPresent(TimingMethod.self, forKey: .timingMethod)
        )
    }
}

public struct TranscriptSegment: Codable, Equatable, Sendable {
    public let text: String
    public let words: [TranscriptWord]
    public let startSeconds: Double?
    public let endSeconds: Double?

    public init(
        text: String,
        words: [TranscriptWord] = [],
        startSeconds: Double? = nil,
        endSeconds: Double? = nil
    ) throws {
        try validateTimestampPair(startSeconds, endSeconds)
        self.text = text
        self.words = words
        self.startSeconds = startSeconds
        self.endSeconds = endSeconds
    }

    /// Text corrections invalidate word alignment. A separate alignment operation can restore it.
    public func replacingText(with text: String) throws -> TranscriptSegment {
        try TranscriptSegment(text: text, startSeconds: startSeconds, endSeconds: endSeconds)
    }

    private enum CodingKeys: String, CodingKey { case text, words, startSeconds, endSeconds }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            text: container.decode(String.self, forKey: .text),
            words: container.decodeIfPresent([TranscriptWord].self, forKey: .words) ?? [],
            startSeconds: container.decodeIfPresent(Double.self, forKey: .startSeconds),
            endSeconds: container.decodeIfPresent(Double.self, forKey: .endSeconds)
        )
    }
}

public struct Transcript: Codable, Equatable, Sendable {
    public let segments: [TranscriptSegment]
    public let language: String?
    public let provenance: TranscriptProvenance
    public let alignmentProvenance: TranscriptProvenance?

    public init(
        segments: [TranscriptSegment],
        language: String? = nil,
        provenance: TranscriptProvenance,
        alignmentProvenance: TranscriptProvenance? = nil
    ) throws {
        self.segments = segments
        self.language = language
        self.provenance = provenance
        self.alignmentProvenance = alignmentProvenance
    }

    public var text: String { segments.map(\.text).joined(separator: "\n") }

    public var hasCompleteWordTiming: Bool {
        segments.allSatisfy { segment in
            if segment.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return true }
            return !segment.words.isEmpty && segment.words.allSatisfy {
                $0.startSeconds != nil && $0.endSeconds != nil
            }
        }
    }

    /// Use exactly once when converting engine-local times for an extracted audio clip.
    public func offsettingTimes(by offset: Double) throws -> Transcript {
        guard offset.isFinite else {
            throw TranscriptionError.invalidTimestamp("offset must be finite")
        }
        let adjusted = try segments.map { segment in
            let words = try segment.words.map { word in
                try TranscriptWord(
                    text: word.text,
                    startSeconds: word.startSeconds.map { $0 + offset },
                    endSeconds: word.endSeconds.map { $0 + offset },
                    confidence: word.confidence,
                    timingMethod: word.timingMethod
                )
            }
            return try TranscriptSegment(
                text: segment.text, words: words,
                startSeconds: segment.startSeconds.map { $0 + offset },
                endSeconds: segment.endSeconds.map { $0 + offset }
            )
        }
        return try Transcript(
            segments: adjusted, language: language, provenance: provenance,
            alignmentProvenance: alignmentProvenance
        )
    }

    public func correctingSegment(at index: Int, text: String) throws -> Transcript {
        guard segments.indices.contains(index) else {
            throw TranscriptionError.invalidInput("segment index is out of range")
        }
        var updated = segments
        updated[index] = try updated[index].replacingText(with: text)
        return try Transcript(segments: updated, language: language, provenance: provenance)
    }
}
