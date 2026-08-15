import Foundation
import Speech

struct OutputSegment: Codable {
    let start_seconds: Double
    let duration_seconds: Double
    let text: String
}

struct OutputDocument: Codable {
    let locale: String
    let segments: [OutputSegment]
}

enum HelperError: Error, LocalizedError {
    case usage
    case permission(String)
    case unavailable(String)
    case recognition(String)

    var errorDescription: String? {
        switch self {
        case .usage:
            return "Usage: apple-transcriber --input /path/to/audio"
        case .permission(let message), .unavailable(let message), .recognition(let message):
            return message
        }
    }
}

func inputPath(from arguments: [String]) throws -> String {
    guard let flagIndex = arguments.firstIndex(of: "--input"),
          flagIndex + 1 < arguments.count else {
        throw HelperError.usage
    }
    return arguments[flagIndex + 1]
}

func requestSpeechAuthorization() throws {
    let semaphore = DispatchSemaphore(value: 0)
    var status = SFSpeechRecognizer.authorizationStatus()
    if status == .notDetermined {
        SFSpeechRecognizer.requestAuthorization { result in
            status = result
            semaphore.signal()
        }
        while semaphore.wait(timeout: .now()) != .success {
            RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
        }
    }
    guard status == .authorized else {
        throw HelperError.permission(
            "Speech Recognition permission is required. Enable EnCap in System Settings > Privacy & Security > Speech Recognition."
        )
    }
}

func transcribe(url: URL) throws -> OutputDocument {
    try requestSpeechAuthorization()
    guard let recognizer = SFSpeechRecognizer() else {
        throw HelperError.unavailable("Apple Speech does not support the current language.")
    }
    guard recognizer.supportsOnDeviceRecognition else {
        throw HelperError.unavailable(
            "Apple On-Device transcription is not installed or supported for \(recognizer.locale.identifier)."
        )
    }

    let request = SFSpeechURLRecognitionRequest(url: url)
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false
    if #available(macOS 13.0, *) {
        request.addsPunctuation = true
    }

    let semaphore = DispatchSemaphore(value: 0)
    var finalResult: SFSpeechRecognitionResult?
    var finalError: Error?
    let task = recognizer.recognitionTask(with: request) { result, error in
        if let result = result, result.isFinal {
            finalResult = result
            semaphore.signal()
        } else if let error = error {
            finalError = error
            semaphore.signal()
        }
    }
    while semaphore.wait(timeout: .now()) != .success {
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
    }
    task.finish()

    if let error = finalError {
        throw HelperError.recognition(error.localizedDescription)
    }
    guard let result = finalResult else {
        throw HelperError.recognition("Apple Speech did not return a final transcription.")
    }
    let segments = result.bestTranscription.segments.map { segment in
        OutputSegment(
            start_seconds: segment.timestamp,
            duration_seconds: segment.duration,
            text: segment.substring
        )
    }
    return OutputDocument(locale: recognizer.locale.identifier, segments: segments)
}

do {
    let path = try inputPath(from: CommandLine.arguments)
    let document = try transcribe(url: URL(fileURLWithPath: path))
    let encoder = JSONEncoder()
    let data = try encoder.encode(document)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
} catch {
    let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}
