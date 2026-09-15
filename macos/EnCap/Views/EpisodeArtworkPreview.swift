import AppKit
import SwiftUI

struct EpisodeArtworkPreview: View {
    let path: String?
    @State private var image: NSImage?

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(.quaternary.opacity(0.4))
                if let image {
                    Image(nsImage: image)
                        .resizable()
                        .scaledToFit()
                        .padding(4)
                } else {
                    VStack(spacing: 8) {
                        Image(systemName: "photo")
                            .font(.largeTitle)
                        Text(path == nil ? "Album artwork" : "Preview unavailable")
                            .font(.caption)
                            .multilineTextAlignment(.center)
                    }
                    .foregroundStyle(.secondary)
                    .padding(8)
                }
            }
            .frame(width: 144, height: 144)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(.quaternary))
            .accessibilityLabel(image == nil ? "No artwork preview" : "Episode album artwork preview")
        }
        .task(id: path) {
            image = path.flatMap { NSImage(contentsOfFile: $0) }
        }
    }
}
