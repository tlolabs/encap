import Foundation
import XCTest
@testable import AVIDTranscription

/// Routing is immutable and per-request, so concurrently executing tests share no mutable fixture state.
private final class FixtureHTTPProtocol: URLProtocol {
    private static let payload = Data("abcdef".utf8)
    private static let streamingPayload = Data(repeating: 0x61, count: 65_536)

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host == "huggingface.co" && request.url?.path.hasPrefix("/tests/") == true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let url = request.url else { return }
        let route = url.lastPathComponent
        var status = 200
        var headers = [String: String]()
        var body = Self.payload
        switch route {
        case "resume":
            guard request.value(forHTTPHeaderField: "Range") == "bytes=2-" else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            status = 206
            headers = ["Content-Range": "bytes 2-5/6", "Content-Length": "4"]
            body = Self.payload.dropFirst(2)
        case "restart":
            guard request.value(forHTTPHeaderField: "Range") == "bytes=2-" else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            headers = ["Content-Length": "6"]
        case "bad-range":
            status = 206
            headers = ["Content-Range": "bytes 1-5/6", "Content-Length": "5"]
            body = Self.payload.dropFirst()
        case "bad-range-end":
            status = 206
            headers = ["Content-Range": "bytes 2-3/6", "Content-Length": "4"]
            body = Self.payload.dropFirst(2)
        case "bad-range-double-dash":
            status = 206
            headers = ["Content-Range": "bytes 2--5/6", "Content-Length": "4"]
            body = Self.payload.dropFirst(2)
        case "bad-range-plus-end":
            status = 206
            headers = ["Content-Range": "bytes 2-+5/6", "Content-Length": "4"]
            body = Self.payload.dropFirst(2)
        case "oversize": body = Data("abcdefg".utf8)
        case "truncated":
            headers = ["Content-Length": "6"]
            body = Self.payload.prefix(3)
        case "status":
            status = 503
            headers = ["Content-Length": "0"]
            body = Data()
        case "cancel":
            status = 206
            headers = ["Content-Range": "bytes 2-65535/65536", "Content-Length": "65534"]
            body = Self.streamingPayload.dropFirst(2).prefix(32_768)
        case "resume-large":
            guard let range = request.value(forHTTPHeaderField: "Range"),
                  range.hasPrefix("bytes="), range.hasSuffix("-"),
                  let offset = Int(range.dropFirst(6).dropLast()), offset > 0, offset < Self.streamingPayload.count else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            status = 206
            headers = ["Content-Range": "bytes \(offset)-65535/65536", "Content-Length": String(65_536 - offset)]
            body = Self.streamingPayload.dropFirst(offset)
        default:
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        if route != "cancel" { client?.urlProtocolDidFinishLoading(self) }
    }

    override func stopLoading() { }
}

@MainActor
final class HTTPTransportTests: XCTestCase {
    private let payload = Data("abcdef".utf8)

    private func destination() throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("avid-http-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return directory.appendingPathComponent("weights.bin")
    }

    private func transport() -> HTTPModelDownloadTransport {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [FixtureHTTPProtocol.self]
        return HTTPModelDownloadTransport(configuration: configuration)
    }

    private func url(_ route: String) -> URL {
        URL(string: "https://huggingface.co/tests/\(route)")!
    }

    func testRangeResumeAppendsValidatedRemainder() async throws {
        let file = try destination()
        try payload.prefix(2).write(to: file)
        try await transport().download(from: url("resume"), to: file, expectedSize: 6) { _ in }
        XCTAssertEqual(try Data(contentsOf: file), payload)
    }

    func testIgnoredRangeRestartsRatherThanAppending() async throws {
        let file = try destination()
        try payload.prefix(2).write(to: file)
        try await transport().download(from: url("restart"), to: file, expectedSize: 6) { _ in }
        XCTAssertEqual(try Data(contentsOf: file), payload)
    }

    func testInvalidRangeAndInconsistentEndDoNotAppend() async throws {
        for route in ["bad-range", "bad-range-end", "bad-range-double-dash", "bad-range-plus-end"] {
            let file = try destination()
            try payload.prefix(2).write(to: file)
            do {
                try await transport().download(from: url(route), to: file, expectedSize: 6) { _ in }
                XCTFail("An invalid Content-Range must be rejected: \(route)")
            } catch ModelStoreError.invalidResponse { }
            XCTAssertEqual(try Data(contentsOf: file), payload.prefix(2))
        }
    }

    func testOversizedTruncatedAndErrorResponsesFailWithoutPublishing() async throws {
        for route in ["oversize", "truncated", "status"] {
            let file = try destination()
            do {
                try await transport().download(from: url(route), to: file, expectedSize: 6) { _ in }
                XCTFail("Incomplete or invalid response must fail: \(route)")
            } catch { }
            let bytes = try Data(contentsOf: file)
            XCTAssertLessThanOrEqual(bytes.count, 6)
            if route == "truncated" { XCTAssertEqual(bytes, payload.prefix(3)) }
            if route == "status" { XCTAssertTrue(bytes.isEmpty) }
        }
    }

    func testCancellationPreservesPartialAndActualHTTPResumesIt() async throws {
        let file = try destination()
        let streamingPayload = Data(repeating: 0x61, count: 65_536)
        try streamingPayload.prefix(2).write(to: file)
        let transport = transport()
        let events = AsyncStream<Int64>.makeStream()
        defer { events.continuation.finish() }
        let requestURL = url("cancel")
        let task = Task {
            defer { events.continuation.finish() }
            try await transport.download(from: requestURL, to: file, expectedSize: 65_536) {
                events.continuation.yield($0)
            }
        }
        var iterator = events.stream.makeAsyncIterator()
        while let bytes = await iterator.next() {
            if bytes >= 2 { break }
        }
        task.cancel()
        do {
            try await task.value
            XCTFail("Cancelling an active HTTP transfer must throw")
        } catch is CancellationError { }
        let partial = try Data(contentsOf: file)
        XCTAssertGreaterThanOrEqual(partial.count, 2)
        XCTAssertLessThan(partial.count, streamingPayload.count)
        XCTAssertEqual(partial, streamingPayload.prefix(partial.count))
        try await transport.download(from: url("resume-large"), to: file, expectedSize: 65_536) { _ in }
        XCTAssertEqual(try Data(contentsOf: file), streamingPayload)
    }

    func testTransportRejectsUnapprovedOriginsBeforeOpeningDestination() async throws {
        for invalidURL in ["http://huggingface.co/tests/status", "https://example.com/tests/status", "https://user:password@huggingface.co/tests/status"] {
            let file = try destination()
            do {
                try await transport().download(from: URL(string: invalidURL)!, to: file, expectedSize: 6) { _ in }
                XCTFail("Only anonymous Hugging Face HTTPS origins are permitted")
            } catch ModelStoreError.invalidResponse { }
            XCTAssertFalse(FileManager.default.fileExists(atPath: file.path))
        }
    }
}
