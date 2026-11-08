// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "AVIDTranscriptionEngines",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [
        .library(name: "AVIDTranscriptionEngines", targets: ["AVIDTranscriptionEngines"]),
        .executable(name: "avid-transcribe", targets: ["avid-transcribe"]),
    ],
    dependencies: [
        .package(path: "../AVIDTranscription"),
        .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", revision: "9f99b5cb6a907730543823ad271b82532782a899"),
        .package(url: "https://github.com/FluidInference/FluidAudio.git", revision: "ee78635d23d52379117554ba72358b65a0612447", traits: []),
        .package(url: "https://github.com/Blaizzy/mlx-audio-swift.git", revision: "df2a2546705f50ca267037702a34cd63aa6e35a6"),
        .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.33.0"),
    ],
    targets: [
        .target(name: "AVIDTranscriptionEngines", dependencies: [
            .product(name: "AVIDTranscription", package: "AVIDTranscription"),
            .product(name: "WhisperKit", package: "argmax-oss-swift"),
            .product(name: "FluidAudio", package: "FluidAudio"),
            .product(name: "MLXAudioSTT", package: "mlx-audio-swift"),
            .product(name: "MLX", package: "mlx-swift"),
        ]),
        .executableTarget(name: "avid-transcribe", dependencies: [
            "AVIDTranscriptionEngines",
            .product(name: "AVIDTranscription", package: "AVIDTranscription"),
        ]),
        .testTarget(name: "AVIDTranscriptionEnginesTests", dependencies: ["AVIDTranscriptionEngines"]),
    ]
)
