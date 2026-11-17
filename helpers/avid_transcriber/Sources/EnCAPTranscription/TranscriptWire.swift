import AVIDTranscription
import Foundation

/// Version 1 of the sidecar's source-clock contract. Explicit keys avoid changing the
/// shared Codable format or losing acronym fields through automatic key conversion.
struct TranscriptWire: Codable, Sendable, Equatable {
    struct Provenance: Codable, Sendable, Equatable {
        let engineID: String
        let modelID: String
        let modelInstallationID: String?
        let sourceBundleSHA256: String?
        let modelIdentity: ModelIdentity?
        let runtimeRevisions: [String: String]?
        let runtimeBuildSHA256: String?
        enum CodingKeys: String, CodingKey {
            case modelIdentity = "model_identity", runtimeRevisions = "runtime_revisions"
            case runtimeBuildSHA256 = "runtime_build_sha256"
            case engineID = "engine_id", modelID = "model_id"
            case modelInstallationID = "model_installation_id", sourceBundleSHA256 = "source_bundle_sha256"
        }
        init(_ value: TranscriptProvenance, descriptor: ModelDescriptor? = nil) {
            engineID = value.engineID; modelID = value.modelID
            modelIdentity = value.modelIdentity
            runtimeRevisions = value.runtimeRevisions
            runtimeBuildSHA256 = value.runtimeBuildSHA256
            modelInstallationID = value.modelIdentity?.installationID ?? descriptor?.installationID
            sourceBundleSHA256 = descriptor == nil ? nil : SharedSource.bundleSHA256
        }
        var core: TranscriptProvenance { .init(engineID: engineID, modelID: modelID,
            modelIdentity: modelIdentity, runtimeRevisions: runtimeRevisions, runtimeBuildSHA256: runtimeBuildSHA256) }
    }
    struct Word: Codable, Sendable, Equatable {
        let text: String
        let startSeconds: Double?
        let endSeconds: Double?
        let confidence: Double?
        let timingMethod: TimingMethod?
        enum CodingKeys: String, CodingKey {
            case text, confidence
            case startSeconds = "start_seconds", endSeconds = "end_seconds", timingMethod = "timing_method"
        }
        init(_ value: TranscriptWord) {
            text = value.text; startSeconds = value.startSeconds; endSeconds = value.endSeconds
            confidence = value.confidence; timingMethod = value.timingMethod
        }
        func core() throws -> TranscriptWord {
            try .init(text: text, startSeconds: startSeconds, endSeconds: endSeconds,
                      confidence: confidence, timingMethod: timingMethod)
        }
    }
    struct Segment: Codable, Sendable, Equatable {
        let text: String
        let words: [Word]?
        let startSeconds: Double?
        let endSeconds: Double?
        enum CodingKeys: String, CodingKey {
            case text, words
            case startSeconds = "start_seconds", endSeconds = "end_seconds"
        }
        init(_ value: AVIDTranscription.TranscriptSegment) {
            text = value.text; words = value.words.map(Word.init)
            startSeconds = value.startSeconds; endSeconds = value.endSeconds
        }
        func core() throws -> AVIDTranscription.TranscriptSegment {
            try .init(text: text, words: (words ?? []).map { try $0.core() },
                      startSeconds: startSeconds, endSeconds: endSeconds)
        }
    }
    let segments: [Segment]
    let language: String?
    let provenance: Provenance
    let alignmentProvenance: Provenance?
    let recognitionSegments: [Segment]?
    enum CodingKeys: String, CodingKey {
        case segments, language, provenance
        case alignmentProvenance = "alignment_provenance"
        case recognitionSegments = "recognition_segments"
    }
    init(_ value: Transcript, recognitionSegments: [AVIDTranscription.TranscriptSegment]? = nil,
         recognitionProvenance: Provenance? = nil, alignmentProvenance: Provenance? = nil) {
        segments = value.segments.map(Segment.init); language = value.language
        provenance = recognitionProvenance ?? .init(value.provenance)
        self.alignmentProvenance = alignmentProvenance ?? value.alignmentProvenance.map { Provenance($0) }
        self.recognitionSegments = recognitionSegments?.map(Segment.init)
    }
    func core() throws -> Transcript {
        try .init(segments: segments.map { try $0.core() }, language: language,
                  provenance: provenance.core, alignmentProvenance: alignmentProvenance?.core)
    }
}

enum SharedSource {
    // Must move with the immutable vendor snapshot, never a mutable checkout revision.
    static let bundleSHA256 = "76f517ddfcf14067ac52c0f84b61b4f3bb7dd11917df30de94385dc0d15428a3"
}
