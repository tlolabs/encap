import CryptoKit
import Foundation

public enum ModelEngine: String, Codable, Sendable { case whisperKit, fluidAudio, mlx }
public enum ModelRole: String, Codable, Sendable { case recognizer, aligner }

public struct ModelLicense: Codable, Sendable, Equatable {
    public let identifier: String
    public let notice: String
    public let url: String
}

public struct ModelArtifact: Codable, Sendable, Equatable {
    public let path: String
    public let repositoryPath: String
    public let sizeBytes: Int64
    public let sha256: String
    /// Auxiliary files, such as tokenizers, may come from a separately pinned repository.
    public let repository: String?
    public let revision: String?

    public init(path: String, repositoryPath: String, sizeBytes: Int64, sha256: String,
                repository: String? = nil, revision: String? = nil) {
        self.path = path; self.repositoryPath = repositoryPath
        self.sizeBytes = sizeBytes; self.sha256 = sha256
        self.repository = repository; self.revision = revision
    }
}

public struct ModelDescriptor: Codable, Sendable, Equatable, Identifiable {
    public let id: String
    public let displayName: String
    public let engine: ModelEngine
    public let role: ModelRole
    public let repository: String
    public let revision: String
    public let modelSubdirectory: String
    public let recognitionLanguages: [String]
    public let timingLanguages: [String]
    public let license: ModelLicense
    public let artifacts: [ModelArtifact]

    public var downloadSizeBytes: Int64 { artifacts.reduce(0) { $0 + $1.sizeBytes } }

    /// Includes auxiliary tokenizer pins and artifact selection, not only the primary model commit.
    public var installationID: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        // Every stored property is a Codable primitive; encoding cannot fail for this descriptor.
        let bytes = try! encoder.encode(self)
        let digest = SHA256.hash(data: bytes).prefix(8).map { String(format: "%02x", $0) }.joined()
        return revision + "-" + digest
    }

    public func downloadURL(for artifact: ModelArtifact) -> URL {
        // Catalog validation guarantees these are safe, relative path components.
        let source = artifact.repository ?? repository
        let pin = artifact.revision ?? revision
        return URL(string: "https://huggingface.co")!
            .appendingPathComponent(source)
            .appendingPathComponent("resolve")
            .appendingPathComponent(pin)
            .appendingPathComponent(artifact.repositoryPath)
    }
}

public enum ModelStoreError: Error, LocalizedError, Sendable {
    case invalidCatalog(String)
    case unknownModel(String)
    case unsafePath(String)
    case missingArtifact(String)
    case sizeMismatch(String, expected: Int64, actual: Int64)
    case checksumMismatch(String)
    case invalidResponse(String)
    case busy(String)

    public var errorDescription: String? {
        switch self {
        case .invalidCatalog(let message): "Invalid model catalog: \(message)"
        case .unknownModel(let id): "Unknown model: \(id)"
        case .unsafePath(let path): "Unsafe model path: \(path)"
        case .missingArtifact(let path): "Missing model artifact: \(path)"
        case .sizeMismatch(let path, let expected, let actual):
            "Incorrect size for \(path): expected \(expected), found \(actual) bytes"
        case .checksumMismatch(let path): "SHA-256 verification failed: \(path)"
        case .invalidResponse(let message): "Model download failed: \(message)"
        case .busy(let id): "Model operation already in progress: \(id)"
        }
    }
}

public struct ModelCatalog: Codable, Sendable {
    public let schemaVersion: Int
    public let defaultModelID: String
    public let models: [ModelDescriptor]

    public init(data: Data) throws {
        self = try JSONDecoder().decode(Self.self, from: data)
        try validate()
    }

    public static func bundled() throws -> Self {
        guard let url = Bundle.module.url(forResource: "models", withExtension: "json") else {
            throw ModelStoreError.invalidCatalog("Missing bundled models.json")
        }
        return try Self(data: Data(contentsOf: url))
    }

    public func model(id: String) throws -> ModelDescriptor {
        guard let model = models.first(where: { $0.id == id }) else {
            throw ModelStoreError.unknownModel(id)
        }
        return model
    }

    public func validate() throws {
        guard schemaVersion == 1, !models.isEmpty else {
            throw ModelStoreError.invalidCatalog("Unsupported schema or empty catalog")
        }
        var ids = Set<String>()
        for model in models {
            guard Self.isComponent(model.id), ids.insert(model.id.lowercased()).inserted,
                  Self.isRepository(model.repository), Self.isHex(model.revision, count: 40),
                  !model.artifacts.isEmpty, !model.license.identifier.isEmpty,
                  !model.license.notice.isEmpty, URL(string: model.license.url)?.scheme == "https" else {
                throw ModelStoreError.invalidCatalog("Invalid identity, pin, artifacts or license for \(model.id)")
            }
            if model.modelSubdirectory != "." { try Self.validateRelativePath(model.modelSubdirectory) }
            var paths = Set<String>()
            var total: Int64 = 0
            for artifact in model.artifacts {
                try Self.validateRelativePath(artifact.path)
                try Self.validateRelativePath(artifact.repositoryPath)
                let key = artifact.path.precomposedStringWithCanonicalMapping.lowercased()
                guard paths.insert(key).inserted,
                      artifact.sizeBytes >= 0,
                      Self.isHex(artifact.sha256, count: 64),
                      (artifact.repository == nil) == (artifact.revision == nil) else {
                    throw ModelStoreError.invalidCatalog("Invalid artifact \(artifact.path)")
                }
                if let source = artifact.repository, let pin = artifact.revision {
                    guard Self.isRepository(source), Self.isHex(pin, count: 40) else {
                        throw ModelStoreError.invalidCatalog("Invalid auxiliary source for \(artifact.path)")
                    }
                }
                let sum = total.addingReportingOverflow(artifact.sizeBytes)
                guard !sum.overflow else { throw ModelStoreError.invalidCatalog("Model size overflow") }
                total = sum.partialValue
            }
            for path in paths {
                var components = path.split(separator: "/").map(String.init)
                components.removeLast()
                while !components.isEmpty {
                    guard !paths.contains(components.joined(separator: "/")) else {
                        throw ModelStoreError.invalidCatalog("Artifact is also a directory: \(path)")
                    }
                    components.removeLast()
                }
            }
        }
        guard try model(id: defaultModelID).role == .recognizer else {
            throw ModelStoreError.invalidCatalog("Default must be a recognizer")
        }
    }

    static func isHex(_ text: String, count: Int) -> Bool {
        text.utf8.count == count && text.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }

    static func isComponent(_ text: String) -> Bool {
        guard let first = text.utf8.first, (48...57).contains(first) || (65...90).contains(first) || (97...122).contains(first) else { return false }
        return text.utf8.allSatisfy { (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || [45, 46, 95].contains($0) }
    }

    static func isRepository(_ text: String) -> Bool {
        let components = text.split(separator: "/", omittingEmptySubsequences: false)
        return components.count == 2 && components.allSatisfy { isComponent(String($0)) }
    }

    static func validateRelativePath(_ path: String) throws {
        let components = path.split(separator: "/", omittingEmptySubsequences: false)
        guard !components.isEmpty, components.allSatisfy({
            !$0.isEmpty && $0 != "." && $0 != ".." && !$0.hasPrefix(".avid-") &&
            !$0.contains("\\") && !$0.contains(":") && !$0.contains("\0") &&
            !$0.contains(where: { $0.isNewline || $0.asciiValue.map { $0 < 32 } == true })
        }) else { throw ModelStoreError.unsafePath(path) }
    }
}
