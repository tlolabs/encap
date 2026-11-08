import Foundation

/// Anonymous HTTPS file downloads only; this does not call an inference API or send user audio.
public struct HTTPModelDownloadTransport: ModelDownloadTransport {
    private let configuration: URLSessionConfiguration
    public init() { configuration = .ephemeral }
    init(configuration: URLSessionConfiguration) { self.configuration = configuration }

    public func download(from url: URL, to destination: URL, expectedSize: Int64,
                         progress: @escaping @Sendable (Int64) -> Void) async throws {
        guard url.scheme == "https", url.host == "huggingface.co", url.user == nil, url.password == nil else {
            throw ModelStoreError.invalidResponse("Only public Hugging Face HTTPS downloads are supported")
        }
        try await HTTPFileTransfer(url: url, destination: destination,
            expectedSize: expectedSize, configuration: configuration, progress: progress).run()
    }
}

/// Delegate callbacks are serialized and mutable state is protected by the lock. Cancellation
/// may arrive from any executor. Responses stream straight to disk rather than into model-sized Data.
private final class HTTPFileTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let lock = NSRecursiveLock()
    private let url: URL
    private let destination: URL
    private let expectedSize: Int64
    private let configuration: URLSessionConfiguration
    private let progress: @Sendable (Int64) -> Void
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var continuation: CheckedContinuation<Void, any Error>?
    private var handle: FileHandle?
    private var offset: Int64 = 0
    private var receivedResponse = false
    private var cancelled = false
    private var finished = false

    init(url: URL, destination: URL, expectedSize: Int64, configuration: URLSessionConfiguration,
         progress: @escaping @Sendable (Int64) -> Void) {
        self.url = url; self.destination = destination
        self.expectedSize = expectedSize; self.progress = progress
        self.configuration = configuration
    }

    func run() async throws {
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            try await withCheckedThrowingContinuation { continuation in
                start(continuation)
            }
        } onCancel: { self.cancel() }
    }

    private func start(_ continuation: CheckedContinuation<Void, any Error>) {
        lock.lock(); defer { lock.unlock() }
        self.continuation = continuation
        guard !cancelled else { finish(CancellationError()); return }
        do {
            let attributes = try? FileManager.default.attributesOfItem(atPath: destination.path)
            if let attributes {
                guard attributes[.type] as? FileAttributeType == .typeRegular else {
                    throw ModelStoreError.unsafePath(destination.path)
                }
                offset = (attributes[.size] as? NSNumber)?.int64Value ?? 0
            } else {
                guard FileManager.default.createFile(atPath: destination.path, contents: nil) else {
                    throw CocoaError(.fileWriteUnknown)
                }
            }
            handle = try FileHandle(forWritingTo: destination)
            if offset > expectedSize { try handle?.truncate(atOffset: 0); offset = 0 }
            // Empty files still need no network transfer; their expected digest is checked by the store.
            if offset == expectedSize { finish(nil); return }
            try handle?.seekToEnd()
            var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 120)
            request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
            request.setValue("AVIDTranscription/1", forHTTPHeaderField: "User-Agent")
            if offset > 0 { request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
            let configuration = self.configuration.copy() as! URLSessionConfiguration
            configuration.urlCache = nil
            configuration.httpCookieStorage = nil
            configuration.urlCredentialStorage = nil
            configuration.timeoutIntervalForResource = 24 * 60 * 60
            let queue = OperationQueue()
            queue.maxConcurrentOperationCount = 1
            let session = URLSession(configuration: configuration, delegate: self, delegateQueue: queue)
            self.session = session
            let task = session.dataTask(with: request)
            self.task = task
            task.resume()
        } catch { finish(error) }
    }

    private func cancel() {
        lock.lock(); defer { lock.unlock() }
        cancelled = true
        task?.cancel()
        // If start has not installed a continuation yet, it will observe cancelled.
        if continuation != nil { finish(CancellationError()) }
    }

    private func finish(_ error: (any Error)?) {
        guard !finished else { return }
        finished = true
        try? handle?.close(); handle = nil
        let continuation = self.continuation
        self.continuation = nil
        task?.cancel(); task = nil
        session?.invalidateAndCancel(); session = nil
        if let error { continuation?.resume(throwing: error) }
        else { continuation?.resume() }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void) {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { completionHandler(.cancel); return }
        do {
            guard let response = response as? HTTPURLResponse else {
                throw ModelStoreError.invalidResponse("Missing HTTP response")
            }
            switch response.statusCode {
            case 200:
                // Upstream ignored the Range header: replace, never append a second full model.
                try handle?.truncate(atOffset: 0)
                try handle?.seek(toOffset: 0)
                offset = 0
            case 206:
                let contentRange = response.value(forHTTPHeaderField: "Content-Range") ?? ""
                let expectedRange = "bytes \(offset)-\(expectedSize - 1)/\(expectedSize)"
                guard contentRange == expectedRange else {
                    throw ModelStoreError.invalidResponse("Invalid resumed Content-Range: \(contentRange)")
                }
            default:
                throw ModelStoreError.invalidResponse("HTTP \(response.statusCode) for \(url.lastPathComponent)")
            }
            if response.expectedContentLength >= 0,
               response.expectedContentLength != expectedSize - offset {
                throw ModelStoreError.invalidResponse("Content-Length does not match pinned artifact size")
            }
            receivedResponse = true
            progress(offset)
            completionHandler(.allow)
        } catch {
            completionHandler(.cancel)
            finish(error)
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return }
        do {
            guard receivedResponse, Int64(data.count) <= expectedSize - offset else {
                throw ModelStoreError.invalidResponse("Response exceeds pinned artifact size")
            }
            try handle?.write(contentsOf: data)
            offset += Int64(data.count)
            progress(offset)
        } catch { finish(error) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return }
        if cancelled { finish(CancellationError()) }
        else if let error { finish(error) }
        else if !receivedResponse || offset != expectedSize {
            finish(ModelStoreError.sizeMismatch(destination.lastPathComponent, expected: expectedSize, actual: offset))
        } else { finish(nil) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        // Hugging Face redirects large weights to its HTTPS storage CDN. Never allow downgrade,
        // embedded credentials, cookies or authorization headers on those requests.
        guard request.url?.scheme == "https", request.url?.user == nil, request.url?.password == nil else {
            completionHandler(nil); return
        }
        var anonymous = request
        anonymous.setValue(nil, forHTTPHeaderField: "Authorization")
        anonymous.setValue(nil, forHTTPHeaderField: "Cookie")
        completionHandler(anonymous)
    }
}
