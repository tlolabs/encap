// swift-tools-version: 5.10

import PackageDescription

let package = Package(
    name: "encap-whisperkit-transcriber",
    platforms: [.macOS(.v14)],
    products: [
        .executable(
            name: "whisperkit-transcriber",
            targets: ["WhisperKitTranscriber"]
        ),
    ],
    dependencies: [
        .package(
            url: "https://github.com/argmaxinc/argmax-oss-swift.git",
            revision: "25c62997041c134b03ca82731ce2f6fd2cae1eb9"
        ),
    ],
    targets: [
        .executableTarget(
            name: "WhisperKitTranscriber",
            dependencies: [
                .product(name: "WhisperKit", package: "argmax-oss-swift"),
            ]
        ),
    ]
)
