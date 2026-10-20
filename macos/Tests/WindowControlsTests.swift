import AppKit
import XCTest
@testable import EnCap

final class WindowControlsTests: XCTestCase {
    @MainActor
    private func window() -> NSWindow {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 880, height: 620),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false
        )
        window.isReleasedWhenClosed = false
        return window
    }

    @MainActor
    private func buttons(in window: NSWindow) -> [NSButton] {
        [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton]
            .compactMap { window.standardWindowButton($0) }
    }

    @MainActor
    func testControlsReturnAfterToolbarReparentsAndHidesThem() throws {
        let window = window()
        defer { window.close() }
        let buttons = buttons(in: window)
        XCTAssertEqual(buttons.count, 3)
        let originalParents = buttons.map(\.superview)
        let host = WindowControls.ControlsView(frame: NSRect(x: 0, y: 0, width: 64, height: 32))
        window.contentView?.addSubview(host)
        defer { host.stopHosting() }

        for _ in 0..<6 {
            // Tab changes can hand the standard controls back to the hidden toolbar.
            for (button, parent) in zip(buttons, originalParents) {
                try XCTUnwrap(parent).addSubview(button)
                button.isHidden = true
            }
            host.attachControls()
            for button in buttons {
                XCTAssertTrue(button.superview === host)
                XCTAssertFalse(button.isHidden)
                XCTAssertTrue(host.bounds.contains(button.frame))
            }
        }
    }

    @MainActor
    func testOldHostDismantlingDoesNotHideReplacementHostsControls() {
        let window = window()
        defer { window.close() }
        let buttons = buttons(in: window)
        let originalParents = buttons.map(\.superview)
        let oldHost = WindowControls.ControlsView(frame: NSRect(x: 0, y: 0, width: 64, height: 32))
        window.contentView?.addSubview(oldHost)
        let newHost = WindowControls.ControlsView(frame: oldHost.frame)
        window.contentView?.addSubview(newHost)

        oldHost.stopHosting()
        for button in buttons {
            XCTAssertTrue(button.superview === newHost)
            XCTAssertFalse(button.isHidden)
        }
        newHost.stopHosting()
        for (button, parent) in zip(buttons, originalParents) {
            XCTAssertTrue(button.superview === parent)
        }
    }
}
