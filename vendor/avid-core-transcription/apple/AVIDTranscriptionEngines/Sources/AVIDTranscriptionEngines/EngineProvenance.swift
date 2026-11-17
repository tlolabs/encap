/// Exact source pins of the SDK components compiled by this package. Keep these
/// aligned with Package.swift/Package.resolved; no host/runtime lookup is needed.
enum EngineProvenance {
    static let whisperKit = ["argmax-oss-swift": "9f99b5cb6a907730543823ad271b82532782a899"]
    static let fluidAudio = ["fluidaudio": "ee78635d23d52379117554ba72358b65a0612447"]
    static let qwen = [
        "mlx-audio-swift": "df2a2546705f50ca267037702a34cd63aa6e35a6",
        "mlx-swift": "7ede4fd6d05f63305c1c0ebf4f8c1909a637c574",
    ]
}
