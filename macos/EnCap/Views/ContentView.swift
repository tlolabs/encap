import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var store: AppStore
    @State private var sidebarVisibility: NavigationSplitViewVisibility = .all
    @State private var videoSidebarVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        VStack(spacing: 0) {
            WorkspaceHeader(
                store: store,
                sidebarVisibility: store.workspace == .video ? $videoSidebarVisibility : $sidebarVisibility
            )

            Group {
                switch store.workspace {
                case .audio:
                    AudioView(store: store, sidebarVisibility: $sidebarVisibility)
                case .transcript:
                    TranscriptView(store: store)
                case .video:
                    VideoView(store: store, sidebarVisibility: $videoSidebarVisibility)
                }
            }
            .disabled(store.isWorking)

            Divider()
            HStack(spacing: 8) {
                if store.isWorking {
                    ProgressView()
                        .controlSize(.small)
                        .accessibilityLabel("Operation in progress")
                    Button("Cancel", action: store.cancelCurrentOperation)
                        .help("Cancel the current operation")
                }
                Text(store.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("Status: \(store.status)")
                Spacer()
                if store.isPlaying || store.playingSourceID != nil {
                    Button("Stop Playback", action: store.stopPlayback)
                        .help("Stop playback and reset the current recording")
                }
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 28)
        }
        .frame(minWidth: 880, minHeight: 620)
        .toolbar(.hidden, for: .windowToolbar)
        .ignoresSafeArea(.container, edges: .top)
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
