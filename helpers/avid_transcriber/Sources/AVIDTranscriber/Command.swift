import EnCAPTranscription

/// Diagnostic command line client of the same linked application adapter.
@main
struct DiagnosticCommand {
    static func main() async { await BridgeCommand.main() }
}
