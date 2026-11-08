import CryptoKit
import Foundation
import Dispatch
import XCTest
@testable import AVIDTranscription

private actor FixtureDownloadTransport: ModelDownloadTransport {
    enum Behavior: Sendable { case complete, corrupt, interruptOnce, cancelOnce }
    let payload: Data
    let behavior: Behavior
    private(set) var offsets: [Int] = []

    init(payload: Data, behavior: Behavior = .complete) {
        self.payload = payload
        self.behavior = behavior
    }

    func download(from url: URL, to destination: URL, expectedSize: Int64,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        let existing = (try? Data(contentsOf: destination)) ?? Data()
        offsets.append(existing.count)
        if behavior == .corrupt {
            try Data(repeating: 0x78, count: Int(expectedSize)).write(to: destination)
            return
        }
        if offsets.count == 1 && (behavior == .interruptOnce || behavior == .cancelOnce) {
            try payload.prefix(2).write(to: destination)
            progress(2)
            if behavior == .cancelOnce { throw CancellationError() }
            throw URLError(.networkConnectionLost)
        }
        var completed = existing
        completed.append(payload.dropFirst(existing.count))
        try completed.write(to: destination)
        progress(Int64(completed.count))
    }
}

private actor HeldDownloadTransport: ModelDownloadTransport {
    let payload: Data
    let started: AsyncStream<Void>.Continuation
    private var releaseContinuation: CheckedContinuation<Void, Never>?

    init(payload: Data, started: AsyncStream<Void>.Continuation) {
        self.payload = payload
        self.started = started
    }

    func download(from url: URL, to destination: URL, expectedSize: Int64,
                  progress: @escaping @Sendable (Int64) -> Void) async throws {
        try payload.prefix(2).write(to: destination)
        started.yield(())
        await withCheckedContinuation { releaseContinuation = $0 }
        try Task.checkCancellation()
        try payload.write(to: destination)
        progress(Int64(payload.count))
    }

    func release() { releaseContinuation?.resume(); releaseContinuation = nil }
}

private actor ModelOperationGate {
    private var continuation: CheckedContinuation<Void, Never>?

    func hold(started: AsyncStream<Void>.Continuation) async {
        started.yield(())
        await withCheckedContinuation { continuation = $0 }
    }

    func release() { continuation?.resume(); continuation = nil }
}

/// A bounded stand-in for slow file IO/hash work; cleanup can always release the worker.
private final class VerificationProgressGate: @unchecked Sendable {
    private let semaphore = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var waiting = false

    var isWaiting: Bool {
        lock.lock()
        defer { lock.unlock() }
        return waiting
    }

    func hold(started: AsyncStream<Void>.Continuation) {
        lock.lock()
        waiting = true
        lock.unlock()
        started.yield(())
        _ = semaphore.wait(timeout: .now() + 5)
        lock.lock()
        waiting = false
        lock.unlock()
    }

    func release() { semaphore.signal() }
}

@MainActor
final class ModelStoreTests: XCTestCase {
    private let payload = Data("abcdef".utf8)
    private let modelID = "fixture"
    private let revision = String(repeating: "a", count: 40)

    private func temporaryDirectory() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("avid-model-store-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory
    }

    private func catalogObject() -> [String: Any] {
        let digest = SHA256.hash(data: payload).map { String(format: "%02x", $0) }.joined()
        return [
            "schemaVersion": 1, "defaultModelID": modelID,
            "models": [[
                "id": modelID, "displayName": "Fixture", "engine": "whisperKit", "role": "recognizer",
                "repository": "tests/fixture", "revision": revision, "modelSubdirectory": ".",
                "recognitionLanguages": ["en"], "timingLanguages": ["en"],
                "license": ["identifier": "MIT", "notice": "Fixture license", "url": "https://example.com/license"],
                "artifacts": [["path": "weights.bin", "repositoryPath": "weights.bin", "sizeBytes": payload.count, "sha256": digest]],
            ]],
        ]
    }

