import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        VStack(spacing: 0) {
            Picker("Workspace", selection: $store.workspace) {
                ForEach(AppStore.Workspace.allCases) { workspace in
                    Text(workspace.rawValue).tag(workspace)
                }
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 320)
            .padding(.vertical, 10)

            Divider()

            Group {
                if store.workspace == .process {
                    ProcessAudioView(store: store)
                } else {
                    TranscribeView(store: store)
                }
            }

            Divider()
            HStack(spacing: 8) {
                if store.isWorking {
                    ProgressView().controlSize(.small)
                }
                Text(store.status)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                if store.isPlaying {
                    Button("Stop Playback", action: store.stopPlayback)
                        .help("Stop audio playback")
                }
            }
            .padding(.horizontal, 12)
            .frame(height: 28)
        }
        .disabled(store.isWorking)
        .frame(minWidth: 980, minHeight: 700)
        .toolbar {
            ToolbarItemGroup {
                Button { store.presentFileImporter(.audioFolder) } label: {
                    Label("Import Audio", systemImage: "folder.badge.plus")
                }
                Button { store.presentFileImporter(.project) } label: {
                    Label("Open Project", systemImage: "folder")
                }
                Button { store.presentSavePanel() } label: {
                    Label("Save Project", systemImage: "square.and.arrow.down")
                }
                .disabled(!store.isProjectLoaded)
                Button { store.presentSavePanel(exportAudio: true) } label: {
                    Label("Export Audio", systemImage: "waveform.badge.plus")
                }
                .disabled(!store.isProjectLoaded)
            }
        }
        .fileImporter(
            isPresented: $store.isFileImporterPresented,
            allowedContentTypes: fileImporterContentTypes,
            allowsMultipleSelection: false
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
        .onAppear { store.loadProviders() }
    }

    private var fileImporterContentTypes: [UTType] {
        switch store.fileImportKind {
        case .audioFolder, .none:
            return [.folder]
        case .project:
            return [.encapProject, .zip, .data]
        case .artwork:
            return [.image]
        }
    }

}
