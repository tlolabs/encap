import Foundation
import Dispatch

/// Isolated per async invocation. The callback borrows Data only during delivery.
enum LinkedProgress {
    @TaskLocal static var handler: (@Sendable (Data) -> Void)?
}

private final class OperationToken: @unchecked Sendable {
    private let lock = NSLock()
    private var task: Task<Data, Never>?
    private var cancelled = false
    private var executing = false
    func begin() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !executing else { return false }
        executing = true
        return true
    }
    func install(_ task: Task<Data, Never>) {
        lock.lock(); self.task = task; let cancel = cancelled; lock.unlock()
        if cancel { task.cancel() }
    }
    func finish() { lock.lock(); task = nil; executing = false; lock.unlock() }
    func cancel() {
        lock.lock(); cancelled = true; let current = task; lock.unlock()
        current?.cancel()
    }
}

public typealias TranscriptionEventCallback = @convention(c) (UnsafeMutableRawPointer?, UnsafePointer<UInt8>?, Int) -> Void
final class ProgressDelivery: @unchecked Sendable {
    let callback: TranscriptionEventCallback?
    let context: UnsafeMutableRawPointer?
    private let lock = NSLock()
    private var queued: [Data] = []
    private var first = 0
    init(_ callback: TranscriptionEventCallback?, _ context: UnsafeMutableRawPointer?) { self.callback = callback; self.context = context }
    func send(_ data: Data) {
        guard callback != nil else { return }
        lock.lock(); defer { lock.unlock() }
        // Progress is advisory. Bound pending updates while a provider reports
        // faster than the caller can dispatch; never retain a borrowed span.
        if queued.count == 1024 {
            queued[first] = data
            first = (first + 1) % queued.count
        } else {
            queued.append(data)
        }
    }
    func drain() {
        guard let callback else { return }
        lock.lock()
        let pending = queued
        let start = first
        queued.removeAll(keepingCapacity: true)
        first = 0
        lock.unlock()
        for index in pending.indices {
            let data = pending[(start + index) % pending.count]
            data.withUnsafeBytes { bytes in callback(context, bytes.baseAddress?.assumingMemoryBound(to: UInt8.self), bytes.count) }
        }
    }
}

private final class CompletedResult: @unchecked Sendable {
    let ready = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var value = Data()
    func finish(_ value: Data) { lock.lock(); self.value = value; lock.unlock(); ready.signal() }
    func wait(delivery: ProgressDelivery) -> Data {
        while ready.wait(timeout: .now() + .milliseconds(30)) == .timedOut { delivery.drain() }
        delivery.drain()
        lock.lock(); defer { lock.unlock() }; return value
    }
}

private final class Handles: @unchecked Sendable {
    static let shared = Handles()
    private let lock = NSLock()
    private var next: UInt64 = 1
    private var tokens: [UInt64: OperationToken] = [:]
    private var results: [UInt64: Data] = [:]
    private func allocate() -> UInt64 {
        guard next != UInt64.max else { return 0 }
        let id = next; next += 1; return id
    }
    func createToken() -> UInt64 {
        lock.lock(); defer { lock.unlock() }; let id = allocate()
        if id != 0 { tokens[id] = OperationToken() }; return id
    }
    func token(_ id: UInt64) -> OperationToken? {
        lock.lock(); defer { lock.unlock() }; return tokens[id]
    }
    func result(_ id: UInt64) -> Data? {
        lock.lock(); defer { lock.unlock() }; return results[id]
    }
    func insert(_ value: Data) -> UInt64 {
        lock.lock(); defer { lock.unlock() }; let id = allocate()
        if id != 0 { results[id] = value }; return id
    }
    func release(_ id: UInt64) {
        lock.lock(); tokens.removeValue(forKey: id); results.removeValue(forKey: id); lock.unlock()
    }
}