    private func catalog() throws -> ModelCatalog {
        try ModelCatalog(data: JSONSerialization.data(withJSONObject: catalogObject()))
    }

    func testCorruptDownloadNeverPublishesOrRemainsResumable() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload, behavior: .corrupt)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        do {
            _ = try await store.install(id: modelID)
            XCTFail("A corrupt model must not be published")
        } catch ModelStoreError.checksumMismatch { }
        let present = try await store.isPresent(id: modelID)
        XCTAssertFalse(present)
        let installationID = try catalog().model(id: modelID).installationID
        let partial = root.appendingPathComponent(modelID).appendingPathComponent(".\(installationID).partial/weights.bin")
        XCTAssertFalse(FileManager.default.fileExists(atPath: partial.path))
    }

    func testInterruptedAndCancelledTransfersResumePersistentPartialFiles() async throws {
        for behavior in [FixtureDownloadTransport.Behavior.interruptOnce, .cancelOnce] {
            let root = try temporaryDirectory()
            let transport = FixtureDownloadTransport(payload: payload, behavior: behavior)
            let firstStore = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
            do {
                _ = try await firstStore.install(id: modelID)
                XCTFail("The interrupted first transfer must fail")
            } catch { }
            let installationID = try catalog().model(id: modelID).installationID
            let partial = root.appendingPathComponent(modelID).appendingPathComponent(".\(installationID).partial/weights.bin")
            XCTAssertEqual(try Data(contentsOf: partial), payload.prefix(2))
            let firstPresent = try await firstStore.isPresent(id: modelID)
            XCTAssertFalse(firstPresent)
            // A fresh store proves resumability is persisted on disk, rather than held in actor state.
            let secondStore = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
            let installed = try await secondStore.install(id: modelID)
            XCTAssertEqual(try Data(contentsOf: installed.directory.appendingPathComponent("weights.bin")), payload)
            let offsets = await transport.offsets
            XCTAssertEqual(offsets, [0, 2])
            XCTAssertFalse(FileManager.default.fileExists(atPath: partial.path))
        }
    }

    func testVerifiedCacheIsOfflineAndTamperingIsDetected() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        let installed = try await store.install(id: modelID)
        _ = try await store.installedModel(id: modelID)
        _ = try await store.install(id: modelID)
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 1)
        try Data("xxxxxx".utf8).write(to: installed.directory.appendingPathComponent("weights.bin"))
        do {
            _ = try await store.installedModel(id: modelID)
            XCTFail("Cached bytes must be reverified")
        } catch ModelStoreError.checksumMismatch { }
        let callsAfterVerification = await transport.offsets.count
        XCTAssertEqual(callsAfterVerification, 1)
    }

    func testScopedUseReverifiesPresentCacheBeforeInvokingBackend() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        let installed = try await store.install(id: modelID)
        try Data("xxxxxx".utf8).write(to: installed.directory.appendingPathComponent("weights.bin"))
        let present = try await store.isPresent(id: modelID)
        XCTAssertTrue(present, "Presence must not be treated as an integrity assertion")
        do {
            _ = try await store.withInstalledModel(id: modelID) { _ in true }
            XCTFail("A present but corrupt model must not reach the backend")
        } catch ModelStoreError.checksumMismatch { }
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 1, "Scoped cache verification must not download replacement bytes")
    }

    func testProvisionMissingOfflineDoesNotDownloadAndScopedUseFails() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        try await store.provisionForUse(id: modelID, offline: true)
        do {
            _ = try await store.withInstalledModel(id: modelID) { _ in true }
            XCTFail("An offline request must not create a loadable model")
        } catch ModelStoreError.missingArtifact { }
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 0)
    }

    func testProvisionMissingOnlineDownloadsAndScopedUseVerifiesResult() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        try await store.provisionForUse(id: modelID)
        let bytes = try await store.withInstalledModel(id: modelID) { installed in
            try Data(contentsOf: installed.directory.appendingPathComponent("weights.bin"))
        }
        XCTAssertEqual(bytes, payload)
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 1)
    }

    func testProvisionPresentOnlineAndOfflineNeverRedownloadsCorruptCache() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        let installed = try await store.install(id: modelID)
        try Data("xxxxxx".utf8).write(to: installed.directory.appendingPathComponent("weights.bin"))
        for offline in [false, true] {
            try await store.provisionForUse(id: modelID, offline: offline)
            do {
                _ = try await store.withInstalledModel(id: modelID) { _ in true }
                XCTFail("Routing an existing model must not bypass final integrity verification")
            } catch ModelStoreError.checksumMismatch { }
        }
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 1, "Existing cache routing must not silently download replacements")
    }

    func testProvisionLocalOverridesOfflineWithoutNetworkAndValidatesSource() async throws {
        let base = try temporaryDirectory()
        let source = base.appendingPathComponent("source")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        try payload.write(to: source.appendingPathComponent("weights.bin"))
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: base.appendingPathComponent("cache"),
                                   transport: transport)
        try await store.provisionForUse(id: modelID, localDirectory: source, offline: true)
        let imported = try await store.withInstalledModel(id: modelID) { installed in installed.directory }
        XCTAssertNotEqual(imported, source)
        XCTAssertEqual(try Data(contentsOf: imported.appendingPathComponent("weights.bin")), payload)
        try Data("xxxxxx".utf8).write(to: source.appendingPathComponent("weights.bin"))
        do {
            try await store.provisionForUse(id: modelID, localDirectory: source)
            XCTFail("An explicitly supplied corrupt import must not be ignored for an existing cache")
        } catch ModelStoreError.checksumMismatch { }
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 0)
    }

    func testScopedUseReportsVerificationProgress() async throws {
        let root = try temporaryDirectory()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        _ = try await store.install(id: modelID)
        let events = AsyncStream<ModelDownloadProgress>.makeStream()
        defer { events.continuation.finish() }
        let directory = try await store.withInstalledModel(id: modelID, progress: {
            events.continuation.yield($0)
        }) { installed in installed.directory }
        events.continuation.finish()
        var progress: [ModelDownloadProgress] = []
        for await event in events.stream { progress.append(event) }
        XCTAssertEqual(progress.count, 1)
        XCTAssertEqual(progress.first?.phase, .verifying)
        XCTAssertEqual(progress.first?.completedBytes, Int64(payload.count))
        XCTAssertEqual(progress.first?.totalBytes, Int64(payload.count))
        XCTAssertEqual(try Data(contentsOf: directory.appendingPathComponent("weights.bin")), payload)
    }

    func testScopedVerificationKeepsOtherModelQueriesResponsiveAndRetainsLease() async throws {
        let root = try temporaryDirectory()
        var object = catalogObject()
        let firstModel = (object["models"] as! [[String: Any]])[0]
        var otherModel = firstModel
        otherModel["id"] = "fixture-other"
        object["models"] = [firstModel, otherModel]
        let fixtureCatalog = try ModelCatalog(data: JSONSerialization.data(withJSONObject: object))
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        let otherStore = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        _ = try await store.install(id: modelID)
        _ = try await store.install(id: "fixture-other")
        let gate = VerificationProgressGate()
        defer { gate.release() }
        let events = AsyncStream<Void>.makeStream()
        defer { events.continuation.finish() }
        let id = modelID
        let operation = Task {
            try await store.withInstalledModel(id: id, progress: { _ in
                gate.hold(started: events.continuation)
            }) { $0.directory }
        }
        var iterator = events.stream.makeAsyncIterator()
        _ = await iterator.next()
        let otherIsPresent = try await store.isPresent(id: "fixture-other")
        XCTAssertTrue(otherIsPresent)
        XCTAssertTrue(gate.isWaiting, "A cheap actor query must finish while verification is still running")
        do {
            try await otherStore.remove(id: modelID)
            XCTFail("Verification must retain its cross-store lease")
        } catch ModelStoreError.busy { }
        gate.release()
        _ = try await operation.value
    }

    func testCancelledScopedVerificationWaitsForWorkerBeforeReleasingLease() async throws {
        let root = try temporaryDirectory()
        let fixtureCatalog = try catalog()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        let otherStore = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        _ = try await store.install(id: modelID)
        let gate = VerificationProgressGate()
        defer { gate.release() }
        let events = AsyncStream<Void>.makeStream()
        defer { events.continuation.finish() }
        let id = modelID
        let operation = Task {
            try await store.withInstalledModel(id: id, progress: { _ in
                gate.hold(started: events.continuation)
            }) { _ in
                XCTFail("A cancelled verification must not invoke the backend")
                return true
            }
        }
        var iterator = events.stream.makeAsyncIterator()
        _ = await iterator.next()
        operation.cancel()
        do {
            try await otherStore.remove(id: modelID)
            XCTFail("Cancellation must not release a lease while its worker is still reading")
        } catch ModelStoreError.busy { }
        XCTAssertTrue(gate.isWaiting)
        gate.release()
        do {
            _ = try await operation.value
            XCTFail("Expected cancellation")
        } catch is CancellationError { }
        try await otherStore.remove(id: modelID)
        let present = try await store.isPresent(id: modelID)
        XCTAssertFalse(present)
    }

    func testLocalImportCopiesOnlyVerifiedArtifactsAndDeletionPreservesSource() async throws {
        let base = try temporaryDirectory()
        let source = base.appendingPathComponent("source")
        let root = base.appendingPathComponent("cache")
        try FileManager.default.createDirectory(at: source, withIntermediateDirectories: true)
        try payload.write(to: source.appendingPathComponent("weights.bin"))
        try Data("unlisted".utf8).write(to: source.appendingPathComponent("extra.txt"))
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        let local = try await store.localModel(id: modelID, directory: source)
        XCTAssertNotEqual(local.directory, source)
        XCTAssertFalse(FileManager.default.fileExists(atPath: local.directory.appendingPathComponent("extra.txt").path))
        let installed = try await store.importModel(id: modelID, from: source)
        XCTAssertFalse(FileManager.default.fileExists(atPath: installed.directory.appendingPathComponent("extra.txt").path))
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 0)
        try await store.remove(id: modelID)
        let present = try await store.isPresent(id: modelID)
        XCTAssertFalse(present)
        XCTAssertEqual(try Data(contentsOf: source.appendingPathComponent("weights.bin")), payload)
        try await store.remove(id: modelID)
    }

    func testLocalImportAndCacheRejectSymlinkEscapes() async throws {
        let base = try temporaryDirectory()
        let source = base.appendingPathComponent("source")
        let outside = base.appendingPathComponent("outside")
        let root = base.appendingPathComponent("cache")
        for directory in [source, outside, root] {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        let outsideFile = outside.appendingPathComponent("weights.bin")
        try payload.write(to: outsideFile)
        try FileManager.default.createSymbolicLink(at: source.appendingPathComponent("weights.bin"), withDestinationURL: outsideFile)
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: catalog(), rootDirectory: root, transport: transport)
        do {
            _ = try await store.importModel(id: modelID, from: source)
            XCTFail("A symlink must not satisfy artifact verification")
        } catch ModelStoreError.unsafePath { }
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent(modelID), withDestinationURL: outside)
        do {
            _ = try await store.install(id: modelID)
            XCTFail("A model cache symlink must not receive downloads")
        } catch ModelStoreError.unsafePath { }
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: outside.path), ["weights.bin"])
        let calls = await transport.offsets.count
        XCTAssertEqual(calls, 0)
    }

    func testCatalogRejectsTraversalAndCaseInsensitiveDuplicates() throws {
        var object = catalogObject()
        var models = object["models"] as! [[String: Any]]
        var artifacts = models[0]["artifacts"] as! [[String: Any]]
        artifacts[0]["path"] = "../escape.bin"
        models[0]["artifacts"] = artifacts
        object["models"] = models
        XCTAssertThrowsError(try ModelCatalog(data: JSONSerialization.data(withJSONObject: object)))

        object = catalogObject()
        models = object["models"] as! [[String: Any]]
        var duplicate = models[0]
        duplicate["id"] = modelID.uppercased()
        object["models"] = [models[0], duplicate]
        XCTAssertThrowsError(try ModelCatalog(data: JSONSerialization.data(withJSONObject: object)))

        object = catalogObject()
        models = object["models"] as! [[String: Any]]
        artifacts = models[0]["artifacts"] as! [[String: Any]]
        var duplicateArtifact = artifacts[0]
        duplicateArtifact["path"] = "WEIGHTS.BIN"
        artifacts.append(duplicateArtifact)
        models[0]["artifacts"] = artifacts
        object["models"] = models
        XCTAssertThrowsError(try ModelCatalog(data: JSONSerialization.data(withJSONObject: object)))
    }

    func testSeparateStoresSerializeSameModelButAllowDifferentModels() async throws {
        let root = try temporaryDirectory()
        var object = catalogObject()
        let firstModel = (object["models"] as! [[String: Any]])[0]
        var otherModel = firstModel
        otherModel["id"] = "fixture-other"
        object["models"] = [firstModel, otherModel]
        let sharedCatalog = try ModelCatalog(data: JSONSerialization.data(withJSONObject: object))
        let events = AsyncStream<Void>.makeStream()
        defer { events.continuation.finish() }
        let heldTransport = HeldDownloadTransport(payload: payload, started: events.continuation)
        let firstStore = try ModelStore(catalog: sharedCatalog, rootDirectory: root, transport: heldTransport)
        let secondStore = try ModelStore(catalog: sharedCatalog, rootDirectory: root,
                                         transport: FixtureDownloadTransport(payload: payload))
        let id = modelID
        let firstInstall = Task {
            defer { events.continuation.finish() }
            return try await firstStore.install(id: id)
        }
        var iterator = events.stream.makeAsyncIterator()
        _ = await iterator.next()
        do {
            _ = try await secondStore.install(id: modelID)
            XCTFail("A second store must not mutate a model with an active install")
        } catch ModelStoreError.busy(let busyID) {
            XCTAssertEqual(busyID, modelID)
        } catch {
            await heldTransport.release()
            _ = try? await firstInstall.value
            throw error
        }
        do {
            let other = try await secondStore.install(id: "fixture-other")
            XCTAssertEqual(try Data(contentsOf: other.directory.appendingPathComponent("weights.bin")), payload)
        } catch {
            await heldTransport.release()
            _ = try? await firstInstall.value
            throw error
        }
        await heldTransport.release()
        _ = try await firstInstall.value
    }

    func testScopedUsePreventsRemovalUntilBackendIsReleased() async throws {
        let root = try temporaryDirectory()
        let fixtureCatalog = try catalog()
        let transport = FixtureDownloadTransport(payload: payload)
        let store = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        let otherStore = try ModelStore(catalog: fixtureCatalog, rootDirectory: root, transport: transport)
        _ = try await store.install(id: modelID)
        let gate = ModelOperationGate()
        let events = AsyncStream<Void>.makeStream()
        defer { events.continuation.finish() }
        let id = modelID
        let operation = Task {
            defer { events.continuation.finish() }
            return try await store.withInstalledModel(id: id) { installed in
                await gate.hold(started: events.continuation)
                return installed.directory
            }
        }
        var iterator = events.stream.makeAsyncIterator()
        _ = await iterator.next()
        do {
            try await otherStore.remove(id: modelID)
            XCTFail("Model removal must not race an active inference operation")
        } catch ModelStoreError.busy { }
        catch {
            await gate.release()
            _ = try? await operation.value
            throw error
        }
        await gate.release()
        let directory = try await operation.value
        XCTAssertEqual(try Data(contentsOf: directory.appendingPathComponent("weights.bin")), payload)
        try await otherStore.remove(id: modelID)
        let present = try await store.isPresent(id: modelID)
        XCTAssertFalse(present)
    }
}
