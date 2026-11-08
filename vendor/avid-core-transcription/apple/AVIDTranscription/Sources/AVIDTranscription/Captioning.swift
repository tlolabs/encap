import Foundation

public struct CaptionOptions: Equatable, Sendable {
    public let maximumCharacters: Int
    public let maximumWords: Int
    public let maximumDurationSeconds: Double
    public let maximumPauseSeconds: Double

    public init(
        maximumCharacters: Int = 42, maximumWords: Int = 6,
        maximumDurationSeconds: Double = 3, maximumPauseSeconds: Double = 0.6
    ) {
        self.maximumCharacters = maximumCharacters
        self.maximumWords = maximumWords
        self.maximumDurationSeconds = maximumDurationSeconds
        self.maximumPauseSeconds = maximumPauseSeconds
    }
}

/// A non-destructive source trim placed at an offset on an output timeline.
public struct CaptionWindow: Equatable, Sendable {
    public let sourceStartSeconds: Double
    public let sourceEndSeconds: Double?
    public let timelineStartSeconds: Double

    public init(
        sourceStartSeconds: Double = 0, sourceEndSeconds: Double? = nil,
        timelineStartSeconds: Double = 0
    ) {
        self.sourceStartSeconds = sourceStartSeconds
        self.sourceEndSeconds = sourceEndSeconds
        self.timelineStartSeconds = timelineStartSeconds
    }
}

/// Cue and word times use the output timeline. Original transcript times remain unchanged.
public struct CaptionCue: Codable, Equatable, Sendable {
    public let startSeconds: Double
    public let endSeconds: Double
    public let text: String
    public let words: [TranscriptWord]

    public init(
        startSeconds: Double, endSeconds: Double, text: String, words: [TranscriptWord] = []
    ) throws {
        try validateTimestampPair(startSeconds, endSeconds)
        guard endSeconds > startSeconds else {
            throw TranscriptionError.invalidTimestamp("caption duration must be positive")
        }
        self.startSeconds = startSeconds
        self.endSeconds = endSeconds
        self.text = text
        self.words = words
    }

    private enum CodingKeys: String, CodingKey { case startSeconds, endSeconds, text, words }

    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(
            startSeconds: container.decode(Double.self, forKey: .startSeconds),
            endSeconds: container.decode(Double.self, forKey: .endSeconds),
            text: container.decode(String.self, forKey: .text),
            words: container.decodeIfPresent([TranscriptWord].self, forKey: .words) ?? []
        )
    }
}

public enum CaptionBuilder {
    public static func cues(
        from transcript: Transcript,
        options: CaptionOptions = CaptionOptions(),
        window: CaptionWindow = CaptionWindow()
    ) throws -> [CaptionCue] {
        guard options.maximumCharacters > 0, options.maximumWords > 0,
              options.maximumDurationSeconds.isFinite, options.maximumDurationSeconds > 0,
              options.maximumPauseSeconds.isFinite, options.maximumPauseSeconds >= 0 else {
            throw TranscriptionError.invalidCaptionOptions("limits must be positive and finite; pause may be zero")
        }
        try validateTimestampPair(window.sourceStartSeconds, window.sourceEndSeconds ?? window.sourceStartSeconds)
        guard window.timelineStartSeconds.isFinite, window.timelineStartSeconds >= 0 else {
            throw TranscriptionError.invalidTimestamp("timeline offset must be finite and nonnegative")
        }
        guard transcript.hasCompleteWordTiming else { throw TranscriptionError.missingWordTiming }

        var words: [TranscriptWord] = []
        var lastSourceStart: Double?
        for word in transcript.segments.flatMap(\.words) {
            guard let start = word.startSeconds, let end = word.endSeconds else {
                throw TranscriptionError.missingWordTiming
            }
            if let lastSourceStart, start < lastSourceStart {
                throw TranscriptionError.invalidTimestamp("words must be ordered by source start time")
            }
            lastSourceStart = start
            guard !word.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
            let trimEnd = window.sourceEndSeconds ?? .infinity
            guard end >= window.sourceStartSeconds, start < trimEnd,
                  !(end == window.sourceStartSeconds && start < end) else { continue }
            let clippedStart = max(start, window.sourceStartSeconds)
            let clippedEnd = min(end, trimEnd)
            words.append(try TranscriptWord(
                text: word.text,
                startSeconds: clippedStart - window.sourceStartSeconds + window.timelineStartSeconds,
                endSeconds: clippedEnd - window.sourceStartSeconds + window.timelineStartSeconds,
                confidence: word.confidence, timingMethod: word.timingMethod
            ))
        }

        var result: [CaptionCue] = []
        var group: [TranscriptWord] = []
        func flush() throws {
            guard let first = group.first, let start = first.startSeconds,
                  let end = group.compactMap(\.endSeconds).max() else { return }
            // Punctuation-only, zero-duration recognition artifacts cannot form a cue alone.
            if end > start {
                result.append(try CaptionCue(
                    startSeconds: start, endSeconds: end,
                    text: joinedText(group, language: transcript.language), words: group
                ))
            }
            group.removeAll(keepingCapacity: true)
        }
        for word in words {
            if let first = group.first, let last = group.last,
               let firstStart = first.startSeconds, let previousEnd = last.endSeconds,
               let start = word.startSeconds, let end = word.endSeconds {
                let candidate = joinedText(group + [word], language: transcript.language)
                if group.count >= options.maximumWords || candidate.count > options.maximumCharacters
                    || end - firstStart > options.maximumDurationSeconds
                    || start - previousEnd > options.maximumPauseSeconds {
                    try flush()
                }
            }
            group.append(word)
            if endsSentence(word.text) { try flush() }
        }
        try flush()
        return result
    }

