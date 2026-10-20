import AppKit
import SwiftUI

/// One header owns the actions and mode picker, outside the split views' scrollable content.
struct WorkspaceHeader: View {
    @ObservedObject var store: AppStore
    @Binding var sidebarVisibility: NavigationSplitViewVisibility
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    private let modePickerWidth: CGFloat = 250

    var body: some View {
        ZStack {
            WindowDragArea()
            HStack {
                WindowControls(workspace: store.workspace)
                    .frame(width: 64, height: 32)
                HStack(spacing: 8) {
                    Button(action: toggleSidebar) {
                        Label(sidebarVisibility == .detailOnly ? "Show Sidebar" : "Hide Sidebar", systemImage: "sidebar.left")
                            .labelStyle(.iconOnly)
                            .font(.system(size: 18))
                            .frame(width: 32, height: 32)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.borderless)
                    .disabled(!store.isProjectLoaded || store.workspace == .transcript || store.isWorking)
                    .help(sidebarVisibility == .detailOnly ? "Show Sidebar" : "Hide Sidebar")
                    actionIcons
                }
                Spacer(minLength: 0)
                exportAction
            }
            .padding(.horizontal, 14)

            HStack(spacing: 8) {
                Text("Mode")
                Picker("Mode", selection: Binding(
                    get: { store.workspace },
                    set: { store.switchWorkspace(to: $0) }
                )) {
                    ForEach(WorkspaceMode.allCases) { workspace in
                        Text(workspace.rawValue).tag(workspace)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: modePickerWidth)
                .disabled(store.isWorking)
                .help("Switch between audio assembly, transcript editing, and video export")
            }
            .fixedSize()
            .alignmentGuide(HorizontalAlignment.center) { dimensions in
                dimensions.width - modePickerWidth / 2
            }
        }
        .frame(height: 52)
        .background(.bar)
        .overlay(alignment: .bottom) { Divider() }
    }

    private var actionIcons: some View {
        HStack(spacing: 8) {
            icon("Import Audio", symbol: "folder.badge.plus", enabled: !store.isWorking) {
                store.presentFileImporter(.audioFolder)
            }
            icon("Open Project", symbol: "folder", enabled: !store.isWorking) {
                store.presentFileImporter(.project)
            }
            icon("Save Project", symbol: "square.and.arrow.down", enabled: store.isProjectLoaded && !store.isWorking, symbolOffsetY: -2) {
                store.saveProject()
            }
        }
    }

    private func icon(_ title: String, symbol: String, enabled: Bool, symbolOffsetY: CGFloat = 0, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .labelStyle(.iconOnly)
                .font(.system(size: 18))
                // The save symbol extends lower than the folder symbols at this font size.
                .offset(y: symbolOffsetY)
                .frame(width: 32, height: 32)
                .contentShape(Rectangle())
        }
        .buttonStyle(.borderless)
        .disabled(!enabled)
        .help(title)
        .accessibilityLabel(title)
    }

    @ViewBuilder
    private var exportAction: some View {
        switch store.workspace {
        case .audio:
            Button("Export Audio…") { store.presentSavePanel(exportAudio: true) }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .fixedSize()
                .disabled(!store.isProjectLoaded || store.isWorking)
                .help("Export the episode using its audio encoding settings")
        case .video:
            Button("Export Video…", action: store.presentVideoSavePanel)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .fixedSize()
                .disabled(!store.canExportVideo)
                .help("Export included chapters in sidebar order as an MP4 video")
        case .transcript:
            Menu("Export Transcript…") {
                Button("Plain Text…") { store.presentTranscriptSavePanel(format: "txt") }
                Button("SRT Captions…") { store.presentTranscriptSavePanel(format: "srt") }
            }
            .menuStyle(.borderedButton)
            .controlSize(.large)
            .fixedSize()
            .disabled(store.project?.transcriptSegments.isEmpty != false || store.isWorking)
            .help("Export the transcript as plain text or timed SRT captions")
        }
    }

    private func toggleSidebar() {
        if reduceMotion {
            sidebarVisibility = sidebarVisibility == .detailOnly ? .all : .detailOnly
        } else {
            withAnimation { sidebarVisibility = sidebarVisibility == .detailOnly ? .all : .detailOnly }
        }
    }
}

