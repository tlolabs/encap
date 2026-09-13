import SwiftUI

@main
struct EnCapApp: App {
    @NSApplicationDelegateAdaptor(EnCapApplicationDelegate.self) private var appDelegate
    @StateObject private var store = AppStore()

    var body: some Scene {
        WindowGroup("EnCap", id: "main") {
            ContentView(store: store)
                .onAppear { appDelegate.store = store }
        }
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Import Audio Folder…") { store.presentFileImporter(.audioFolder) }
                    .keyboardShortcut("i", modifiers: .command)
                Button("Open Project…") { store.presentFileImporter(.project) }
                    .keyboardShortcut("o", modifiers: .command)
                Button("Save Project…") { store.presentSavePanel() }
                    .keyboardShortcut("s", modifiers: .command)
                    .disabled(!store.isProjectLoaded || store.isWorking)
            }
            CommandMenu("Workspace") {
                Button("Process Audio") { store.workspace = .process }
                    .keyboardShortcut("1", modifiers: .command)
                Button("Transcribe") { store.workspace = .transcribe }
                    .keyboardShortcut("2", modifiers: .command)
            }
            CommandGroup(replacing: .help) {
                Button("Check for Updates…") { store.checkForUpdates() }
            }
        }
    }
}

@MainActor
final class EnCapApplicationDelegate: NSObject, NSApplicationDelegate {
    weak var store: AppStore?
    private var isPreparingToTerminate = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if isPreparingToTerminate { return .terminateLater }
        guard store?.confirmDiscardChanges() != false else { return .terminateCancel }
        guard let store else { return .terminateNow }
        isPreparingToTerminate = true
        Task { @MainActor in
            await store.prepareToTerminate()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
