import Foundation

enum EngineError: LocalizedError {
    case unavailable
    case failed(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .unavailable:
            return "The EnCap audio engine could not be found."
        case .failed(let message):
            return message
        case .invalidResponse:
            return "The EnCap audio engine returned an invalid response."
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

/// Versioned stderr events never change the single final JSON value on stdout.
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
    private struct ErrorResponse: Decodable { let error: String }
    private let processLock = NSLock()
    private var currentProcesses: [ObjectIdentifier: Process] = [:]
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
        processLock.lock()
        let processes = Array(currentProcesses.values)
        processLock.unlock()
        for process in processes where process.isRunning { process.terminate() }
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
        let invocation = try invocation(arguments: arguments)
        return try await Self.runProcess(
            executable: invocation.executable,
            arguments: invocation.arguments,
            environment: invocation.environment,
            priority: priority,
            progress: progress,
            processChanged: { [weak self] process, started in
                self?.updateCurrentProcess(process, started: started)
            }
        )
    }

    private func updateCurrentProcess(_ process: Process, started: Bool) {
        processLock.lock()
        if started {
            currentProcesses[ObjectIdentifier(process)] = process
        } else {
            currentProcesses.removeValue(forKey: ObjectIdentifier(process))
        }
        processLock.unlock()
    }

    // Drain both pipes while the child runs. Waiting first deadlocks once either
    // pipe fills (large projects/transcripts or verbose encoder diagnostics).
    static func runProcess(
        executable: URL,
        arguments: [String],
        environment: [String: String],
        priority: TaskPriority = .userInitiated,
        progress: (@Sendable (EngineProgress) -> Void)? = nil,
        processChanged: (@Sendable (Process, Bool) -> Void)? = nil
    ) async throws -> Data {
        let cancellation = ProcessCancellation()
        return try await withTaskCancellationHandler {
            let output = try await Task.detached(priority: priority) {
                let process = Process()
                let stdout = Pipe()
                let stderr = Pipe()
                process.executableURL = executable
                process.arguments = arguments
                process.environment = environment
                process.standardOutput = stdout
                process.standardError = stderr
                try cancellation.start(process)
                processChanged?(process, true)
                defer { processChanged?(process, false) }
                let errorReader = Task.detached {
                    Self.readDiagnostics(stderr.fileHandleForReading, progress: progress)
                }
                let output = stdout.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let errorOutput = await errorReader.value
                if process.terminationStatus != 0 {
                    let decoder = JSONDecoder()
                    if let response = try? decoder.decode(ErrorResponse.self, from: output) {
                        throw EngineError.failed(response.error)
                    }
                    let detail = String(
                        data: errorOutput,
                        encoding: .utf8
                    )?.trimmingCharacters(in: .whitespacesAndNewlines)
                    throw EngineError.failed(detail?.isEmpty == false ? detail! : "The EnCap audio engine failed.")
                }
                return output
            }.value
            try Task.checkCancellation()
            return output
        } onCancel: {
            cancellation.cancel()
        }
    }

    // Read chunks continuously; split complete event lines and retain a bounded
    // diagnostic tail for failures. Neither a verbose backend nor a split UTF-8
    // event may fill the child's pipe or consume unbounded diagnostic memory.
    static func readDiagnostics(_ handle: FileHandle,
                                progress: (@Sendable (EngineProgress) -> Void)?) -> Data {
        var pending = Data()
        var tail = Data()
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty { break }
            tail.append(chunk)
            if tail.count > 65_536 { tail = Data(tail.suffix(65_536)) }
            pending.append(chunk)
            while let newline = pending.firstIndex(of: 10) {
                let line = Data(pending[..<newline])
                pending.removeSubrange(...newline)
                if let event = try? decoder.decode(EngineProgress.self, from: line), event.event == "progress" {
                    progress?(event)
                }
            }
            if pending.count > 65_536 { pending.removeAll(keepingCapacity: true) }
        }
        if let event = try? decoder.decode(EngineProgress.self, from: pending), event.event == "progress" {
            progress?(event)
        }
        return tail
    }

    private func invocation(arguments: [String]) throws -> (
        executable: URL,
        arguments: [String],
        environment: [String: String]
    ) {
        let environment = ProcessInfo.processInfo.environment
        if let bundled = Bundle.main.executableURL?
            .deletingLastPathComponent()
            .appendingPathComponent("encap-engine"),
           FileManager.default.isExecutableFile(atPath: bundled.path) {
            return (bundled, arguments, environment)
        }

        guard let sourceRoot = environment["ENCAP_SOURCE_ROOT"], !sourceRoot.isEmpty else {
            throw EngineError.unavailable
        }
        let root = URL(fileURLWithPath: sourceRoot)
        let releaseEngine = root.appendingPathComponent("target/release/encap-engine")
        let debugEngine = root.appendingPathComponent("target/debug/encap-engine")
        guard let engine = [releaseEngine, debugEngine].first(where: {
            FileManager.default.isExecutableFile(atPath: $0.path)
        }) else { throw EngineError.unavailable }
        return (engine, arguments, environment)
    }
}

// Serialize launch against task cancellation so a cancelled preview cannot
// launch a new child after its view has already moved to another chapter.
private final class ProcessCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    private var process: Process?

    func start(_ process: Process) throws {
        lock.lock()
        defer { lock.unlock() }
        guard !cancelled else { throw CancellationError() }
        try process.run()
        self.process = process
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let active = process
        lock.unlock()
        if let active, active.isRunning { active.terminate() }
    }
}