/// Host the window's real controls so hiding the system toolbar cannot hide them.
struct WindowControls: NSViewRepresentable {
    var workspace: WorkspaceMode

    func makeNSView(context: Context) -> ControlsView { ControlsView() }
    func updateNSView(_ view: ControlsView, context: Context) {
        view.attachControls()
        // Navigation and toolbar changes can finish after SwiftUI updates this view.
        view.scheduleReconciliation()
    }

    static func dismantleNSView(_ view: ControlsView, coordinator: ()) {
        view.stopHosting()
    }

    final class ControlsView: NSView {
        private final class SavedControl {
            let button: NSButton
            weak var parent: NSView?
            let frame: NSRect
            let wasHidden: Bool

            init(_ button: NSButton) {
                self.button = button
                parent = button.superview
                frame = button.frame
                wasHidden = button.isHidden
            }
        }

        private weak var attachedWindow: NSWindow?
        private var controls: [SavedControl] = []
        private var observers: [NSObjectProtocol] = []
        private var isHosting = true
        private var reconciliationScheduled = false
        private var generation = 0

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            attachControls()
            scheduleReconciliation()
        }

        override func layout() {
            super.layout()
            attachControls()
        }

        func attachControls() {
            guard isHosting else { return }
            if attachedWindow !== window { restoreControls() }
            guard let window else { return }
            if attachedWindow == nil {
                attachedWindow = window
                for name in [NSWindow.didResizeNotification, NSWindow.didUpdateNotification] {
                    observers.append(NotificationCenter.default.addObserver(
                        forName: name, object: window, queue: .main
                    ) { [weak self] _ in self?.scheduleReconciliation() })
                }
            }

            let buttons = [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton]
                .compactMap { window.standardWindowButton($0) }
            var inherited: [SavedControl] = []
            // A replacement SwiftUI host may attach before its predecessor dismantles.
            // Transfer ownership so the old host cannot hide the new host's controls.
            for button in buttons {
                if let previous = button.superview as? ControlsView, previous !== self {
                    inherited.append(contentsOf: previous.controls)
                    previous.stopHosting(restoring: false)
                }
            }
            let known = controls + inherited
            let next = buttons.map { button in
                known.first(where: { $0.button === button }) ?? SavedControl(button)
            }
            for stale in controls where !buttons.contains(where: { $0 === stale.button }) {
                if stale.button.superview === self { stale.button.removeFromSuperview() }
            }
            controls = next
            for (index, control) in controls.enumerated() {
                if control.button.superview !== self { addSubview(control.button) }
                if control.button.isHidden { control.button.isHidden = false }
                let target = NSRect(
                    x: CGFloat(index) * 20,
                    y: (bounds.height - control.frame.height) / 2,
                    width: control.frame.width,
                    height: control.frame.height
                )
                if control.button.frame != target { control.button.frame = target }
            }
        }

        func scheduleReconciliation() {
            guard isHosting, window != nil, !reconciliationScheduled else { return }
            reconciliationScheduled = true
            let scheduledGeneration = generation
            DispatchQueue.main.async { [weak self] in
                guard let self, self.isHosting, self.generation == scheduledGeneration else { return }
                self.reconciliationScheduled = false
                self.attachControls()
            }
        }

        func stopHosting(restoring: Bool = true) {
            isHosting = false
            if restoring {
                restoreControls()
            } else {
                removeObservers()
                controls = []
                attachedWindow = nil
            }
        }

        private func restoreControls() {
            removeObservers()
            for control in controls where control.button.superview === self {
                control.parent?.addSubview(control.button)
                control.button.frame = control.frame
                control.button.isHidden = control.wasHidden
            }
            controls = []
            attachedWindow = nil
        }

        private func removeObservers() {
            for observer in observers { NotificationCenter.default.removeObserver(observer) }
            observers = []
            generation += 1
            reconciliationScheduled = false
        }
    }
}

/// The header's blank space drags the window; SwiftUI controls above it receive their own clicks.
private struct WindowDragArea: NSViewRepresentable {
    func makeNSView(context: Context) -> DragView { DragView() }
    func updateNSView(_ view: DragView, context: Context) {}

    final class DragView: NSView {
        override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    }
}
