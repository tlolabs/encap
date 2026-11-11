import AVIDTranscription
import AVIDTranscriptionEngines
import Darwin
import Dispatch
import Foundation

@main
struct BridgeCommand {
    static func main() async {
        // Preserve a dedicated protocol descriptor. Any SDK prints go to stderr,
        // leaving exactly one machine-readable JSON value on the original stdout.
        let descriptor = dup(STDOUT_FILENO)
        guard descriptor >= 0, dup2(STDERR_FILENO, STDOUT_FILENO) >= 0 else { exit(1) }
        let protocolOutput = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        let parentProcess = getppid()
        let operation = Task { try await execute(Array(CommandLine.arguments.dropFirst())) }
        // A host crash may kill the Rust owner before it can forward a signal.
        // Cancel this operation only when its own original parent disappears.
        let parentMonitor = DispatchSource.makeTimerSource(queue: .global())
        parentMonitor.schedule(deadline: .now() + 1, repeating: 1)
        parentMonitor.setEventHandler { @Sendable in
            if getppid() != parentProcess { operation.cancel() }
        }
        parentMonitor.resume()
        signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
        let signals = [SIGINT, SIGTERM].map { number in
            let source = DispatchSource.makeSignalSource(signal: number, queue: .global())
            source.setEventHandler { @Sendable in operation.cancel() }
            source.resume()
            return source
        }
        defer { parentMonitor.cancel(); signals.forEach { $0.cancel() } }
        do {
            let data = try await operation.value
            guard !operation.isCancelled else { throw CancellationError() }
            protocolOutput.write(data + Data([10]))
        } catch is CancellationError {
            writeError("The AVID operation was cancelled safely. A running Core ML or Metal kernel may finish before cancellation is observed.", to: protocolOutput)
            exit(130)
        } catch {
            writeError(error.localizedDescription, to: protocolOutput)
            exit(1)
        }
    }

    static func execute(_ arguments: [String]) async throws -> Data {
        let options = try Options(arguments)
        if options.command == "subtitles" {
            // Exporting saved segments needs neither model acquisition nor an
            // installation/cache lease. Core owns subtitle validation/formatting.
            let input = try options.file("--transcript")
            let text = try segmentSubtitles(Data(contentsOf: input), format: options.required("--format"))
            try Task.checkCancellation()
            return try encode(text)
        }
        let catalog = try ModelCatalog.bundled()
        let cacheOverride = options["--cache"] ?? ProcessInfo.processInfo.environment["ENCAP_AVID_MODEL_CACHE"]
        let directory = cacheOverride.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? ModelStore.defaultDirectory
        let store = try ModelStore(catalog: catalog, rootDirectory: directory)
        switch options.command {
        case "status":
            return try encode(Status(protocolVersion: 1, defaultModelID: catalog.defaultModelID,
                                     cacheDirectory: directory.path, platform: "apple-silicon-macos14"))
        case "models":
            var models: [ModelWire] = []
            for model in catalog.models {
                models.append(ModelWire(model, present: try await store.isPresent(id: model.id), defaultID: catalog.defaultModelID))
            }
            return try encode(models)
        case "providers":
            var providers: [ProviderWire] = []
            for model in catalog.models where model.role == .recognizer {
                if try await store.isPresent(id: model.id) {
                    providers.append(.init(id: model.id, name: model.displayName,
                        detail: "AVID Core · \(model.engine.rawValue) · local files; verified before inference"))
                }
            }
            return try encode(providers)
        case "install-model", "remove-model", "import-model", "verify-model":
            let model = try catalog.model(id: options.required("--model"))
            switch options.command {
            case "install-model": _ = try await store.install(id: model.id, progress: reportDownload)
            case "remove-model": try await store.remove(id: model.id)
            case "import-model":
                let source = URL(fileURLWithPath: try options.required("--source"), isDirectory: true)
                _ = try await store.importModel(id: model.id, from: source, progress: reportDownload)
            default: _ = try await store.installedModel(id: model.id, progress: reportDownload)
            }
            return try encode(ModelWire(model, present: try await store.isPresent(id: model.id),
                verified: options.command != "remove-model", defaultID: catalog.defaultModelID))
        case "transcribe":
            let audio = try options.file("--input")
            let model = try catalog.model(id: options["--model"] ?? catalog.defaultModelID)
            guard model.role == .recognizer else { throw BridgeError.invalid("Choose a recognition model for transcription.") }
            try validateLanguage(options.language, supported: model.recognitionLanguages)
            let recognizer: any TranscriptionProvider
            switch model.engine {
            case .whisperKit: recognizer = WhisperKitProvider()
            case .fluidAudio: recognizer = FluidAudioProvider()
            case .mlx: recognizer = QwenASRProvider()
            }
            report(.init(stage: "verifying", modelID: model.id))
            // The shared lease spans verification, loading, recognition, and awaited
            // provider cleanup. Inference never attempts an implicit download.
            var result = try await store.withInstalledModel(id: model.id) { installed in
                try await recognizer.transcribe(.init(audioURL: audio, modelID: model.id,
                    modelDirectory: installed.directory, language: options.language,
                    sourceStartSeconds: options.offset), progress: reportInference)
            }
            let recognitionSegments = options["--alignment-model"] == nil ? nil : result.segments
            var alignmentProvenance: TranscriptWire.Provenance?
            if let alignID = options["--alignment-model"] {
                result = try await align(result, audio: audio, modelID: alignID, store: store, catalog: catalog, options: options)
                let descriptor = try catalog.model(id: alignID)
                alignmentProvenance = result.alignmentProvenance.map { .init($0, descriptor: descriptor) }
            }
            try Task.checkCancellation()
            return try encode(TranscriptWire(result, recognitionSegments: recognitionSegments,
                recognitionProvenance: .init(result.provenance, descriptor: model),
                alignmentProvenance: alignmentProvenance))
        case "realign":
            let audio = try options.file("--input")
            let input = try options.file("--transcript")
            let inputRecord = try JSONDecoder().decode(TranscriptWire.self, from: Data(contentsOf: input))
            let transcript = try inputRecord.core()
            let descriptor = try catalog.model(id: options["--model"] ?? "qwen3-forced-aligner-0.6b-4bit")
            let result = try await align(transcript, audio: audio,
                modelID: descriptor.id,
                store: store, catalog: catalog, options: options)
            try Task.checkCancellation()
            return try encode(TranscriptWire(result, recognitionProvenance: inputRecord.provenance,
                alignmentProvenance: result.alignmentProvenance.map { .init($0, descriptor: descriptor) }))
        case "captions":
            let format = try options.required("--format")
            guard ["srt", "vtt"].contains(format) else {
                throw BridgeError.invalid("Choose srt or vtt for caption export.")
            }
            let input = try options.file("--transcript")
            let transcript = try JSONDecoder().decode(TranscriptWire.self, from: Data(contentsOf: input)).core()
            let cues = try CaptionBuilder.cues(from: transcript)
            let text = try format == "srt" ? CaptionExporter.srt(cues) : CaptionExporter.webVTT(cues)
            try Task.checkCancellation()
            return try encode(text)
        default: throw BridgeError.invalid("Unsupported AVID bridge command.")
        }
    }

