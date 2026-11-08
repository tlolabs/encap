// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "EnCAPAVIDTranscriber",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "avid-transcriber", targets: ["AVIDTranscriber"])],
    dependencies: [
        .package(path: "../../vendor/avid-core-transcription/apple/AVIDTranscription"),
        .package(path: "../../vendor/avid-core-transcription/apple/AVIDTranscriptionEngines"),
    ],
    targets: [
        .executableTarget(name: "AVIDTranscriber", dependencies: [
            .product(name: "AVIDTranscription", package: "AVIDTranscription"),
            .product(name: "AVIDTranscriptionEngines", package: "AVIDTranscriptionEngines"),
        ]),
        .testTarget(name: "AVIDTranscriberTests", dependencies: ["AVIDTranscriber"]),
    ]
)
