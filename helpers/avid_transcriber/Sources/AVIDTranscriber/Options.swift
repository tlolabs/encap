import Foundation

enum BridgeError: Error, LocalizedError {
    case invalid(String)
    var errorDescription: String? { if case .invalid(let message) = self { message } else { nil } }
}

struct Options: Sendable {
    let command: String
    private(set) var values: [String: String] = [:]

    init(_ arguments: [String]) throws {
        guard let command = arguments.first else { throw BridgeError.invalid("An AVID bridge command is required.") }
        let allowed: Set<String>
        switch command {
        case "models", "providers", "status": allowed = ["--cache"]
        case "install-model", "remove-model", "verify-model": allowed = ["--cache", "--model"]
        case "import-model": allowed = ["--cache", "--model", "--source"]
        case "transcribe": allowed = ["--cache", "--model", "--input", "--language", "--alignment-model", "--source-offset"]
        case "realign": allowed = ["--cache", "--model", "--input", "--transcript", "--language", "--source-offset"]
        case "captions": allowed = ["--cache", "--transcript", "--format"]
        case "subtitles": allowed = ["--transcript", "--format"]
        default: throw BridgeError.invalid("Unknown AVID bridge command: \(command)")
        }
        self.command = command
        var index = 1
        while index < arguments.count {
            let key = arguments[index]
            guard allowed.contains(key), values[key] == nil, index + 1 < arguments.count else {
                throw BridgeError.invalid("Invalid or duplicate option: \(key)")
            }
            let value = arguments[index + 1]
            guard !value.isEmpty else { throw BridgeError.invalid("Empty value for \(key).") }
            values[key] = value
            index += 2
        }
        if let value = values["--source-offset"] {
            guard let offset = Double(value), offset.isFinite, offset >= 0 else {
                throw BridgeError.invalid("The source offset must be finite and nonnegative.")
            }
        }
    }

    subscript(_ name: String) -> String? { values[name] }
    func required(_ name: String) throws -> String {
        guard let value = values[name] else { throw BridgeError.invalid("Missing required option: \(name)") }
        return value
    }
    var offset: Double { values["--source-offset"].flatMap(Double.init) ?? 0 }
    var language: String? { values["--language"] }
    func file(_ name: String) throws -> URL {
        let file = URL(fileURLWithPath: try required(name)).standardizedFileURL
        guard let values = try? file.resourceValues(forKeys: [.isRegularFileKey]), values.isRegularFile == true else {
            throw BridgeError.invalid("The input file is missing or is not a regular file: \(file.path)")
        }
        return file
    }
}