    private static func align(_ transcript: Transcript, audio: URL, modelID: String,
                              store: ModelStore, catalog: ModelCatalog, options: Options) async throws -> Transcript {
        let model = try catalog.model(id: modelID)
        guard model.role == .aligner, model.engine == .mlx else {
            throw BridgeError.invalid("Choose a supported alignment model.")
        }
        guard let language = options.language ?? transcript.language else {
            throw BridgeError.invalid("Choose a language before aligning a transcript without a detected language.")
        }
        try validateLanguage(language, supported: model.timingLanguages)
        report(.init(stage: "verifying", modelID: model.id))
        return try await store.withInstalledModel(id: model.id) { installed in
            try await QwenAlignmentProvider().align(.init(audioURL: audio, modelID: model.id,
                modelDirectory: installed.directory, transcript: transcript, language: language,
                sourceStartSeconds: options.offset), progress: reportInference)
        }
    }

    static func validateLanguage(_ language: String?, supported: [String]) throws {
        guard let language else { return }
        let code = language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            .replacingOccurrences(of: "_", with: "-").split(separator: "-").first.map(String.init) ?? ""
        guard supported.contains(code) else { throw TranscriptionError.unsupportedLanguage(language) }
    }

    static func segmentSubtitles(_ data: Data, format: String) throws -> String {
        guard ["srt", "vtt"].contains(format) else {
            throw BridgeError.invalid("Choose srt or vtt for subtitle export.")
        }
        let input = try JSONDecoder().decode(SegmentSubtitleInput.self, from: data)
        let cues = try input.segments.map { segment in
            let speaker = segment.speaker.trimmingCharacters(in: .whitespacesAndNewlines)
            let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
            // Preserve segment boundaries and host speaker labels; this path
            // deliberately skips word-based CaptionBuilder regrouping. Core
            // escapes markup/folds newlines and requires ordered, positive cues.
            return try CaptionCue(startSeconds: segment.startSeconds, endSeconds: segment.endSeconds,
                text: speaker.isEmpty ? text : "\(speaker): \(text)")
        }
        return try format == "srt" ? CaptionExporter.srt(cues) : CaptionExporter.webVTT(cues)
    }

    private static let reportDownload: ModelProgressHandler = { report(.init($0)) }
    private static let reportInference: @Sendable (TranscriptionProgress) -> Void = {
        report(.init(stage: $0.stage, fraction: $0.fraction))
    }
    private static func report(_ value: ProgressWire) {
        if let data = try? encode(value) { FileHandle.standardError.write(data + Data([10])) }
    }
    private static func writeError(_ message: String, to output: FileHandle) {
        if let data = try? encode(ErrorWire(error: message)) { output.write(data + Data([10])) }
    }
    static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(value)
    }
}

private struct ErrorWire: Encodable { let error: String }
private struct SegmentSubtitleInput: Decodable {
    let segments: [Segment]
    struct Segment: Decodable {
        let startSeconds: Double
        let endSeconds: Double
        let text: String
        let speaker: String
        enum CodingKeys: String, CodingKey {
            case startSeconds = "start_seconds", endSeconds = "end_seconds", text, speaker
        }
    }
}
private struct Status: Encodable {
    let protocolVersion: Int
    let defaultModelID: String
    let cacheDirectory: String
    let platform: String
    enum CodingKeys: String, CodingKey {
        case protocolVersion = "protocol_version", defaultModelID = "default_model_id"
        case cacheDirectory = "cache_directory", platform
    }
}
