import Foundation
import Darwin
import WhisperKit

private struct OutputSegment: Codable {
    let startSeconds: Double
    let endSeconds: Double
    let text: String

    enum CodingKeys: String, CodingKey {
        case startSeconds = "start_seconds"
        case endSeconds = "end_seconds"
        case text
    }
}

private struct OutputDocument: Codable {
    let segments: [OutputSegment]
}

private struct Options {
    let modelPath: String
    let tokenizerPath: String
    let inputPath: String
    let language: String?

    static func parse(_ arguments: [String]) throws -> Options {
        var values: [String: String] = [:]
        var index = 0
        while index < arguments.count {
            let option = arguments[index]
            guard ["--model", "--tokenizer", "--input", "--language"].contains(option) else {
                throw HelperError.usage("Unknown option: \(option)")
            }
            guard index + 1 < arguments.count else {
                throw HelperError.usage("Missing value for \(option)")
            }
            values[option] = arguments[index + 1]
            index += 2
        }
        guard let modelPath = values["--model"],
              let tokenizerPath = values["--tokenizer"],
              let inputPath = values["--input"]
        else {
            throw HelperError.usage(
                "Usage: whisperkit-transcriber --model DIR --tokenizer DIR --input AUDIO [--language CODE]"
            )
        }
        return Options(
            modelPath: modelPath,
            tokenizerPath: tokenizerPath,
            inputPath: inputPath,
            language: values["--language"]
        )
    }
}

private enum HelperError: LocalizedError {
    case usage(String)
    case missingPath(String)

    var errorDescription: String? {
        switch self {
        case let .usage(message), let .missingPath(message):
            return message
        }
    }
}

@main
struct WhisperKitTranscriber {
    static func main() async {
        do {
            let options = try Options.parse(Array(CommandLine.arguments.dropFirst()))
            try requireDirectory(options.modelPath, label: "model")
            try requireDirectory(options.tokenizerPath, label: "tokenizer")
            for filename in ["tokenizer.json", "tokenizer_config.json", "config.json"] {
                try requireReadableFile(
                    URL(fileURLWithPath: options.tokenizerPath).appendingPathComponent(filename).path,
                    label: "tokenizer file"
                )
            }
            guard FileManager.default.isReadableFile(atPath: options.inputPath) else {
                throw HelperError.missingPath("The input audio is not readable: \(options.inputPath)")
            }

            // This helper exists only to run a complete local package. Prevent
            // WhisperKit from contacting the Hub if local tokenizer parsing fails.
            setenv("HF_ENDPOINT", "http://127.0.0.1:9", 1)
            let config = WhisperKitConfig(
                modelFolder: options.modelPath,
                tokenizerFolder: URL(fileURLWithPath: options.tokenizerPath),
                verbose: false,
                prewarm: false,
                load: true,
                download: false
            )
            let whisperKit = try await WhisperKit(config)
            let decodingOptions = DecodingOptions(
                language: options.language,
                usePrefillPrompt: options.language != nil,
                detectLanguage: options.language == nil,
                skipSpecialTokens: true
            )
            let results = try await whisperKit.transcribe(
                audioPath: options.inputPath,
                decodeOptions: decodingOptions
            )
            let segments = results
                .flatMap(\.segments)
                .compactMap { segment -> OutputSegment? in
                    let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !text.isEmpty else { return nil }
                    return OutputSegment(
                        startSeconds: Double(segment.start),
                        endSeconds: Double(max(segment.end, segment.start)),
                        text: text
                    )
                }
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            let payload = try encoder.encode(OutputDocument(segments: segments))
            FileHandle.standardOutput.write(payload)
            FileHandle.standardOutput.write(Data([0x0A]))
        } catch {
            let message = "whisperkit-transcriber: \(error.localizedDescription)\n"
            FileHandle.standardError.write(Data(message.utf8))
            exit(EXIT_FAILURE)
        }
    }

    private static func requireDirectory(_ path: String, label: String) throws {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else {
            throw HelperError.missingPath("The \(label) directory is unavailable: \(path)")
        }
    }

    private static func requireReadableFile(_ path: String, label: String) throws {
        guard FileManager.default.isReadableFile(atPath: path) else {
            throw HelperError.missingPath("The \(label) is unavailable: \(path)")
        }
    }
}
