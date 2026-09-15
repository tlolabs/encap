import AppKit
import MediaPlayer
import SwiftUI

/// Discrete editor shuttle speeds. Opposite direction starts at 1×; K chords use ½×.
enum SourceShuttle {
    static func rate(current: Float, direction: Float, slow: Bool = false) -> Float {
        if slow { return direction * 0.5 }
        return direction * (current * direction > 0 ? min(32, max(1, abs(current) * 2)) : 1)
    }
}

/// macOS 13 does not have SwiftUI's key press API. The monitor only consumes keys
/// when the first responder is inside this list's visible bounds, never a text editor.
struct SourcePlaybackKeys: NSViewRepresentable {
    var action: (String, Bool) -> Void
    func makeNSView(context: Context) -> KeyScopeView { KeyScopeView(action: action) }
    func updateNSView(_ view: KeyScopeView, context: Context) { view.action = action }
    static func dismantleNSView(_ view: KeyScopeView, coordinator: ()) { view.removeMonitor() }

    final class KeyScopeView: NSView {
        var action: (String, Bool) -> Void
        private var monitor: Any?
        private var focusObserver: NSObjectProtocol?
        private var held: Set<String> = []
        init(action: @escaping (String, Bool) -> Void) { self.action = action; super.init(frame: .zero) }
        required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
        override func hitTest(_ point: NSPoint) -> NSView? { nil }
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            removeMonitor()
            guard window != nil else { return }
            focusObserver = NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification, object: window, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.releaseChord() }
            }
            monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp, .leftMouseDown, .rightMouseDown]) { [weak self] event in
                guard let self else { return event }
                if event.type == .leftMouseDown || event.type == .rightMouseDown {
                    self.releaseChord()
                    return event
                }
                let key = event.charactersIgnoringModifiers?.lowercased() ?? ""
                guard [" ", "j", "k", "l"].contains(key) else { return event }
                if event.type == .keyUp {
                    let consumed = self.held.remove(key) != nil
                    if consumed && (key == "k" || self.held.contains("k")) { self.action("k", false) }
                    return consumed ? nil : event
                }
                guard let window = self.window, window.isKeyWindow, window.attachedSheet == nil,
                      let focus = window.firstResponder as? NSView,
                      !(focus is NSTextView), !(focus is NSTextField),
                      !self.isHiddenOrHasHiddenAncestor,
                      self.convert(self.bounds, to: nil).intersects(focus.convert(focus.visibleRect, to: nil)),
                      event.modifierFlags.intersection([.command, .control, .option, .shift]).isEmpty
                else { self.held.removeAll(); return event }
                guard !event.isARepeat else { return nil }
                self.held.insert(key)
                self.action(key, self.held.contains("k"))
                return nil
            }
        }
        private func releaseChord() {
            if held.contains("k") && (held.contains("j") || held.contains("l")) { action("k", false) }
            held.removeAll()
        }
        func removeMonitor() {
            if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
            focusObserver = nil
            if let monitor { NSEvent.removeMonitor(monitor) }
            monitor = nil
            held.removeAll()
        }
        deinit {
            if let monitor { NSEvent.removeMonitor(monitor) }
            if let focusObserver { NotificationCenter.default.removeObserver(focusObserver) }
        }
    }
}

/// Uses the OS media session, including hardware keys and Control Center.
@MainActor
final class SourceMediaControls {
    private var targets: [(MPRemoteCommand, Any)] = []
    func activate(action: @escaping @MainActor (String, Double?) -> Void) {
        guard targets.isEmpty else { return }
        let center = MPRemoteCommandCenter.shared()
        func bind(_ command: MPRemoteCommand, _ name: String) {
            command.isEnabled = true
            let token = command.addTarget { event in
                let position = (event as? MPChangePlaybackPositionCommandEvent)?.positionTime
                Task { @MainActor in action(name, position) }
                return .success
            }
            targets.append((command, token))
        }
        bind(center.playCommand, "play")
        bind(center.pauseCommand, "pause")
        bind(center.togglePlayPauseCommand, "toggle")
        bind(center.stopCommand, "stop")
        bind(center.nextTrackCommand, "next")
        bind(center.previousTrackCommand, "previous")
        bind(center.changePlaybackPositionCommand, "seek")
    }
    func update(source: AudioSource, position: Double, rate: Float) {
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: source.displayName,
            MPMediaItemPropertyPlaybackDuration: source.durationSeconds,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position.isFinite ? max(0, position) : 0,
            MPNowPlayingInfoPropertyPlaybackRate: rate,
            MPNowPlayingInfoPropertyDefaultPlaybackRate: 1
        ]
        MPNowPlayingInfoCenter.default().playbackState = rate == 0 ? .paused : .playing
    }
    func deactivate() {
        for (command, token) in targets { command.removeTarget(token); command.isEnabled = false }
        targets.removeAll()
        MPNowPlayingInfoCenter.default().playbackState = .stopped
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
    }
    deinit { for (command, token) in targets { command.removeTarget(token) } }
}
