import AVIDTranscription
import Foundation

struct ModelWire: Encodable, Sendable {
    let id: String
    let name: String
    let downloadSize: String
    let downloadSizeBytes: Int64
    let languages: String
    let description: String
    let installed: Bool
    let downloadAllowed: Bool
    let role: String
    let engine: String
    let recognitionLanguages: [String]
    let timingLanguages: [String]
    let license: ModelLicense
    let installationID: String
    let repository: String
    let revision: String
    let installationState: String
    let isDefault: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, languages, description, installed, role, engine, license, repository, revision
        case downloadSize = "download_size", downloadSizeBytes = "download_size_bytes"
        case downloadAllowed = "download_allowed", recognitionLanguages = "recognition_languages"
        case timingLanguages = "timing_languages", installationID = "installation_id"
        case installationState = "installation_state", isDefault = "is_default"
    }
    init(_ model: ModelDescriptor, present: Bool, verified: Bool = false, defaultID: String) {
        id = model.id; name = model.displayName
        downloadSizeBytes = model.downloadSizeBytes
        downloadSize = "\(model.downloadSizeBytes) bytes"
        languages = model.recognitionLanguages.joined(separator: ", ")
        description = model.role == .aligner
            ? "Separate word alignment; select a supported timing language."
            : "Local \(model.engine.rawValue) recognition. Models are downloaded directly from the pinned public publisher."
        installed = present; downloadAllowed = true
        role = model.role.rawValue; engine = model.engine.rawValue
        recognitionLanguages = model.recognitionLanguages; timingLanguages = model.timingLanguages
        license = model.license; installationID = model.installationID
        repository = model.repository; revision = model.revision
        installationState = verified ? "verified" : (present ? "present_unverified" : "missing")
        isDefault = model.id == defaultID
    }
}

struct ProviderWire: Encodable, Sendable {
    let id: String
    let name: String
    let detail: String
}

struct ProgressWire: Encodable, Sendable {
    let event = "progress"
    let stage: String
    let fraction: Double?
    let modelID: String?
    let artifactPath: String?
    let completedBytes: Int64?
    let totalBytes: Int64?
    enum CodingKeys: String, CodingKey {
        case event, stage, fraction
        case modelID = "model_id", artifactPath = "artifact_path"
        case completedBytes = "completed_bytes", totalBytes = "total_bytes"
    }
    init(_ value: ModelDownloadProgress) {
        stage = value.phase.rawValue; fraction = value.fraction
        modelID = value.modelID; artifactPath = value.artifactPath
        completedBytes = value.completedBytes; totalBytes = value.totalBytes
    }
    init(stage: String, fraction: Double? = nil, modelID: String? = nil) {
        self.stage = stage; self.fraction = fraction; self.modelID = modelID
        artifactPath = nil; completedBytes = nil; totalBytes = nil
    }
}