    private static func endsSentence(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.last.map { ".!?。！？…".contains($0) } ?? false
    }

    private static func joinedText(_ words: [TranscriptWord], language: String?) -> String {
        let languageCode = language?.lowercased().split(separator: "-").first.map(String.init)
        let normallyUnspaced = ["zh", "ja", "th", "lo", "km", "my"].contains(languageCode ?? "")
        var result = ""
        for word in words {
            let token = word.text
            guard !token.isEmpty else { continue }
            if result.isEmpty {
                result = token
                continue
            }
            let explicitWhitespace = token.first?.isWhitespace == true || result.last?.isWhitespace == true
            let closingPunctuation = token.first.map { ".,!?;:%…)]}’”。，、！？；：％）》」』】".contains($0) } ?? false
            let openingPunctuation = result.last.map { "([{‘“（《「『【".contains($0) } ?? false
            let cjkBoundary = token.first.map(isCJK) == true || result.last.map(isCJK) == true
            if !normallyUnspaced && !explicitWhitespace && !closingPunctuation && !openingPunctuation && !cjkBoundary {
                result += " "
            }
            result += token
        }
        return result.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isCJK(_ character: Character) -> Bool {
        character.unicodeScalars.contains { scalar in
            (0x3040...0x30FF).contains(scalar.value) || (0x3400...0x9FFF).contains(scalar.value)
                || (0xF900...0xFAFF).contains(scalar.value) || (0x20000...0x3134F).contains(scalar.value)
        }
    }
}

public enum CaptionExporter {
    /// Basic SRT cues. Word records remain in the transcript for a separate animated renderer.
    public static func srt(_ cues: [CaptionCue]) throws -> String {
        try validate(cues)
        return try cues.enumerated().map { index, cue in
            "\(index + 1)\n\(try timingLine(cue, separator: ","))\n\(escapedText(cue.text))\n"
        }.joined(separator: "\n")
    }

    public static func webVTT(_ cues: [CaptionCue]) throws -> String {
        try validate(cues)
        let body = try cues.map { cue in
            "\(try timingLine(cue, separator: "."))\n\(escapedText(cue.text))\n"
        }.joined(separator: "\n")
        return "WEBVTT\n\n" + body
    }

    private static func validate(_ cues: [CaptionCue]) throws {
        var previousStart = 0.0
        for cue in cues {
            try validateTimestampPair(cue.startSeconds, cue.endSeconds)
            guard cue.startSeconds >= previousStart, cue.endSeconds > cue.startSeconds else {
                throw TranscriptionError.invalidTimestamp("caption cues must be ordered and have positive duration")
            }
            previousStart = cue.startSeconds
        }
    }

    private static func milliseconds(_ seconds: Double) throws -> Int64 {
        // Keep conversion safely below Int64's floating-point rounding boundary.
        guard seconds.isFinite, seconds >= 0, seconds <= 9_000_000_000_000 else {
            throw TranscriptionError.invalidTimestamp("timestamp is outside the supported export range")
        }
        return Int64((seconds * 1000).rounded())
    }

    private static func timingLine(_ cue: CaptionCue, separator: String) throws -> String {
        let start = try milliseconds(cue.startSeconds)
        // Quantization must not erase a valid sub-millisecond cue's duration.
        let end = max(try milliseconds(cue.endSeconds), start + 1)
        return "\(timestamp(start, separator: separator)) --> \(timestamp(end, separator: separator))"
    }

    private static func timestamp(_ milliseconds: Int64, separator: String) -> String {
        let hours = milliseconds / 3_600_000
        let minutes = (milliseconds / 60_000) % 60
        let wholeSeconds = (milliseconds / 1000) % 60
        let remainder = milliseconds % 1000
        return String(format: "%02lld:%02lld:%02lld%@%03lld", hours, minutes, wholeSeconds, separator, remainder)
    }

    private static func escapedText(_ text: String) -> String {
        // Subtitle markup and injected blank lines must not alter the user's text or cue structure.
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .split(whereSeparator: \.isNewline).joined(separator: " ")
    }
}
