import Foundation

public struct TranscriptionProgress: Equatable, Sendable {
    public let stage: String
    public let fraction: Double?

    public init(stage: String, fraction: Double? = nil) {
        self.stage = stage
        self.fraction = fraction.flatMap { $0.isFinite ? min(1, max(0, $0)) : nil }
    }
}

public struct RecognitionRequest: Sendable {
    public let audioURL: URL
    public let modelID: String
    public let modelDirectory: URL
    public let language: String?
    /// Offset of the input's first sample on the original source audio's clock.
    public let sourceStartSeconds: Double

    public init(
        audioURL: URL, modelID: String, modelDirectory: URL,
        language: String? = nil, sourceStartSeconds: Double = 0
    ) {
        self.audioURL = audioURL
        self.modelID = modelID
        self.modelDirectory = modelDirectory
        self.language = language
        self.sourceStartSeconds = sourceStartSeconds
    }

    public func validate() throws {
        guard audioURL.isFileURL, modelDirectory.isFileURL else {
            throw TranscriptionError.invalidInput("audio and model locations must be local file URLs")
        }
        guard sourceStartSeconds.isFinite, sourceStartSeconds >= 0 else {
            throw TranscriptionError.invalidTimestamp("source offset must be finite and nonnegative")
        }
        guard !modelID.isEmpty else { throw TranscriptionError.invalidInput("model ID is empty") }
    }
}

/// Implementations use installed files only, check Task cancellation, and return source-relative times.
public protocol TranscriptionProvider: Sendable {
    var engineID: String { get }
    func transcribe(
        _ request: RecognitionRequest,
        progress: @escaping @Sendable (TranscriptionProgress) -> Void
    ) async throws -> Transcript
}

public struct AlignmentRequest: Sendable {
    public let audioURL: URL
    public let modelID: String
    public let modelDirectory: URL
    public let transcript: Transcript
    public let language: String?
    public let sourceStartSeconds: Double

    public init(
        audioURL: URL, modelID: String, modelDirectory: URL, transcript: Transcript,
        language: String? = nil, sourceStartSeconds: Double = 0
    ) {
        self.audioURL = audioURL
        self.modelID = modelID
        self.modelDirectory = modelDirectory
        self.transcript = transcript
        self.language = language
        self.sourceStartSeconds = sourceStartSeconds
    }

    public func validate() throws {
        try RecognitionRequest(
            audioURL: audioURL, modelID: modelID, modelDirectory: modelDirectory,
            language: language, sourceStartSeconds: sourceStartSeconds
        ).validate()
    }
}

/// Alignment preserves corrected text; it does not run a second recognition pass.
public protocol AlignmentProvider: Sendable {
    var engineID: String { get }
    func align(
        _ request: AlignmentRequest,
        progress: @escaping @Sendable (TranscriptionProgress) -> Void
    ) async throws -> Transcript
}
