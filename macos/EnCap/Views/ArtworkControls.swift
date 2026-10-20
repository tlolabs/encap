import SwiftUI

struct ArtworkPathLabel: View {
    let path: String?
    let accessibilityName: String
    @State private var showsFullPath = false

    private var displayedPath: String {
        guard let path else { return "None" }
        return showsFullPath ? path : URL(fileURLWithPath: path).lastPathComponent
    }

    var body: some View {
        Button { showsFullPath.toggle() } label: {
            Text(displayedPath)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(path == nil)
        .accessibilityLabel(accessibilityName)
        .accessibilityValue(displayedPath)
        .help(path.map {
            "\($0)\nClick to show the \(showsFullPath ? "file name" : "full file path")."
        } ?? "Drop an image here or choose an artwork file.")
        .onChange(of: path) { _ in showsFullPath = false }
    }
}

struct ArtworkDropTarget: ViewModifier {
    let isEnabled: Bool
    let selectArtwork: (URL) -> Bool
    @State private var isTargeted = false

    func body(content: Content) -> some View {
        content
            .contentShape(Rectangle())
            .overlay {
                RoundedRectangle(cornerRadius: 5)
                    .stroke(Color.accentColor, lineWidth: 2)
                    .opacity(isTargeted && isEnabled ? 1 : 0)
                    .allowsHitTesting(false)
            }
            .dropDestination(for: URL.self) { urls, _ in
                guard isEnabled, urls.count == 1, let url = urls.first else { return false }
                return selectArtwork(url)
            } isTargeted: { isTargeted = $0 }
    }
}
