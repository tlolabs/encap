import AppKit
import SwiftUI

@main
struct EnCapApp: App {
    @NSApplicationDelegateAdaptor(EnCapApplicationDelegate.self) private var appDelegate
    @StateObject private var store = AppStore()
    @AppStorage("SUEnableAutomaticChecks") private var automaticUpdates = true
    @AppStorage("appearance") private var appearance = "system"

    var body: some Scene {
        WindowGroup("EnCap", id: "main") {
            ContentView(store: store)
                .onAppear { appDelegate.store = store }
                .onAppear(perform: applyAppearance)
                .onChange(of: appearance) { _ in applyAppearance() }
        }
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Import Audio Folder…") { store.presentFileImporter(.audioFolder) }
                    .keyboardShortcut("i", modifiers: .command)
                    .help("Import a folder of WAV or AIFF recordings")
                Button("Add Audio Files…") { store.presentFileImporter(.audioFiles) }
                    .keyboardShortcut("i", modifiers: [.command, .shift])
                    .help("Add WAV or AIFF recordings to this episode")
                    .disabled(!store.isProjectLoaded || store.isWorking)
                Button("Open Project…") { store.presentFileImporter(.project) }
                    .keyboardShortcut("o", modifiers: .command)
                    .help("Open a saved EnCap project")
                Button("Save Project") { store.saveProject() }
                    .keyboardShortcut("s", modifiers: .command)
                    .help("Save this episode, its media, and editing settings")
                    .disabled(!store.isProjectLoaded || store.isWorking)
                Button("Save Project As…") { store.presentSavePanel() }
                    .keyboardShortcut("S", modifiers: [.command, .shift])
                    .help("Save a copy of this project to a new location")
                    .disabled(!store.isProjectLoaded || store.isWorking)
            }
            CommandMenu("Mode") {
                Button("Audio") { store.switchWorkspace(to: .audio) }
                    .keyboardShortcut("1", modifiers: .command)
                    .help("Assemble recordings, edit chapters, and configure audio export")
                Button("Transcript") { store.switchWorkspace(to: .transcript) }
                    .keyboardShortcut("2", modifiers: .command)
                    .help("Generate and edit the episode transcript")
                Button("Video") { store.switchWorkspace(to: .video) }
                    .keyboardShortcut("3", modifiers: .command)
                    .help("Arrange chapters and artwork for video export")
            }
            CommandGroup(after: .appInfo) {
                Button("Check for Updates…") { store.checkForUpdates() }
                    .help("Check for a newer version of EnCap")
                Toggle("Automatically Check for Updates", isOn: $automaticUpdates)
            }
        }
        Settings {
            Form {
                Picker("Appearance", selection: $appearance) {
                    Text("System").tag("system")
                    Text("Light").tag("light")
                    Text("Dark").tag("dark")
                }
                .pickerStyle(.radioGroup)
            }
            .padding(20)
            .frame(width: 320)
        }
    }

    private func applyAppearance() {
        switch appearance {
        case "light": NSApp.appearance = NSAppearance(named: .aqua)
        case "dark": NSApp.appearance = NSAppearance(named: .darkAqua)
        default: NSApp.appearance = nil
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
