// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "EnCapNative",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "EnCap", targets: ["EnCap"]),
    ],
    targets: [
        .executableTarget(
            name: "EnCap",
            dependencies: ["SparkleBridge"],
            path: "EnCap",
            exclude: ["Resources"]
        ),
        .target(
            name: "SparkleBridge",
            path: "SparkleBridge",
            publicHeadersPath: "include",
            linkerSettings: [.linkedFramework("Foundation")]
        ),
        .testTarget(
            name: "EnCapTests",
            dependencies: ["EnCap"],
            path: "Tests"
        ),
    ]
)
