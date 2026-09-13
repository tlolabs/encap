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

struct EngineClient: Sendable {
    private struct ErrorResponse: Decodable { let error: String }
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

    func inspect(folder: URL) async throws -> ProjectDocument {
        try decode(ProjectDocument.self, from: await run(["inspect", folder.path]))
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

    func providers() async throws -> [TranscriptionProvider] {
        try decode([TranscriptionProvider].self, from: await run(["providers"]))
    }

    func transcribe(_ project: ProjectDocument, providerID: String) async throws -> [TranscriptSegment] {
        let payload = try temporaryPayload(for: project)
        defer { try? FileManager.default.removeItem(at: payload) }
        let data = try await run(["transcribe", payload.path, providerID])
        return try decode([TranscriptSegment].self, from: data)
    }

    private struct PathResponse: Decodable {
        let path: String
        var url: URL { URL(fileURLWithPath: path) }
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

    private func run(_ arguments: [String]) async throws -> Data {
        let invocation = try invocation(arguments: arguments)
        return try await Self.runProcess(
            executable: invocation.executable,
            arguments: invocation.arguments,
            environment: invocation.environment
        )
    }

    // Drain both pipes while the child runs. Waiting first deadlocks once either
    // pipe fills (large projects/transcripts or verbose encoder diagnostics).
    static func runProcess(
        executable: URL, arguments: [String], environment: [String: String]
    ) async throws -> Data {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            let stdout = Pipe()
            let stderr = Pipe()
            process.executableURL = executable
            process.arguments = arguments
            process.environment = environment
            process.standardOutput = stdout
            process.standardError = stderr
            try process.run()
            let errorReader = Task.detached {
                stderr.fileHandleForReading.readDataToEndOfFile()
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
