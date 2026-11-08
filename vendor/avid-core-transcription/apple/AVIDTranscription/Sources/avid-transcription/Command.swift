import AVIDTranscription
import Darwin
import Dispatch
import Foundation

@main
struct Command {
    static func main() async {
        let arguments = Array(CommandLine.arguments.dropFirst())
        let operation = Task { try await execute(arguments) }
        signal(SIGINT, SIG_IGN)
        let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        interrupt.setEventHandler { operation.cancel() }
        interrupt.resume()
        defer { interrupt.cancel() }
        do { try await operation.value }
        catch is CancellationError { stderr("Cancelled. Partial downloads can be resumed.\n"); exit(130) }
        catch { stderr("\(error.localizedDescription)\n"); exit(1) }
    }

    private static func execute(_ rawArguments: [String]) async throws {
        var arguments = rawArguments
        var cache = ModelStore.defaultDirectory
        if let index = arguments.firstIndex(of: "--cache") {
            guard arguments.indices.contains(index + 1) else { throw CLIError.usage }
            cache = URL(fileURLWithPath: arguments[index + 1], isDirectory: true)
            arguments.removeSubrange(index...(index + 1))
        }
        guard let command = arguments.first else { print(help); return }
        if ["help", "--help", "-h"].contains(command) { print(help); return }
        let catalog = try ModelCatalog.bundled()
        let store = try ModelStore(catalog: catalog, rootDirectory: cache)
        switch command {
        case "models":
            guard arguments.count == 1 else { throw CLIError.usage }
            for model in catalog.models {
                let present = try await store.isPresent(id: model.id)
                let size = ByteCountFormatter.string(fromByteCount: model.downloadSizeBytes, countStyle: .file)
                print("\(model.id)\(model.id == catalog.defaultModelID ? " [default]" : "") — \(size), \(present ? "cached" : "not installed"), \(model.license.identifier)")
                print("  \(model.displayName); \(model.role.rawValue); \(model.recognitionLanguages.count) recognition / \(model.timingLanguages.count) timing languages")
            }
        case "install":
            guard arguments.count == 2 else { throw CLIError.usage }
            let model = try await store.install(id: arguments[1], progress: report)
            stderr("\n")
            print(model.directory.path)
        case "verify":
            guard arguments.count == 2 else { throw CLIError.usage }
            let model = try await store.installedModel(id: arguments[1], progress: report)
            stderr("\n")
            print(model.directory.path)
        case "import":
            guard arguments.count == 3 else { throw CLIError.usage }
            let model = try await store.importModel(id: arguments[1],
                from: URL(fileURLWithPath: arguments[2], isDirectory: true), progress: report)
            stderr("\n")
            print(model.directory.path)
        case "remove":
            guard arguments.count == 2 else { throw CLIError.usage }
            try await store.remove(id: arguments[1])
            print("Removed \(arguments[1])")
        case "captions":
            guard arguments.count == 3 else { throw CLIError.usage }
            let input = URL(fileURLWithPath: arguments[1]).standardizedFileURL
            let output = URL(fileURLWithPath: arguments[2]).standardizedFileURL
            guard input.resolvingSymlinksInPath() != output.resolvingSymlinksInPath() else {
                throw CLIError.message("Caption output must differ from transcript input")
            }
            let transcript = try JSONDecoder().decode(Transcript.self, from: Data(contentsOf: input))
            let cues = try CaptionBuilder.cues(from: transcript)
            let text: String
            switch output.pathExtension.lowercased() {
            case "srt": text = try CaptionExporter.srt(cues)
            case "vtt": text = try CaptionExporter.webVTT(cues)
            default: throw CLIError.message("Caption output must end in .srt or .vtt")
            }
            try Data(text.utf8).write(to: output, options: .atomic)
        default: throw CLIError.usage
        }
    }

    private static let report: ModelProgressHandler = { progress in
        stderr(String(format: "\r%@ %.1f%% %@", progress.phase.rawValue,
            progress.fraction * 100, progress.artifactPath ?? ""))
    }

    private static func stderr(_ text: String) { FileHandle.standardError.write(Data(text.utf8)) }

    private static let help = """
    avid-transcription [--cache DIRECTORY] COMMAND
      models                         List model sizes, capabilities, licenses and cache presence
      install MODEL                  Download pinned files directly from Hugging Face (Ctrl-C cancels)
      verify MODEL                   Verify cached files offline and print the model directory
      import MODEL DIRECTORY         Verify and copy a manually provisioned model folder
      remove MODEL                   Delete cached revisions and partial downloads
      captions TRANSCRIPT OUTPUT     Export a timed transcript JSON to .srt or .vtt

    Inference adapters and the transcription command are in ../AVIDTranscriptionEngines.
    """
}

private enum CLIError: Error, LocalizedError {
    case usage
    case message(String)
    var errorDescription: String? {
        switch self {
        case .usage: "Invalid arguments. Run avid-transcription --help."
        case .message(let message): message
        }
    }
}
