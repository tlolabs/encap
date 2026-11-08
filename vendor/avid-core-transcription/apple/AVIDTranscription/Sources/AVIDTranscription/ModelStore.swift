import CryptoKit
import Darwin
import Dispatch
import Foundation

public struct ModelDownloadProgress: Sendable {
    public enum Phase: String, Sendable { case downloading, verifying, complete }
    public let modelID: String
    public let artifactPath: String?
    public let completedBytes: Int64
    public let totalBytes: Int64
    public let phase: Phase
    public var fraction: Double { totalBytes == 0 ? 1 : min(1, Double(completedBytes) / Double(totalBytes)) }
}

public typealias ModelProgressHandler = @Sendable (ModelDownloadProgress) -> Void

/// Implementations must stream to `destination`, honor cancellation, and never exceed `expectedSize`.
/// An existing partial file can be resumed, but a server ignoring Range must restart it from zero.
public protocol ModelDownloadTransport: Sendable {
    func download(from url: URL, to destination: URL, expectedSize: Int64,
                  progress: @escaping @Sendable (Int64) -> Void) async throws
}

public struct InstalledModel: Sendable {
    public let descriptor: ModelDescriptor
    public let directory: URL
}

/// Owns only downloaded model files. Recognition never calls the network through this store.
/// A complete revision is published by rename only after every artifact is verified.
public actor ModelStore {
    public let catalog: ModelCatalog
    public let rootDirectory: URL
    private let transport: any ModelDownloadTransport
    private var operations = Set<String>()
    private static let verificationQueue = DispatchQueue(
        label: "AVID.ModelStore.verification", qos: .utility, attributes: .concurrent
    )

    public init(catalog: ModelCatalog, rootDirectory: URL = ModelStore.defaultDirectory,
                transport: any ModelDownloadTransport = HTTPModelDownloadTransport()) throws {
        try catalog.validate()
        guard rootDirectory.isFileURL else { throw ModelStoreError.unsafePath(rootDirectory.absoluteString) }
        self.catalog = catalog
        self.rootDirectory = rootDirectory.standardizedFileURL.resolvingSymlinksInPath()
        self.transport = transport
    }

    public nonisolated static var defaultDirectory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AVID/Transcription/Models", isDirectory: true)
    }

    /// This is a cheap presence check for a model picker, not an integrity assertion.
    public func isPresent(id: String) throws -> Bool {
        let model = try catalog.model(id: id)
        return FileManager.default.fileExists(atPath: revisionDirectory(model).path)
    }

    /// Route a host's provisioning request before scoped use. Cached/offline presence is not
    /// an integrity assertion: hosts must still load through withInstalledModel afterwards.
    /// A supplied local directory takes precedence, including in offline mode.
    public func provisionForUse(id: String, localDirectory: URL? = nil, offline: Bool = false,
                                progress: ModelProgressHandler? = nil) async throws {
        _ = try catalog.model(id: id)
        if let localDirectory {
            _ = try localModel(id: id, directory: localDirectory)
            return
        }
        if offline { return }
        if try isPresent(id: id) { return }
        _ = try await install(id: id, progress: progress)
    }

    /// Verify all bytes on disk without contacting upstream. Safe to use while completely offline.
    public func installedModel(id: String, progress: ModelProgressHandler? = nil) throws -> InstalledModel {
        let model = try catalog.model(id: id)
        let lease = try begin(id)
        defer { lease.release(); operations.remove(id) }
        let directory = revisionDirectory(model)
        try rejectSymlinks(directory, under: rootDirectory)
        try verify(model, at: directory, progress: progress)
        return try installed(model, at: directory)
    }

    /// Hold the cross-process model lock throughout loading and inference. Hosts must unload
    /// the backend before this operation returns; remove() then cannot race lazy-mapped weights.
    public func withInstalledModel<T: Sendable>(
        id: String, progress: ModelProgressHandler? = nil,
        operation: @Sendable (InstalledModel) async throws -> T
    ) async throws -> T {
        let model = try catalog.model(id: id)
        let lease = try begin(id)
        defer { lease.release(); operations.remove(id) }
        let directory = revisionDirectory(model)
        try rejectSymlinks(directory, under: rootDirectory)
        // Keep the model lease while blocking file reads/hash work runs outside the actor.
        // Await worker completion even after cancellation so removal cannot race its reads.
        try await verifyForScopedUse(model, at: directory, progress: progress)
        let installation = try installed(model, at: directory)
        try Task.checkCancellation()
        return try await operation(installation)
    }

    /// Download directly from pinned public repositories. Cancel the calling Task to stop;
    /// partial files remain available for a later Range request and are never loadable models.
    public func install(id: String, progress: ModelProgressHandler? = nil) async throws -> InstalledModel {
        let model = try catalog.model(id: id)
        let lease = try begin(id)
        defer { lease.release(); operations.remove(id) }
        let final = revisionDirectory(model)
        if FileManager.default.fileExists(atPath: final.path) {
            try rejectSymlinks(final, under: rootDirectory)
            try verify(model, at: final, progress: progress)
            return try installed(model, at: final)
        }
        try prepareRoot()
        let parent = rootDirectory.appendingPathComponent(model.id, isDirectory: true)
        try ensureDirectory(parent, under: rootDirectory)
        let staging = parent.appendingPathComponent(".\(model.installationID).partial", isDirectory: true)
        try ensureDirectory(staging, under: rootDirectory)
        var completed: Int64 = 0
        for artifact in model.artifacts {
            try Task.checkCancellation()
            let file = staging.appendingPathComponent(artifact.path)
            try ensureDirectory(file.deletingLastPathComponent(), under: rootDirectory)
            try rejectSymlinks(file, under: rootDirectory)
            if (try? Self.verifyArtifact(artifact, file: file)) == nil {
                let base = completed
                // A complete but corrupt artifact must not be resumed forever.
                if let size = try? Self.regularFileSize(file), size >= artifact.sizeBytes {
                    try FileManager.default.removeItem(at: file)
                }
                try await transport.download(from: model.downloadURL(for: artifact), to: file,
                                             expectedSize: artifact.sizeBytes) { bytes in
                    progress?(ModelDownloadProgress(modelID: id, artifactPath: artifact.path,
                        completedBytes: base + bytes, totalBytes: model.downloadSizeBytes, phase: .downloading))
                }
                try Task.checkCancellation()
                do { try Self.verifyArtifact(artifact, file: file) }
                catch {
                    // Preserve useful interrupted transfers, but discard bytes proven invalid.
                    if case ModelStoreError.checksumMismatch = error {
                        try? FileManager.default.removeItem(at: file)
                    }
                    throw error
                }
            }
            completed += artifact.sizeBytes
            progress?(ModelDownloadProgress(modelID: id, artifactPath: artifact.path,
                completedBytes: completed, totalBytes: model.downloadSizeBytes, phase: .verifying))
        }
        try Task.checkCancellation()
        try FileManager.default.moveItem(at: staging, to: final)
        progress?(ModelDownloadProgress(modelID: id, artifactPath: nil,
            completedBytes: model.downloadSizeBytes, totalBytes: model.downloadSizeBytes, phase: .complete))
        return try installed(model, at: final)
    }

    /// Provision a manually supplied folder without network requests. Copy only catalog-listed
    /// artifacts into the cache so extra local weight shards cannot change what a backend loads.
    public func localModel(id: String, directory: URL) throws -> InstalledModel {
        try importModel(id: id, from: directory)
    }

    /// Import a verified folder into the shared cache. Unlisted files are not copied.
    public func importModel(id: String, from directory: URL,
                            progress: ModelProgressHandler? = nil) throws -> InstalledModel {
        let model = try catalog.model(id: id)
        let lease = try begin(id)
        defer { lease.release(); operations.remove(id) }
        let source = directory.standardizedFileURL
        try verify(model, at: source, progress: progress)
        let final = revisionDirectory(model)
        if FileManager.default.fileExists(atPath: final.path) {
            try rejectSymlinks(final, under: rootDirectory)
            try verify(model, at: final, progress: progress)
            return try installed(model, at: final)
        }
        try prepareRoot()
        let parent = rootDirectory.appendingPathComponent(model.id, isDirectory: true)
        try ensureDirectory(parent, under: rootDirectory)
        let staging = parent.appendingPathComponent(".avid-import-\(UUID().uuidString)", isDirectory: true)
        try ensureDirectory(staging, under: rootDirectory)
        defer { try? FileManager.default.removeItem(at: staging) }
        for artifact in model.artifacts {
            try Task.checkCancellation()
            let target = staging.appendingPathComponent(artifact.path)
            try ensureDirectory(target.deletingLastPathComponent(), under: rootDirectory)
            try FileManager.default.copyItem(at: source.appendingPathComponent(artifact.path), to: target)
        }
        // Recheck copied bytes before publishing (including changes during an external copy).
        try verify(model, at: staging, progress: progress)
        try Task.checkCancellation()
        try FileManager.default.moveItem(at: staging, to: final)
        return try installed(model, at: final)
    }

    /// Removes this model's completed revisions and partial downloads, never a caller's import source.
    public func remove(id: String) throws {
        _ = try catalog.model(id: id)
        let lease = try begin(id)
        defer { lease.release(); operations.remove(id) }
        let directory = rootDirectory.appendingPathComponent(id, isDirectory: true)
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try rejectSymlinks(directory, under: rootDirectory)
        try FileManager.default.removeItem(at: directory)
    }

    private func begin(_ id: String) throws -> ModelFileLock {
        guard !operations.contains(id) else { throw ModelStoreError.busy(id) }
        try prepareRoot()
        let directory = rootDirectory.appendingPathComponent(".avid-locks", isDirectory: true)
        try ensureDirectory(directory, under: rootDirectory)
        let lease = try ModelFileLock(file: directory.appendingPathComponent(id + ".lock"), modelID: id)
        operations.insert(id)
        return lease
    }

    private func revisionDirectory(_ model: ModelDescriptor) -> URL {
        rootDirectory.appendingPathComponent(model.id, isDirectory: true)
            .appendingPathComponent(model.installationID, isDirectory: true)
    }

    private func installed(_ model: ModelDescriptor, at directory: URL) throws -> InstalledModel {
        let modelDirectory = model.modelSubdirectory == "." ? directory : directory.appendingPathComponent(model.modelSubdirectory)
        try rejectSymlinks(modelDirectory, under: directory)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: modelDirectory.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            throw ModelStoreError.missingArtifact(modelDirectory.path)
        }
        return InstalledModel(descriptor: model, directory: modelDirectory)
    }

    private func verifyForScopedUse(_ model: ModelDescriptor, at directory: URL,
                                    progress: ModelProgressHandler?) async throws {
        let cancellation = ModelVerificationCancellation()
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                Self.verificationQueue.async {
                    do {
                        try self.verify(model, at: directory, progress: progress,
                                        checkCancellation: cancellation.check)
                        continuation.resume()
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            }
            try Task.checkCancellation()
        } onCancel: {
            cancellation.cancel()
        }
    }

    private nonisolated func verify(_ model: ModelDescriptor, at directory: URL,
                                    progress: ModelProgressHandler? = nil,
                                    checkCancellation: () throws -> Void = { try Task.checkCancellation() }) throws {
        var completed: Int64 = 0
        for artifact in model.artifacts {
            try checkCancellation()
            let file = directory.appendingPathComponent(artifact.path)
            try rejectSymlinks(file, under: directory)
            try Self.verifyArtifact(artifact, file: file, checkCancellation: checkCancellation)
            completed += artifact.sizeBytes
            progress?(ModelDownloadProgress(modelID: model.id, artifactPath: artifact.path,
                completedBytes: completed, totalBytes: model.downloadSizeBytes, phase: .verifying))
        }
    }

    private static func regularFileSize(_ file: URL) throws -> Int64 {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: file.path),
              attributes[.type] as? FileAttributeType == .typeRegular,
              let size = attributes[.size] as? NSNumber else {
            throw ModelStoreError.missingArtifact(file.path)
        }
        return size.int64Value
    }

    private static func verifyArtifact(_ artifact: ModelArtifact, file: URL,
                                       checkCancellation: () throws -> Void = { try Task.checkCancellation() }) throws {
        let size = try regularFileSize(file)
        guard size == artifact.sizeBytes else {
            throw ModelStoreError.sizeMismatch(artifact.path, expected: artifact.sizeBytes, actual: size)
        }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hash = SHA256()
        while true {
            try checkCancellation()
            guard let data = try handle.read(upToCount: 1024 * 1024), !data.isEmpty else { break }
            hash.update(data: data)
        }
        let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
        guard actual == artifact.sha256 else { throw ModelStoreError.checksumMismatch(artifact.path) }
    }

    private func prepareRoot() throws {
        try FileManager.default.createDirectory(at: rootDirectory, withIntermediateDirectories: true)
        try rejectSymlinks(rootDirectory, under: rootDirectory)
    }

    private func ensureDirectory(_ directory: URL, under root: URL) throws {
        try rejectSymlinks(directory, under: root)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try rejectSymlinks(directory, under: root)
    }

    private nonisolated func rejectSymlinks(_ target: URL, under root: URL) throws {
        let rootPath = root.standardizedFileURL.path
        let targetPath = target.standardizedFileURL.path
        guard targetPath == rootPath || targetPath.hasPrefix(rootPath + "/") else {
            throw ModelStoreError.unsafePath(target.path)
        }
        var current = target.standardizedFileURL
        while true {
            if let attributes = try? FileManager.default.attributesOfItem(atPath: current.path),
               attributes[.type] as? FileAttributeType == .typeSymbolicLink {
                throw ModelStoreError.unsafePath(current.path)
            }
            if current.path == rootPath { break }
            current.deleteLastPathComponent()
        }
    }
}

/// Advisory lock shared by every AVID host using this cache. Lock files are persistent: deleting
/// a locked inode would allow a second process to lock a different inode at the same pathname.
private final class ModelFileLock {
    private var descriptor: Int32

    init(file: URL, modelID: String) throws {
        descriptor = open(file.path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, S_IRUSR | S_IWUSR)
        guard descriptor >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
            let code = errno
            close(descriptor); descriptor = -1
            if code == EWOULDBLOCK { throw ModelStoreError.busy(modelID) }
            throw POSIXError(POSIXErrorCode(rawValue: code) ?? .EIO)
        }
    }

    func release() {
        if descriptor >= 0 { flock(descriptor, LOCK_UN); close(descriptor); descriptor = -1 }
    }

    deinit { release() }
}

/// Dispatch work has no Swift task context; this flag carries the caller's cancellation.
/// The lock protects every access, and a cancelled worker is still awaited before its lease ends.
private final class ModelVerificationCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false

    func cancel() {
        lock.lock()
        cancelled = true
        lock.unlock()
    }

    func check() throws {
        lock.lock()
        let isCancelled = cancelled
        lock.unlock()
        if isCancelled { throw CancellationError() }
    }
}
