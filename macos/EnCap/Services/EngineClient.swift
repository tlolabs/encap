import Foundation
import Darwin
#if SWIFT_PACKAGE
import SparkleBridge
#endif

enum EngineError: LocalizedError {
    case unavailable
    case failed(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .unavailable:
            return "The linked EnCap application library could not be loaded."
        case .failed(let message):
            return message
        case .invalidResponse:
            return "The linked EnCap application library returned an invalid response."
        }
    }
}

struct TranscriptionAvailability: Decodable, Sendable {
    var available: Bool
    var reason: String?
}

struct ArtworkOptimizationResponse: Decodable, Sendable {
    let path: String
    let format: String
    let inputBytes: UInt64
    let outputBytes: UInt64
    let bytesSaved: UInt64
    let optimized: Bool

    var url: URL { URL(fileURLWithPath: path) }
}

/// Copied, versioned events from the linked worker.
struct EngineProgress: Decodable, Sendable {
    var event: String
    var stage: String?
    var phase: String?
    var message: String?
    var completedBytes: Int64?
    var totalBytes: Int64?
    var fraction: Double?

    var status: String {
        let detail = message ?? stage ?? phase ?? "Working locally…"
        if let completedBytes, let totalBytes, totalBytes > 0 {
            return "\(detail) · \(ByteCountFormatter.string(fromByteCount: completedBytes, countStyle: .file)) / \(ByteCountFormatter.string(fromByteCount: totalBytes, countStyle: .file))"
        }
        if let fraction, fraction.isFinite {
            return "\(detail) · \(Int(min(1, max(0, fraction)) * 100))%"
        }
        return detail
    }
}

final class EngineClient: @unchecked Sendable {
    private let operationCondition = NSCondition()
    private final class Operation {
        var job: LinkedApplication.Job?
        var cancellationRequested = false
    }
    private var operations: [UUID: Operation] = [:]
    private var closing = false
    private let operationPreparationHook: @Sendable () -> Void
    init() { operationPreparationHook = {} }
    #if DEBUG
    /// Deterministic lifecycle seam; never present in distributable builds.
    init(operationPreparationHook: @escaping @Sendable () -> Void) {
        self.operationPreparationHook = operationPreparationHook
    }
    #endif
    var hasActiveOperations: Bool {
        operationCondition.lock()
        defer { operationCondition.unlock() }
        return !operations.isEmpty
    }
    let sessionDirectory = FileManager.default.temporaryDirectory
        .appendingPathComponent("encap-native-session-\(UUID().uuidString)", isDirectory: true)

    func cleanup(project: ProjectDocument) {
        guard let path = project.workingDir else { return }
        let directory = URL(fileURLWithPath: path).standardizedFileURL
        guard directory.deletingLastPathComponent().resolvingSymlinksInPath()
            == sessionDirectory.resolvingSymlinksInPath() else { return }
        try? FileManager.default.removeItem(at: directory)
    }

    func cleanupSession() {
        try? FileManager.default.removeItem(at: sessionDirectory)
    }

    func cancelCurrentOperation() {
        operationCondition.lock()
        let jobs = operations.values.compactMap { operation -> LinkedApplication.Job? in
            operation.cancellationRequested = true
            return operation.job
        }
        operationCondition.unlock()
        jobs.forEach { $0.cancel() }
    }

    /// Cooperative cancellation never destroys a library worker. Await all cleanup.
    func drain() async {
        await Task.detached { [self] in waitForOperations() }.value
    }

    private func waitForOperations() {
        operationCondition.lock()
        defer { operationCondition.unlock() }
        while !operations.isEmpty { operationCondition.wait() }
    }

    private func beginShutdown() -> [LinkedApplication.Job] {
        operationCondition.lock()
        defer { operationCondition.unlock() }
        closing = true
        return operations.values.compactMap { operation in
            operation.cancellationRequested = true
            return operation.job
        }
    }

    func shutdown() async {
        beginShutdown().forEach { $0.cancel() }
        await drain()
    }

    /// Reserve and count work before loading any native code. Shutdown waits
    /// for preparing operations too, and cancels them before execution starts.
    private func reserve(_ id: UUID) throws {
        operationCondition.lock()
        defer { operationCondition.unlock() }
        guard !closing else { throw CancellationError() }
        operations[id] = Operation()
        EnCapLinkedWorkStarted()
    }

    private func checkPreparation(_ id: UUID) throws {
        operationCondition.lock()
        defer { operationCondition.unlock() }
        guard !closing, let operation = operations[id], !operation.cancellationRequested else {
            throw CancellationError()
        }
    }

