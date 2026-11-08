@preconcurrency import AVFoundation
import AVIDTranscription
import Foundation

/// Reads an audio track from either an audio file or a movie. Only the current
/// inference window is retained; sample positions remain on the input's clock.
final class PCMChunkReader {
    static let sampleRate = 16_000
    private let reader: AVAssetReader
    private let output: AVAssetReaderTrackOutput
    private var pending: [Float] = []
    private var consumedSamples = 0
    private var finished = false
    let startSeconds: Double
    let durationSeconds: Double

    init(url: URL, startSeconds: Double = 0, endSeconds: Double? = nil) async throws {
        guard url.isFileURL, startSeconds.isFinite, startSeconds >= 0 else {
            throw TranscriptionError.invalidInput("audio input must be a local file with a valid range")
        }
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .audio).first else {
            throw TranscriptionError.invalidInput("the recording has no audio track")
        }
        let duration = try await asset.load(.duration).seconds
        let end = endSeconds ?? duration
        guard duration.isFinite, end.isFinite, end > startSeconds,
              end <= duration + 0.05 else {
            throw TranscriptionError.invalidInput("audio range lies outside the recording")
        }
        self.startSeconds = startSeconds
        durationSeconds = min(end, duration) - startSeconds
        reader = try AVAssetReader(asset: asset)
        output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: Double(Self.sampleRate),
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else {
            throw TranscriptionError.invalidInput("unsupported recording audio format")
        }
        reader.add(output)
        reader.timeRange = CMTimeRange(
            start: CMTime(seconds: startSeconds, preferredTimescale: 16_000),
            duration: CMTime(seconds: durationSeconds, preferredTimescale: 16_000)
        )
        guard reader.startReading() else {
            throw reader.error ?? TranscriptionError.unavailable("could not decode the audio track")
        }
    }

    deinit { reader.cancelReading() }

    /// A pause near the end of the window reduces words split across calls.
    func next(maxSeconds: Double = 30, preferPause: Bool = true) throws -> (samples: [Float], start: Double)? {
        try Task.checkCancellation()
        let limit = max(1, Int(maxSeconds * Double(Self.sampleRate)))
        while pending.count < limit && !finished {
            try Task.checkCancellation()
            guard let buffer = output.copyNextSampleBuffer() else {
                finished = true
                if reader.status == .failed {
                    throw reader.error ?? TranscriptionError.unavailable("audio decoding failed")
                }
                break
            }
            // AVAssetReader normally materializes edit-list gaps as silence.
            // Validate that behavior instead of silently discarding any PTS gap
            // or overlap a container/decoder might return. Allow sub-millisecond
            // resampler rounding; a discontinuity must not shift every caption.
            let presentation = CMSampleBufferGetPresentationTimeStamp(buffer).seconds
            let expected = startSeconds + Double(consumedSamples + pending.count) / Double(Self.sampleRate)
            guard presentation.isFinite, abs(presentation - expected) <= 0.001 else {
                throw TranscriptionError.invalidInput("audio presentation timestamps are discontinuous; export a continuous audio track before transcribing")
            }
            guard let block = CMSampleBufferGetDataBuffer(buffer) else {
                throw TranscriptionError.invalidInput("audio decoder did not return PCM samples")
            }
            let bytes = CMBlockBufferGetDataLength(block)
            guard bytes.isMultiple(of: MemoryLayout<Float>.size) else {
                throw TranscriptionError.invalidInput("invalid float PCM sample data")
            }
            var samples = [Float](repeating: 0, count: bytes / MemoryLayout<Float>.size)
            let status = samples.withUnsafeMutableBytes {
                CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: bytes, destination: $0.baseAddress!)
            }
            guard status == kCMBlockBufferNoErr, samples.allSatisfy(\.isFinite) else {
                throw TranscriptionError.invalidInput("audio decoder returned invalid PCM data")
            }
            pending.append(contentsOf: samples)
        }
        guard !pending.isEmpty else { return nil }
        var count = min(limit, pending.count)
        if preferPause && count == limit && maxSeconds >= 10 {
            let width = Self.sampleRate / 10
            let lowerBound = max(width, count - Self.sampleRate * 5)
            var lowest = Double.infinity
            var best = count
            for end in stride(from: lowerBound, through: count, by: width) {
                let energy = pending[(end - width)..<end].reduce(0.0) { $0 + Double($1 * $1) }
                if energy < lowest { lowest = energy; best = end }
            }
            // Split only at a quiet interval, otherwise preserve maximum context.
            if lowest / Double(width) < 0.0001 { count = best }
        }
        let start = startSeconds + Double(consumedSamples) / Double(Self.sampleRate)
        let samples = Array(pending.prefix(count))
        pending.removeFirst(count)
        consumedSamples += count
        return (samples, start)
    }
}

enum LocalModelFiles {
    static func require(_ names: [String], in directory: URL) throws {
        guard directory.isFileURL else { throw TranscriptionError.invalidInput("model directory must be local") }
        for name in names where !FileManager.default.fileExists(atPath: directory.appendingPathComponent(name).path) {
            throw TranscriptionError.unavailable("installed model is missing \(name)")
        }
    }

    /// The upstream Qwen loader generates tokenizer.json. Stage metadata privately
    /// so model loading never modifies the verified installation. Large weights
    /// are read-only hard links, with a copy fallback when volumes differ.
    static func stageQwen(_ source: URL) throws -> URL {
        let names = ["config.json", "tokenizer_config.json", "vocab.json", "merges.txt", "model.safetensors"]
        try require(names, in: source)
        // Both supported, pinned Qwen models have one exact weights file. Do not
        // glob the caller's directory: upstream merges every safetensors file,
        // which could let an unverified extra shard replace verified parameters.
        let files = names.map { source.appendingPathComponent($0) }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("avid-qwen-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        do {
            for file in files {
                let destination = directory.appendingPathComponent(file.lastPathComponent)
                if file.pathExtension == "safetensors" {
                    do { try FileManager.default.linkItem(at: file, to: destination) }
                    catch { try FileManager.default.copyItem(at: file, to: destination) }
                } else {
                    try FileManager.default.copyItem(at: file, to: destination)
                }
            }
            return directory
        } catch {
            try? FileManager.default.removeItem(at: directory)
            throw error
        }
    }
}
