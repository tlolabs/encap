import Foundation

/// Exact installed bytes, including independently pinned tokenizer/config files.
/// This is a record of a verified manifest, not a substitute for a model lease.
public struct ModelArtifactIdentity: Codable, Equatable, Sendable {
    public let path: String
    public let repository: String
    public let revision: String
    public let repositoryPath: String
    public let sizeBytes: Int64
    public let sha256: String

    public init(path: String, repository: String, revision: String,
                repositoryPath: String, sizeBytes: Int64, sha256: String) throws {
        self.path = path; self.repository = repository; self.revision = revision
        self.repositoryPath = repositoryPath; self.sizeBytes = sizeBytes; self.sha256 = sha256
        try validate()
    }

    public func validate() throws {
        guard ModelCatalog.isRepository(repository), ModelCatalog.isHex(revision, count: 40),
              ModelCatalog.isHex(sha256, count: 64), sizeBytes >= 0 else {
            throw TranscriptionError.invalidInput("invalid immutable model artifact identity")
        }
        try ModelCatalog.validateRelativePath(path)
        try ModelCatalog.validateRelativePath(repositoryPath)
    }

    private enum CodingKeys: String, CodingKey {
        case path, repository, revision, repositoryPath, sizeBytes, sha256
    }
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(path: c.decode(String.self, forKey: .path),
            repository: c.decode(String.self, forKey: .repository),
            revision: c.decode(String.self, forKey: .revision),
            repositoryPath: c.decode(String.self, forKey: .repositoryPath),
            sizeBytes: c.decode(Int64.self, forKey: .sizeBytes),
            sha256: c.decode(String.self, forKey: .sha256))
    }
}

/// A complete immutable model/tokenizer selection. Existing cache installation
/// IDs remain unchanged; the full manifest digest removes reliance on a short ID.
public struct ModelIdentity: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let installationID: String
    public let repository: String
    public let revision: String
    public let manifestSHA256: String
    public let artifacts: [ModelArtifactIdentity]

    public init(installationID: String, repository: String, revision: String,
                manifestSHA256: String, artifacts: [ModelArtifactIdentity], schemaVersion: Int = 1) throws {
        self.schemaVersion = schemaVersion; self.installationID = installationID
        self.repository = repository; self.revision = revision
        self.manifestSHA256 = manifestSHA256; self.artifacts = artifacts
        try validate()
    }

    public func validate() throws {
        guard schemaVersion == 1, ModelCatalog.isRepository(repository),
              ModelCatalog.isHex(revision, count: 40), ModelCatalog.isHex(manifestSHA256, count: 64),
              !artifacts.isEmpty,
              installationID == revision + "-" + manifestSHA256 ||
                installationID == revision + "-" + String(manifestSHA256.prefix(16)) else {
            throw TranscriptionError.invalidInput("invalid immutable model manifest identity")
        }
        var paths = Set<String>()
        for artifact in artifacts {
            try artifact.validate()
            guard paths.insert(artifact.path.precomposedStringWithCanonicalMapping.lowercased()).inserted else {
                throw TranscriptionError.invalidInput("duplicate model provenance artifact path")
            }
        }
        for path in paths {
            var components = path.split(separator: "/").map(String.init)
            components.removeLast()
            while !components.isEmpty {
                guard !paths.contains(components.joined(separator: "/")) else {
                    throw TranscriptionError.invalidInput("model provenance artifact is also a directory")
                }
                components.removeLast()
            }
        }
    }

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, installationID, repository, revision, manifestSHA256, artifacts
    }
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(installationID: c.decode(String.self, forKey: .installationID),
            repository: c.decode(String.self, forKey: .repository),
            revision: c.decode(String.self, forKey: .revision),
            manifestSHA256: c.decode(String.self, forKey: .manifestSHA256),
            artifacts: c.decode([ModelArtifactIdentity].self, forKey: .artifacts),
            schemaVersion: c.decode(Int.self, forKey: .schemaVersion))
    }
}

public struct TranscriptProvenance: Codable, Equatable, Sendable {
    public let engineID: String
    public let modelID: String
    public let modelIdentity: ModelIdentity?
    /// Component identifiers mapped to exact SDK Git revisions, where known.
    public let runtimeRevisions: [String: String]?
    /// Digest of the actual validated native SDK build receipt, including patches.
    /// Absent where the runtime does not expose such a receipt.
    public let runtimeBuildSHA256: String?

    public init(engineID: String, modelID: String, modelIdentity: ModelIdentity? = nil,
                runtimeRevisions: [String: String]? = nil, runtimeBuildSHA256: String? = nil) {
        self.engineID = engineID; self.modelID = modelID; self.modelIdentity = modelIdentity
        self.runtimeRevisions = runtimeRevisions; self.runtimeBuildSHA256 = runtimeBuildSHA256
    }

    public func validate() throws {
        guard !engineID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !modelID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              !engineID.utf8.contains(where: { $0 < 32 || $0 == 127 }),
              !modelID.utf8.contains(where: { $0 < 32 || $0 == 127 }) else {
            throw TranscriptionError.invalidInput("recognition provenance must identify the engine and model")
        }
        try modelIdentity?.validate()
        if let runtimeRevisions {
            guard !runtimeRevisions.isEmpty, runtimeRevisions.allSatisfy({
                ModelCatalog.isComponent($0.key) && ModelCatalog.isHex($0.value, count: 40)
            }) else { throw TranscriptionError.invalidInput("invalid runtime source revisions") }
        }
        if let runtimeBuildSHA256, !ModelCatalog.isHex(runtimeBuildSHA256, count: 64) {
            throw TranscriptionError.invalidInput("invalid runtime build identity")
        }
    }

    private enum CodingKeys: String, CodingKey {
        case engineID, modelID, modelIdentity, runtimeRevisions, runtimeBuildSHA256
    }
    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(engineID: try c.decode(String.self, forKey: .engineID),
            modelID: try c.decode(String.self, forKey: .modelID),
            modelIdentity: try c.decodeIfPresent(ModelIdentity.self, forKey: .modelIdentity),
            runtimeRevisions: try c.decodeIfPresent([String: String].self, forKey: .runtimeRevisions),
            runtimeBuildSHA256: try c.decodeIfPresent(String.self, forKey: .runtimeBuildSHA256))
        try validate()
    }
}
