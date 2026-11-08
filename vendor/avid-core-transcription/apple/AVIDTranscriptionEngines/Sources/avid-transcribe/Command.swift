import AVIDTranscription
import AVIDTranscriptionEngines
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
        catch is CancellationError { stderr("Cancelled.\n"); exit(130) }
        catch { stderr("\(error.localizedDescription)\n"); exit(1) }
    }

    private static func execute(_ arguments: [String]) async throws {
        guard let command = arguments.first, !["--help", "-h", "help"].contains(command) else {
            print(help); return
        }
        guard ["transcribe", "align"].contains(command) else { throw CommandError.usage }
        let options = try Options(Array(arguments.dropFirst()))
        let expectedCount = command == "transcribe" ? 2 : 3
        guard options.positional.count == expectedCount else { throw CommandError.usage }
        let audio = URL(fileURLWithPath: options.positional[0]).standardizedFileURL
        let output = URL(fileURLWithPath: options.positional[expectedCount - 1]).standardizedFileURL
        guard output.pathExtension.lowercased() == "json" else {
            throw CommandError.message("Output must end in .json; export SRT/VTT using avid-transcription captions.")
        }
        guard !FileManager.default.fileExists(atPath: output.path) else {
            throw CommandError.message("Output already exists; choose a new transcript path.")
        }
        let catalog = try ModelCatalog.bundled()
        let store = try ModelStore(catalog: catalog, rootDirectory: options.cache)
        let modelID = options.model ?? (command == "align" ? "qwen3-forced-aligner-0.6b-4bit" : catalog.defaultModelID)
        let descriptor = try catalog.model(id: modelID)
        let result: Transcript
        if command == "transcribe" {
            guard descriptor.role == .recognizer else { throw CommandError.message("Select a recognition model.") }
            try validateLanguage(options.language, supported: descriptor.recognitionLanguages)
            _ = try await provision(descriptor, store: store, local: options.localModel, offline: options.offline)
            let recognizer: any TranscriptionProvider
            switch descriptor.engine {
            case .whisperKit: recognizer = WhisperKitProvider()
            case .fluidAudio: recognizer = FluidAudioProvider()
            case .mlx: recognizer = QwenASRProvider()
            }
            let transcript = try await store.withInstalledModel(id: modelID) { installed in
                let request = RecognitionRequest(audioURL: audio, modelID: modelID,
                    modelDirectory: installed.directory, language: options.language, sourceStartSeconds: options.offset)
                return try await recognizer.transcribe(request, progress: reportInference)
            }
            if let alignID = options.alignModel {
                let aligner = try catalog.model(id: alignID)
                result = try await align(transcript, audio: audio, descriptor: aligner, store: store,
                    options: options, local: options.localAligner)
            } else { result = transcript }
        } else {
            guard options.alignModel == nil, options.localAligner == nil else { throw CommandError.usage }
            let input = URL(fileURLWithPath: options.positional[1])
            let transcript = try JSONDecoder().decode(Transcript.self, from: Data(contentsOf: input))
            result = try await align(transcript, audio: audio, descriptor: descriptor, store: store,
                options: options, local: options.localModel)
        }
        try Task.checkCancellation()
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let data = try encoder.encode(result)
        // Publish a completed transcript atomically, without replacing concurrent writers or inputs.
        let staging = output.deletingLastPathComponent().appendingPathComponent(".avid-transcript-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: staging) }
        try data.write(to: staging, options: .withoutOverwriting)
        guard link(staging.path, output.path) == 0 else {
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
        stderr("\n")
        print(output.path)
    }

    private static func align(_ transcript: Transcript, audio: URL, descriptor: ModelDescriptor,
                              store: ModelStore, options: Options, local: URL?) async throws -> Transcript {
        guard descriptor.role == .aligner, descriptor.engine == .mlx else {
            throw CommandError.message("Select a supported alignment model.")
        }
        let language = options.language ?? transcript.language
        guard let language else { throw CommandError.message("Alignment requires --language when the transcript has no detected language.") }
        try validateLanguage(language, supported: descriptor.timingLanguages)
        _ = try await provision(descriptor, store: store, local: local, offline: options.offline)
        return try await store.withInstalledModel(id: descriptor.id) { installed in
            try await QwenAlignmentProvider().align(AlignmentRequest(audioURL: audio,
                modelID: descriptor.id, modelDirectory: installed.directory, transcript: transcript,
                language: language, sourceStartSeconds: options.offset), progress: reportInference)
        }
    }

    private static func provision(_ descriptor: ModelDescriptor, store: ModelStore,
                                  local: URL?, offline: Bool) async throws -> InstalledModel {
        if let local { return try await store.localModel(id: descriptor.id, directory: local) }
        if offline { return try await store.installedModel(id: descriptor.id, progress: reportDownload) }
        return try await store.install(id: descriptor.id, progress: reportDownload)
    }

    private static func validateLanguage(_ language: String?, supported: [String]) throws {
        guard let language else { return }
        let code = language.lowercased().replacingOccurrences(of: "_", with: "-").split(separator: "-").first.map(String.init) ?? language
        guard supported.contains(code) else { throw TranscriptionError.unsupportedLanguage(language) }
    }

    private static let reportDownload: ModelProgressHandler = { value in
        stderr(String(format: "\r%@ %.1f%% %@", value.phase.rawValue, value.fraction * 100, value.artifactPath ?? ""))
    }
    private static let reportInference: @Sendable (TranscriptionProgress) -> Void = { value in
        if let fraction = value.fraction { stderr(String(format: "\r%@ %.1f%%", value.stage, fraction * 100)) }
        else { stderr("\r\(value.stage)") }
    }
    private static func stderr(_ text: String) { FileHandle.standardError.write(Data(text.utf8)) }

    private static let help = """
    avid-transcribe transcribe AUDIO OUTPUT.json [OPTIONS]
    avid-transcribe align AUDIO INPUT.json OUTPUT.json [OPTIONS]
      --model ID              Recognition model, or alignment model for the align command
      --language CODE         Explicit language (otherwise detect during recognition)
      --align-model ID        Align the recognized text before writing it
      --cache DIRECTORY       Model cache (shared with avid-transcription)
      --local-model DIRECTORY Import a manually provisioned model, without network
      --local-aligner DIR     Local alignment model for --align-model
      --offline               Fail if a required model is not already installed
      --source-offset SECONDS Source clock offset if AUDIO is an extracted clip

    Default quality model: whisper-large-v3. First installation downloads directly from
    Hugging Face; inference always uses local files. Output must be a new .json path.
    Ctrl-C cancels; a Core ML/Metal operation in progress may finish before stopping.
    """
}

private struct Options: Sendable {
    var positional: [String] = []
    var model: String?
    var language: String?
    var alignModel: String?
    var localModel: URL?
    var localAligner: URL?
    var cache = ModelStore.defaultDirectory
    var offline = false
    var offset: Double = 0

    init(_ arguments: [String]) throws {
        var index = 0
        var flags = Set<String>()
        while index < arguments.count {
            let argument = arguments[index]
            if !argument.hasPrefix("--") { positional.append(argument); index += 1; continue }
            guard flags.insert(argument).inserted else { throw CommandError.usage }
            if argument == "--offline" { offline = true; index += 1; continue }
            guard index + 1 < arguments.count else { throw CommandError.usage }
            let value = arguments[index + 1]
            switch argument {
            case "--model": model = value
            case "--language": language = value
            case "--align-model": alignModel = value
            case "--cache": cache = URL(fileURLWithPath: value, isDirectory: true)
            case "--local-model": localModel = URL(fileURLWithPath: value, isDirectory: true)
            case "--local-aligner": localAligner = URL(fileURLWithPath: value, isDirectory: true)
            case "--source-offset":
                guard let number = Double(value), number.isFinite, number >= 0 else { throw CommandError.usage }
                offset = number
            default: throw CommandError.usage
            }
            index += 2
        }
        if localAligner != nil && alignModel == nil { throw CommandError.usage }
    }
}

private enum CommandError: Error, LocalizedError {
    case usage
    case message(String)
    var errorDescription: String? {
        switch self {
        case .usage: "Invalid arguments. Run avid-transcribe --help."
        case .message(let message): message
        }
    }
}