    private func attach(_ job: LinkedApplication.Job, id: UUID) throws {
        operationCondition.lock()
        let operation = operations[id]
        operation?.job = job
        let cancelled = closing || operation == nil || operation?.cancellationRequested == true
        operationCondition.unlock()
        if cancelled { job.cancel(); throw CancellationError() }
    }

    private func cancel(_ id: UUID) {
        operationCondition.lock()
        let operation = operations[id]
        operation?.cancellationRequested = true
        let job = operation?.job
        operationCondition.unlock()
        job?.cancel()
    }

    private func finish(_ id: UUID) {
        operationCondition.lock()
        if operations.removeValue(forKey: id) != nil { EnCapLinkedWorkFinished() }
        operationCondition.broadcast()
        operationCondition.unlock()
    }

    func waveform(path: String) async throws -> WaveformResponse {
        try decode(WaveformResponse.self, from: await run(["waveform", "--", path], priority: .utility))
    }

    func inspect(folder: URL) async throws -> ProjectDocument {
        try decode(ProjectDocument.self, from: await run(["inspect", folder.path]))
    }

    func inspect(files: [URL]) async throws -> ProjectDocument {
        try decode(ProjectDocument.self, from: await run(["inspect-files", "--"] + files.map(\.path)))
    }

    func open(project: URL) async throws -> ProjectDocument {
        try FileManager.default.createDirectory(
            at: sessionDirectory, withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        return try decode(ProjectDocument.self, from: await run([
            "open", project.path, "--extraction-parent", sessionDirectory.path
        ]))
    }

    func save(_ project: ProjectDocument, to destination: URL) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["save", payload.path, destination.path])
        return try decode(PathResponse.self, from: data).url
    }

    func export(_ project: ProjectDocument, to destination: URL) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["export", payload.path, destination.path])
        return try decode(PathResponse.self, from: data).url
    }

    func optimizeArtwork(_ project: ProjectDocument, image: URL, to destination: URL) async throws -> ArtworkOptimizationResponse {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        return try decode(ArtworkOptimizationResponse.self, from: await run([
            "optimize-artwork", payload.path, image.path, destination.path
        ]))
    }

    func exportVideo(_ project: ProjectDocument, to destination: URL) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["export-video", payload.path, destination.path])
        return try decode(PathResponse.self, from: data).url
    }

    func previewVideo(_ project: ProjectDocument, chapterID: String, to destination: URL) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["preview-video", payload.path, destination.path, "--chapter-id", chapterID], priority: .utility)
        return try decode(PathResponse.self, from: data).url
    }

    func videoPresets() async throws -> [VideoPreset] {
        try decode([VideoPreset].self, from: await run(["video-presets"]))
    }

    func videoCapabilities() async throws -> VideoCapabilities {
        try decode(VideoCapabilities.self, from: await run(["video-capabilities"]))
    }

    func providers() async throws -> [TranscriptionProvider] {
        try decode([TranscriptionProvider].self, from: await run(["providers"]))
    }

    func models() async throws -> [TranscriptionModelInfo] {
        try decode([TranscriptionModelInfo].self, from: await run(["models"]))
    }

    func transcriptionStatus() async throws -> TranscriptionAvailability {
        try decode(TranscriptionAvailability.self, from: await run(["transcription-status"]))
    }

    func installModel(id: String, progress: (@Sendable (EngineProgress) -> Void)? = nil) async throws -> TranscriptionModelInfo {
        try decode(TranscriptionModelInfo.self, from: await run(["install-model", id], progress: progress))
    }

    func importModel(id: String, from source: URL, progress: (@Sendable (EngineProgress) -> Void)? = nil) async throws -> TranscriptionModelInfo {
        try decode(TranscriptionModelInfo.self, from: await run(["import-model", id, source.path], progress: progress))
    }

    func removeModel(id: String) async throws -> TranscriptionModelInfo {
        try decode(TranscriptionModelInfo.self, from: await run(["remove-model", id]))
    }

    func transcribe(
        _ project: ProjectDocument,
        providerID: String,
        wordTimestamps: Bool,
        language: String = "",
        alignmentModelID: String = "",
        progress: (@Sendable (EngineProgress) -> Void)? = nil
    ) async throws -> [TranscriptSegment] {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        var arguments = ["transcribe", payload.path, providerID]
        if wordTimestamps { arguments.append("--word-timestamps") }
        if !language.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            arguments += ["--language", language]
        }
        if !alignmentModelID.isEmpty { arguments += ["--alignment-model", alignmentModelID] }
        let data = try await run(arguments, progress: progress)
        return try decode([TranscriptSegment].self, from: data)
    }

    func realign(_ project: ProjectDocument, modelID: String, language: String,
                 progress: (@Sendable (EngineProgress) -> Void)? = nil) async throws -> [TranscriptSegment] {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        var arguments = ["realign", payload.path, modelID]
        if !language.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            arguments += ["--language", language]
        }
        return try decode([TranscriptSegment].self, from: await run(arguments, progress: progress))
    }

    func exportTranscript(
        _ project: ProjectDocument,
        to destination: URL,
        format: String
    ) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["export-transcript", payload.path, destination.path, format])
        return try decode(PathResponse.self, from: data).url
    }

    func exportCaptions(_ project: ProjectDocument, to destination: URL, format: String) async throws -> URL {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["export-captions", payload.path, destination.path, format])
        return try decode(PathResponse.self, from: data).url
    }

    func saveRecovery(_ project: ProjectDocument) async throws {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        _ = try await run(["save-recovery", payload.path])
    }

    func loadRecovery() async throws -> ProjectDocument? {
        try decode(RecoveryResponse.self, from: await run(["load-recovery"])).project
    }

    func clearRecovery() async throws {
        _ = try await run(["clear-recovery"])
    }

    private struct PathResponse: Decodable {
        let path: String
        var url: URL { URL(fileURLWithPath: path) }
    }

    private struct RecoveryResponse: Decodable {
        let project: ProjectDocument?
    }

    private func temporaryPayload(for project: ProjectDocument) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("encap-native-\(UUID().uuidString).json")
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        try encoder.encode(project).write(to: url, options: .atomic)
        return url
    }

    private func decode<Value: Decodable>(_ type: Value.Type, from data: Data) throws -> Value {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw EngineError.invalidResponse
        }
    }

    private func run(_ arguments: [String], priority: TaskPriority = .userInitiated,
                     progress: (@Sendable (EngineProgress) -> Void)? = nil) async throws -> Data {
        let request = try Self.applicationRequest(arguments)
        let id = UUID()
        try reserve(id)
        defer { finish(id) }
        return try await withTaskCancellationHandler {
            let output = try await Task.detached(priority: priority) { [self] in
                operationPreparationHook()
                try checkPreparation(id)
                let job = try LinkedApplication.Job()
                try attach(job, id: id)
                return try job.execute(request, progress: progress)
            }.value
            // A successful native result confirms publication. Cancellation
            // arriving after that commit cannot turn it into a failed operation.
            return output
        } onCancel: { self.cancel(id) }
    }

    #if DEBUG
    func linkedOperationForTesting(_ arguments: [String], progress: (@Sendable (EngineProgress) -> Void)? = nil) async throws -> Data {
        try await run(arguments, progress: progress)
    }
    #endif

    /// Built-in package qualification client. Native work stays on its worker;
    /// no SwiftUI/AppStore is created and the process waits through cleanup.
    static func diagnosticOperation(_ arguments: [String]) -> Int32 {
        // Only the standalone diagnostic mode redirects process-wide stdout.
        // Provider diagnostics go to stderr; preserve one pristine JSON stream.
        fflush(stdout)
        let outputDescriptor = dup(STDOUT_FILENO)
        guard outputDescriptor >= 0, dup2(STDERR_FILENO, STDOUT_FILENO) >= 0 else {
            if outputDescriptor >= 0 { close(outputDescriptor) }
            return 1
        }
        let output = FileHandle(fileDescriptor: outputDescriptor, closeOnDealloc: false)
        defer { fflush(stdout); _ = dup2(outputDescriptor, STDOUT_FILENO); close(outputDescriptor) }
        let completed = DispatchSemaphore(value: 0)
        let result = DiagnosticResult()
        let previousInterrupt = signal(SIGINT, SIG_IGN)
        let previousTerminate = signal(SIGTERM, SIG_IGN)
        let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        interrupt.setEventHandler { result.cancel() }
        terminate.setEventHandler { result.cancel() }
        interrupt.resume(); terminate.resume()
        defer {
            interrupt.cancel(); terminate.cancel()
            signal(SIGINT, previousInterrupt); signal(SIGTERM, previousTerminate)
        }
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                let request = try applicationRequest(arguments)
                let job = try LinkedApplication.Job()
                result.register(job)
                result.store(.success(try job.execute(request, progress: nil)))
            } catch { result.store(.failure(error)) }
            completed.signal()
        }
        completed.wait()
        do {
            switch result.load() {
            case .success(let bytes):
                try output.write(contentsOf: bytes + Data([10]))
                return 0
            case .failure(let error):
                let bytes = try JSONSerialization.data(withJSONObject: ["error": error.localizedDescription])
                try output.write(contentsOf: bytes + Data([10]))
                return 1
            }
        } catch { return 1 }
    }

    private final class DiagnosticResult: @unchecked Sendable {
        private let lock = NSLock()
        private var value: Result<Data, Error> = .failure(EngineError.invalidResponse)
        private var job: LinkedApplication.Job?
        private var cancellationRequested = false
        func register(_ active: LinkedApplication.Job) {
            lock.lock(); job = active; let cancelled = cancellationRequested; lock.unlock()
            if cancelled { active.cancel() }
        }
        func cancel() {
            lock.lock(); cancellationRequested = true; let active = job; lock.unlock()
            active?.cancel()
        }
        func store(_ result: Result<Data, Error>) {
            lock.lock(); value = result; job = nil; lock.unlock()
        }
        func load() -> Result<Data, Error> { lock.lock(); defer { lock.unlock() }; return value }
    }

    /// Host transport fields are translated to the EnCAP facade, never Core JSON.
    static func applicationRequest(_ arguments: [String]) throws -> Data {
        guard let operation = arguments.first else { throw EngineError.invalidResponse }
        let fields: [String: [String]] = [
            "inspect": ["folder"], "waveform": ["file"], "inspect-files": ["files"],
            "edit-audio": ["payload", "edits"], "open": ["project"],
            "save": ["payload", "project"], "export": ["payload", "output"],
            "export-video": ["payload", "output"], "inspect-artwork": ["image"],
            "optimize-artwork": ["payload", "image", "output"],
            "preview-video": ["payload", "output"],
            "export-transcript": ["payload", "output", "format"],
            "export-captions": ["payload", "output", "format"],
            "transcribe": ["payload", "provider"], "realign": ["payload", "model"],
            "install-model": ["model"], "remove-model": ["model"], "verify-model": ["model"],
            "import-model": ["model", "source"], "save-recovery": ["payload"],
            "build-info": [], "startup": [], "video-presets": [], "video-capabilities": [],
            "transcription-status": [], "providers": [], "models": [],
            "load-recovery": [], "clear-recovery": [], "validate-tools": [], "validate-compatibility-tools": []
        ]
        guard let names = fields[operation] else { throw EngineError.failed("Unknown application operation: \(operation)") }
        let allowedOptions: [String: Set<String>] = [
            "open": ["extraction-parent"], "preview-video": ["chapter-id"],
            "export-video": ["render-mode"], "transcribe": ["word-timestamps", "language", "alignment-model"],
            "realign": ["language"]
        ]
        var request: [String: Any] = ["schema_version": 1, "operation": operation]
        var positional: [String] = []
        var index = 1
        var literal = false
        while index < arguments.count {
            let argument = arguments[index]
            if argument == "--" && !literal { literal = true; index += 1; continue }
            if !literal && argument.hasPrefix("--") {
                let option = String(argument.dropFirst(2))
                let key = option.replacingOccurrences(of: "-", with: "_")
                guard allowedOptions[operation]?.contains(option) == true, request[key] == nil else { throw EngineError.invalidResponse }
                if option == "word-timestamps" { request[key] = true }
                else {
                    index += 1
                    guard index < arguments.count else { throw EngineError.invalidResponse }
                    request[key] = arguments[index]
                }
            } else { positional.append(argument) }
            index += 1
        }
        if operation == "inspect-files" {
            guard !positional.isEmpty else { throw EngineError.invalidResponse }
            request["files"] = positional
        } else {
            guard positional.count == names.count else { throw EngineError.invalidResponse }
            for (name, value) in zip(names, positional) { request[name] = value }
        }
        let bytes = try JSONSerialization.data(withJSONObject: request)
        guard bytes.count <= 65_536 else { throw EngineError.failed("The operation request exceeds the application interface limit.") }
        return bytes
    }
}

