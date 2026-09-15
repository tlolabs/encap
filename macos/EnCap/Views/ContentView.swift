import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var store: AppStore
    @State private var sidebarVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        VStack(spacing: 0) {
            Picker("Mode", selection: Binding(
                get: { store.workspace },
                set: { store.switchWorkspace(to: $0) }
            )) {
                ForEach(WorkspaceMode.allCases) { workspace in
                    Text(workspace.rawValue).tag(workspace)
                }
            }
            .pickerStyle(.segmented)
            .help("Switch between audio assembly, transcript editing, and video export")
            .frame(maxWidth: 320)
            .padding(.vertical, 10)
            .disabled(store.isWorking)

            Divider()

            Group {
                switch store.workspace {
                case .audio:
                    AudioView(store: store, sidebarVisibility: $sidebarVisibility)
                case .transcript:
                    TranscriptView(store: store)
                case .video:
                    VideoView(store: store)
                }
            }
            .disabled(store.isWorking)

            Divider()
            HStack(spacing: 8) {
                if store.isWorking {
                    ProgressView().controlSize(.small)
                    Button("Cancel", action: store.cancelCurrentOperation)
                        .help("Cancel the current operation")
                }
                Text(store.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if store.isPlaying || store.playingSourceID != nil {
                    Button("Stop Playback", action: store.stopPlayback)
                        .help("Stop playback and reset the current recording")
                }
            }
            .padding(.horizontal, 12)
            .frame(height: 28)
        }
        .frame(minWidth: 980, minHeight: 700)
        .modifier(PinnedTitleVisibility(isActive: store.workspace == .audio && store.isProjectLoaded))
        .background {
            if #available(macOS 14.0, *) {
                PinnedSidebarHeader(
                    visibility: $sidebarVisibility,
                    isVisible: store.workspace == .audio && store.isProjectLoaded,
                    isEnabled: !store.isWorking
                )
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button { store.presentFileImporter(.audioFolder) } label: {
                    Label("Import Audio", systemImage: "folder.badge.plus")
                }
                .help("Import a folder of WAV or AIFF recordings (⌘I)")
                .disabled(store.isWorking)
                Button { store.presentFileImporter(.project) } label: {
                    Label("Open Project", systemImage: "folder")
                }
                .help("Open a saved EnCap project (⌘O)")
                .disabled(store.isWorking)
                Button { store.saveProject() } label: {
                    Label("Save Project", systemImage: "square.and.arrow.down")
                }
                .help("Save this episode, its media, and editing settings as an EnCap project (⌘S)")
                .disabled(!store.isProjectLoaded || store.isWorking)
                Button { store.presentSavePanel(exportAudio: true) } label: {
                    Label("Export Audio", systemImage: "waveform.badge.plus")
                }
                .help("Export the assembled episode using the selected audio format and encoding settings")
                .disabled(!store.isProjectLoaded || store.isWorking)
            }
        }
        .fileImporter(
            isPresented: $store.isFileImporterPresented,
            allowedContentTypes: fileImporterContentTypes,
            allowsMultipleSelection: store.fileImportKind == .audioFiles
        ) { store.completeFileImport($0) }
        .alert(
            "EnCap could not complete the operation",
            isPresented: Binding(
                get: { store.errorMessage != nil },
                set: { if !$0 { store.errorMessage = nil } }
            )
        ) {
            Button("OK", role: .cancel) { store.errorMessage = nil }
        } message: {
            Text(store.errorMessage ?? "Unknown error")
        }
        .onAppear {
            store.loadProviders()
            store.loadVideoSupport()
        }
    }

    private var fileImporterContentTypes: [UTType] {
        switch store.fileImportKind {
        case .audioFolder, .none:
            return [.folder]
        case .audioFiles:
            return ["wav", "wave", "aif", "aiff", "aifc"].compactMap { UTType(filenameExtension: $0) }
        case .project:
            return [.encapProject, .zip, .data]
        case .artwork:
            return [.image]
        }
    }

}


