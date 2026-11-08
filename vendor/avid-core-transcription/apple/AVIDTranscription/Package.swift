// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "AVIDTranscription",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "AVIDTranscription", targets: ["AVIDTranscription"]),
        .executable(name: "avid-transcription", targets: ["avid-transcription"]),
    ],
    targets: [
        .target(name: "AVIDTranscription", resources: [.process("Resources")]),
        .executableTarget(name: "avid-transcription", dependencies: ["AVIDTranscription"]),
        .testTarget(name: "AVIDTranscriptionTests", dependencies: ["AVIDTranscription"]),
    ]
)