private struct Failure: Encodable {
    let schema_version = 1
    let ok = false
    let error: Detail
    struct Detail: Encodable { let code: String; let detail: String }
}
private func failure(_ code: String, _ detail: String) -> Data {
    (try? JSONEncoder().encode(Failure(error: .init(code: code, detail: detail)))) ?? Data()
}

/// ABI/schema 1; execute is blocking and must be called on a host worker. A token
/// is per invocation. Releasing it never cancels or makes library unloading safe.
@_cdecl("encap_transcription_abi_version")
public func transcriptionABIVersion() -> UInt32 { 1 }
@_cdecl("encap_transcription_token_create")
public func transcriptionTokenCreate() -> UInt64 { Handles.shared.createToken() }
@_cdecl("encap_transcription_cancel")
public func transcriptionCancel(_ token: UInt64) -> Int32 {
    guard let operation = Handles.shared.token(token) else { return 0 }
    operation.cancel(); return 1
}
@_cdecl("encap_transcription_release")
public func transcriptionRelease(_ handle: UInt64) { Handles.shared.release(handle) }

/// Request is a bounded, versioned EnCAP adapter object with an operation and
/// its explicit argument values. Transcript files are operation-local inputs;
/// neither a complete project manifest nor a model's bytes enter this request.
@_cdecl("encap_transcription_execute")
public func transcriptionExecute(_ token: UInt64, _ bytes: UnsafePointer<UInt8>?, _ length: Int,
    _ callback: TranscriptionEventCallback?, _ context: UnsafeMutableRawPointer?) -> UInt64 {
    guard let operation = Handles.shared.token(token) else {
        return Handles.shared.insert(failure("invalid_handle", "Unknown operation token."))
    }
    guard length > 0, length <= 4 * 1024 * 1024, let bytes else {
        return Handles.shared.insert(failure("invalid_request", "Request must contain 1–4194304 UTF-8 JSON bytes."))
    }
    struct Request: Decodable { let schema_version: Int; let arguments: [String] }
    let request: Request
    do {
        request = try JSONDecoder().decode(Request.self, from: Data(bytes: bytes, count: length))
        guard request.schema_version == 1 else { throw BridgeError.invalid("Unsupported transcription schema.") }
    } catch { return Handles.shared.insert(failure("invalid_request", error.localizedDescription)) }
    guard operation.begin() else { return Handles.shared.insert(failure("busy", "Token already executing.")) }
    let completed = CompletedResult()
    let delivery = ProgressDelivery(callback, context)
    let task = Task.detached {
        let data: Data
        do {
            try Task.checkCancellation()
            let result = try await LinkedProgress.$handler.withValue({ delivery.send($0) }) {
                try await BridgeCommand.execute(request.arguments)
            }
            try Task.checkCancellation()
            data = Data("{\"schema_version\":1,\"ok\":true,\"result\":".utf8) + result + Data("}".utf8)
        } catch is CancellationError {
            data = failure("cancelled", "The operation was cancelled after awaited model cleanup.")
        } catch { data = failure("transcription", error.localizedDescription) }
        completed.finish(data)
        return data
    }
    operation.install(task)
    let data = completed.wait(delivery: delivery)
    operation.finish()
    return Handles.shared.insert(data)
}
@_cdecl("encap_transcription_result_size")
public func transcriptionResultSize(_ result: UInt64) -> Int {
    Handles.shared.result(result)?.count ?? 0
}
@_cdecl("encap_transcription_result_copy")
public func transcriptionResultCopy(_ result: UInt64, _ destination: UnsafeMutablePointer<UInt8>?, _ capacity: Int) -> Int32 {
    guard let value = Handles.shared.result(result), capacity >= value.count,
          value.isEmpty || destination != nil else { return 0 }
    value.withUnsafeBytes { bytes in
        if let destination, let source = bytes.baseAddress { destination.update(from: source.assumingMemoryBound(to: UInt8.self), count: value.count) }
    }
    return 1
}