/// SwiftUI's split-view toolbar items follow the divider. A left titlebar
/// accessory keeps the sidebar control and title together beside the window buttons.
/// The window retains its title for accessibility and the Window menu.
private struct PinnedSidebarHeader: NSViewRepresentable {
    @Binding var visibility: NavigationSplitViewVisibility
    var isVisible: Bool
    var isEnabled: Bool

    func makeNSView(context: Context) -> WindowProbe { WindowProbe() }

    func updateNSView(_ view: WindowProbe, context: Context) {
        view.shouldShow = isVisible
        view.button.isEnabled = isEnabled
        let label = visibility == .detailOnly ? "Show Sidebar" : "Hide Sidebar"
        view.button.toolTip = label
        view.button.setAccessibilityLabel(label)
        view.onToggle = {
            withAnimation { visibility = visibility == .detailOnly ? .all : .detailOnly }
        }
        view.updateAccessory()
    }

    static func dismantleNSView(_ view: WindowProbe, coordinator: ()) {
        view.removeAccessory()
        view.onToggle = nil
    }

    final class WindowProbe: NSView {
        let accessory = NSTitlebarAccessoryViewController()
        let button = NSButton()
        let titleLabel = NSTextField(labelWithString: "EnCap")
        private var originalTitleVisibility: NSWindow.TitleVisibility?
        weak var accessoryWindow: NSWindow?
        var shouldShow = false
        var onToggle: (() -> Void)?

        override init(frame: NSRect) {
            super.init(frame: frame)
            accessory.layoutAttribute = .left
            let container = NSView(frame: NSRect(x: 0, y: 0, width: 40, height: 38))
            button.image = NSImage(systemSymbolName: "sidebar.left", accessibilityDescription: "Toggle Sidebar")
            button.bezelStyle = .texturedRounded
            button.isBordered = false
            button.contentTintColor = .labelColor
            button.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 18, weight: .regular)
            button.imagePosition = .imageOnly
            button.target = self
            button.action = #selector(toggleSidebar)
            button.translatesAutoresizingMaskIntoConstraints = false
            titleLabel.font = .systemFont(ofSize: NSFont.systemFontSize, weight: .semibold)
            titleLabel.textColor = .labelColor
            titleLabel.translatesAutoresizingMaskIntoConstraints = false
            container.addSubview(button)
            container.addSubview(titleLabel)
            NSLayoutConstraint.activate([
                button.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 4),
                button.centerYAnchor.constraint(equalTo: container.centerYAnchor),
                button.widthAnchor.constraint(equalToConstant: 32),
                button.heightAnchor.constraint(equalToConstant: 28),
                titleLabel.leadingAnchor.constraint(equalTo: button.trailingAnchor, constant: 12),
                titleLabel.centerYAnchor.constraint(equalTo: container.centerYAnchor)
            ])
            accessory.view = container
        }

        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            updateAccessory()
        }

        func updateAccessory() {
            if accessoryWindow !== window || !shouldShow { removeAccessory() }
            guard shouldShow, accessoryWindow == nil, let window else { return }
            titleLabel.stringValue = window.title
            accessory.view.setFrameSize(NSSize(width: 60 + ceil(titleLabel.fittingSize.width), height: 38))
            originalTitleVisibility = window.titleVisibility
            window.titleVisibility = .hidden
            window.addTitlebarAccessoryViewController(accessory)
            accessoryWindow = window
        }

        func removeAccessory() {
            if let window = accessoryWindow,
               let index = window.titlebarAccessoryViewControllers.firstIndex(where: { $0 === accessory }) {
                window.removeTitlebarAccessoryViewController(at: index)
                if let originalTitleVisibility { window.titleVisibility = originalTitleVisibility }
            }
            originalTitleVisibility = nil
            accessoryWindow = nil
        }

        @objc private func toggleSidebar() { onToggle?() }
    }
}

private struct PinnedTitleVisibility: ViewModifier {
    var isActive: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if #available(macOS 15.0, *) {
            content.toolbar(removing: isActive ? .title : nil)
        } else {
            content
        }
    }
}