/// Only the packaged application library is loaded in production. SDK and PATH
/// discovery cannot substitute an unauthenticated media runtime.
private final class LinkedApplication: @unchecked Sendable {
    typealias Version = @convention(c) () -> UInt32
    typealias Create = @convention(c) () -> UInt64
    typealias Release = @convention(c) (UInt64) -> Int32
    typealias Length = @convention(c) (UInt64) -> Int
    typealias Copy = @convention(c) (UInt64, UnsafeMutablePointer<UInt8>?, Int) -> Int
    typealias Callback = @convention(c) (UnsafeMutableRawPointer?, UnsafePointer<UInt8>?, Int) -> Void
    typealias Execute = @convention(c) (UInt64, UInt64, UnsafePointer<UInt8>?, Int, Callback?, UnsafeMutableRawPointer?) -> UInt64
    let library: UnsafeMutableRawPointer
    let create: Create
    let token: Create
    let cancel: Release
    let release: Release
    let length: Length
    let copy: Copy
    let execute: Execute

    // Rust TLS destructors and provider caches may outlive an individual call.
    // Keep the successful native module resident until process exit.
    static let shared: Result<LinkedApplication, Error> = Result { try LinkedApplication() }

    private init() throws {
        var path = Bundle.main.privateFrameworksURL?.appendingPathComponent("libencap_app.dylib").path
        #if DEBUG
        if let override = ProcessInfo.processInfo.environment["ENCAP_APP_LIBRARY"], override.hasPrefix("/") { path = override }
        #endif
        guard let path, let library = dlopen(path, RTLD_NOW | RTLD_LOCAL) else { throw EngineError.unavailable }
        self.library = library
        func symbol<T>(_ name: String, as type: T.Type) throws -> T {
            guard let pointer = dlsym(library, name) else { throw EngineError.unavailable }
            return unsafeBitCast(pointer, to: type)
        }
        do {
            let version = try symbol("encap_app_abi_version", as: Version.self)
            let schema = try symbol("encap_app_schema_version", as: Version.self)
            guard version() == 1, schema() == 1 else { throw EngineError.failed("Unsupported EnCap application ABI.") }
            create = try symbol("encap_app_create", as: Create.self)
            token = try symbol("encap_app_cancel_create", as: Create.self)
            cancel = try symbol("encap_app_cancel", as: Release.self)
            release = try symbol("encap_app_release", as: Release.self)
            length = try symbol("encap_app_buffer_len", as: Length.self)
            copy = try symbol("encap_app_buffer_copy", as: Copy.self)
            execute = try symbol("encap_app_execute_json", as: Execute.self)
        } catch { dlclose(library); throw error }
    }
    final class Job: @unchecked Sendable {
        let api: LinkedApplication
        let app: UInt64
        let token: UInt64
        init() throws {
            api = try LinkedApplication.shared.get()
            app = api.create()
            token = api.token()
            guard app != 0, token != 0 else {
                if app != 0 { _ = api.release(app) }
                if token != 0 { _ = api.release(token) }
                throw EngineError.unavailable
            }
        }
        deinit { _ = api.release(token); _ = api.release(app) }
        func cancel() { _ = api.cancel(token) }
        func execute(_ request: Data, progress: (@Sendable (EngineProgress) -> Void)?) throws -> Data {
            let box = ProgressBox(progress)
            let context = Unmanaged.passUnretained(box).toOpaque()
            let result = request.withUnsafeBytes { bytes in
                api.execute(app, token, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count,
                    { context, bytes, count in
                        guard let context, let bytes, count > 0, count <= 1_048_576 else { return }
                        // The native callback span is borrowed. Data copies it before dispatch.
                        let data = Data(bytes: bytes, count: count)
                        let box = Unmanaged<ProgressBox>.fromOpaque(context).takeUnretainedValue()
                        let decoder = JSONDecoder()
                        decoder.keyDecodingStrategy = .convertFromSnakeCase
                        if let event = try? decoder.decode(EngineProgress.self, from: data) { box.progress?(event) }
                    }, context)
            }
            withExtendedLifetime(box) {}
            guard result != 0 else { throw EngineError.invalidResponse }
            defer { _ = api.release(result) }
            let size = api.length(result)
            guard size > 0, size <= 64 * 1024 * 1024 else { throw EngineError.invalidResponse }
            var data = Data(count: size)
            let copied = data.withUnsafeMutableBytes { api.copy(result, $0.bindMemory(to: UInt8.self).baseAddress, $0.count) }
            guard copied == size,
                  let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  envelope["schema_version"] as? Int == 1, let ok = envelope["ok"] as? Bool else { throw EngineError.invalidResponse }
            guard ok else {
                let error = envelope["error"] as? [String: Any]
                throw EngineError.failed(error?["detail"] as? String ?? "The linked operation failed.")
            }
            guard let value = envelope["result"] else { throw EngineError.invalidResponse }
            return try JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed])
        }
    }
    private final class ProgressBox {
        let progress: (@Sendable (EngineProgress) -> Void)?
        init(_ progress: (@Sendable (EngineProgress) -> Void)?) { self.progress = progress }
    }
}
