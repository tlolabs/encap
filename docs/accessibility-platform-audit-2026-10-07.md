# Accessibility and platform support audit — 7 October 2026

This is a practical accessibility review, not a WCAG certification. The native
SwiftUI/AppKit app remains the macOS reference. The Avalonia app remains the
Windows/Linux interface and the internal macOS reference build.

## Support baseline

| Build | Existing minimum and architecture | UI and distribution |
| --- | --- | --- |
| macOS | macOS 13; Apple silicon and Intel | SwiftUI/AppKit; application ZIP |
| Windows | Windows 10 1809; x64 and ARM64 | Avalonia/.NET 10; portable ZIP |
| Linux | X11/XWayland, glibc 2.39+; x64 and ARM64 | Avalonia/.NET 10; AppImage |
| Internal macOS reference | Apple silicon | Avalonia/.NET 10; internal ZIP |

These targets, frameworks, and formats were preserved. The source of record for
release support is the README and build workflows.

## Confirmed defects addressed

- macOS lacked a persisted System/Light/Dark preference. A native Settings
  scene now provides it and applies the selection to the application immediately.
- Avalonia exposed all three appearance choices but forgot the choice at
  relaunch and did not show which one was active. It now persists the choice
  separately for production and internal builds, restores it at startup, and
  marks the active menu item.
- Adding recordings to an existing macOS project was only exposed through the
  source-list context menu. File > Add Audio Files now provides a keyboard path
  with Command-Shift-I.
- The macOS source-list play control was dimmed when the pointer was absent,
  making an essential action difficult to discover. It remains visible.
- Long source names could force the macOS sidebar wider than the window.
  Its preferred width is now capped; the full name remains available in help.
- The fixed-height macOS status bar could clip longer status text. It now has a
  minimum height, and status changes request VoiceOver announcements.
- Custom sidebar-toggle animation now respects Reduce Motion.
- macOS video preview controls, timeline value, chapter movement controls, and
  repeated chapter fields now have contextual accessibility labels.
- Avalonia menu shortcuts now display the existing Save As and mode gestures.
  The internal macOS build uses Command for those actions; Windows and Linux
  retain Control.

Existing native controls, semantic colors, native dialogs, keyboard paths for
deleting and reordering chapters, and non-color status text were retained.
No new framework or dependency was introduced.

## Automated verification

- Before changes: 40 Avalonia headless presentation/lifecycle checks and 23
  shared timestamp cases passed.
- After changes: 40 existing Avalonia checks passed. Eleven separate headless
  accessibility checks passed for appearance persistence, live status,
  progress and slider names, exclusive appearance selection, and platform
  shortcut modifiers.
- The eleven accessibility checks run on macOS internal, Windows, and Linux CI
  with `continue-on-error: true`; they do not block merges or releases.
- Changed Swift files passed syntax parsing. This does not type-check or launch
  the native application.
- The rebuilt internal macOS Avalonia package passed its distribution tests.
  A live launch exposed the recording and form controls in the macOS
  accessibility tree. Keyboard navigation opened the Appearance submenu;
  switching to Dark changed the running UI immediately, and System restored
  the prior light appearance.

## Verification still required

The local Xcode license has not been accepted, so the full native macOS build,
Swift tests, packaged app, and VoiceOver session could not be completed here.
The command-line-tools Swift build also failed before changes because its
SwiftUI macro plugin was unavailable. After the Xcode license is accepted,
run the existing macOS build and test commands in `README.md`, then check:

1. VoiceOver reading order, names, status announcements, alerts, and focus
   restoration in Audio, Transcript, Video, Settings, and model management.
2. Keyboard operation of import, add, delete, reorder, playback, seeking,
   export, dialogs, and menu commands.
3. System/Light/Dark switching and relaunch persistence, with Reduce Motion,
   Increase Contrast, Reduce Transparency, and larger text enabled.
4. Window resizing and movement between 100%, 125%, 150%, 175%, and 200%
   scaling where those factors are available; inspect constrained laptop sizes.
5. Windows Narrator or NVDA and UI Automation; Linux Orca and AT-SPI. Run
   packaged Windows and Linux builds on those hosts, including high-contrast
   themes, fractional scaling, and display changes.

No screen-reader session or multi-display scaling test was performed in this
environment. Avalonia's exact UI Automation and AT-SPI behavior therefore
remains unverified. The dependency's built-in support should be validated on
the actual target desktops before making a compatibility claim.

## Follow-up recommendations

- If large-text testing exposes overflow in the dense audio encoding controls
  or transcript toolbar, adapt those groups to available width after observing
  the affected settings and screen sizes.
- Review whether model installation progress can expose a measurable fraction
  from the engine. The current indeterminate indicator accurately reports
  activity but cannot report a percentage.
- Consider contextual help for first-time chapter editing only after user
  research identifies a concrete discoverability gap. No onboarding was added.
