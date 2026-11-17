import Foundation
import MLX

/// MLX's public host resource setting avoids its executable-relative fallback.
/// The immutable module resource is selected once before any MLX provider loads.
private final class ModuleResourceAnchor: NSObject {}
enum MetalResources {
    private static let configuration: Result<Void, BridgeError> = {
        let resources = Bundle(for: ModuleResourceAnchor.self).resourceURL
        let bundle = resources.flatMap { Bundle(url: $0.appendingPathComponent("mlx-swift_Cmlx.bundle")) }
        guard let metal = bundle?.url(forResource: "default", withExtension: "metallib"),
              metal.isFileURL, FileManager.default.isReadableFile(atPath: metal.path) else {
            return .failure(.invalid("The packaged MLX Metal resource is missing; reinstall the linked transcription framework."))
        }
        GPU.metallib = metal
        return .success(())
    }()
    static func configure() throws { try configuration.get() }
}
