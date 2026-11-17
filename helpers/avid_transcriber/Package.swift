// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "EnCAPAVIDTranscriber",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "EnCAPTranscription", type: .dynamic, targets: ["EnCAPTranscription"]),
        .executable(name: "avid-transcriber", targets: ["AVIDTranscriber"]),
    ],
    dependencies: [
        .package(path: "../../vendor/avid-core-transcription/apple/AVIDTranscription"),
        .package(path: "../../vendor/avid-core-transcription/apple/AVIDTranscriptionEngines"),
        .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.33.0"),
    ],
    targets: [
        .target(name: "EnCAPTranscription", dependencies: [
            .product(name: "AVIDTranscription", package: "AVIDTranscription"),
            .product(name: "AVIDTranscriptionEngines", package: "AVIDTranscriptionEngines"),
            .product(name: "MLX", package: "mlx-swift"),
        ]),
        .executableTarget(name: "AVIDTranscriber", dependencies: ["EnCAPTranscription"]),
        .testTarget(name: "AVIDTranscriberTests", dependencies: ["EnCAPTranscription"]),
    ]
)
