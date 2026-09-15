import SwiftUI

struct TranscriptView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Project",
                systemImage: "text.bubble",
                description: "Import audio before creating a transcript."
            )
        } else {
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    Picker("Engine", selection: $store.selectedProviderID) {
                        ForEach(store.providers) { provider in
                            Text(provider.name).tag(provider.id)
                        }
                    }
                    .frame(maxWidth: 300)
                    .help("Choose the on-device engine used to transcribe this episode")

                    Button("Transcribe", action: store.transcribe)
                        .buttonStyle(.borderedProminent)
                        .disabled(store.providers.isEmpty || store.isWorking)
                        .help("Create or replace the transcript using the selected on-device engine")
                    Button("Manage Models…", action: store.presentModelManager)
                        .help("Download or remove local transcription models")
                    Menu("Export") {
                        Button("Plain Text…") { store.presentTranscriptSavePanel(format: "txt") }
                            .help("Save the transcript as a plain text file")
                        Button("SRT Captions…") { store.presentTranscriptSavePanel(format: "srt") }
                            .help("Save timed captions as an SRT subtitle file")
                    }
                    .disabled(store.project?.transcriptSegments.isEmpty != false)
                    .help("Export the transcript as plain text or timed SRT captions")
                    Toggle("Show Speakers", isOn: $store.transcriptShowsSpeakers)
                        .help("Show or hide editable speaker names beside transcript segments")
                    Toggle(
                        "Word timing",
                        isOn: Binding(
                            get: { store.project?.transcriptSettings.includeWordTimestamps ?? false },
                            set: { store.project?.transcriptSettings.includeWordTimestamps = $0 }
                        )
                    )
                    .help("Include individual word timestamps when generating the transcript")
                    Spacer()
                    TextField("Search transcript", text: $store.transcriptSearch)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 220)
                }
                .padding(12)
                Divider()

                if filteredIndices.isEmpty {
                    EmptyStateView(
                        store.transcriptSearch.isEmpty ? "No Transcript" : "No Matching Segments",
                        systemImage: "captions.bubble",
                        description: store.transcriptSearch.isEmpty
                            ? "Choose an on-device engine and transcribe this episode."
                            : "Try another search or clear the search field."
                    )
                } else {
                    List {
                        ForEach(filteredIndices, id: \.self) { index in
                            TranscriptRow(
                                segment: segmentBinding(index),
                                showSpeaker: store.transcriptShowsSpeakers,
                                play: { playSegment(index) }
                            )
                        }
                    }
                    .listStyle(.inset)
                }
            }
            .sheet(isPresented: $store.isModelManagerPresented) {
                ModelManagerView(store: store)
            }
        }
    }

    private var filteredIndices: [Int] {
        guard let segments = store.project?.transcriptSegments else { return [] }
        guard !store.transcriptSearch.isEmpty else { return Array(segments.indices) }
        return segments.indices.filter {
            segments[$0].text.localizedCaseInsensitiveContains(store.transcriptSearch)
                || segments[$0].speaker.localizedCaseInsensitiveContains(store.transcriptSearch)
        }
    }

    private func segmentBinding(_ index: Int) -> Binding<TranscriptSegment> {
        let fallback = TranscriptSegment(
            id: UUID().uuidString,
            startTimeSeconds: 0,
            endTimeSeconds: 0,
            speaker: "",
            text: ""
        )
        guard let segments = store.project?.transcriptSegments,
              segments.indices.contains(index) else {
            return .constant(fallback)
        }
        let targetID = segments[index].id
        return Binding(
            get: {
                store.project?.transcriptSegments.first(where: { $0.id == targetID })
                    ?? segments.first(where: { $0.id == targetID })
                    ?? fallback
            },
            set: { updated in
                guard let current = store.project?.transcriptSegments.firstIndex(where: { $0.id == targetID }) else { return }
                store.project?.transcriptSegments[current] = updated
            }
        )
    }

    private func playSegment(_ index: Int) {
        guard let project = store.project,
              index < project.transcriptSegments.count else { return }
        let time = project.transcriptSegments[index].startTimeSeconds
        var running = 0.0
        for source in project.audioSources {
            if time < running + source.durationSeconds {
                store.play(source: source, at: time - running)
                return
            }
            running += source.durationSeconds
        }
    }
}

private struct ModelManagerView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Local Transcription Models").font(.title2).bold()
                    Text("Models are downloaded from EnCap's pinned catalog, verified with SHA-256, and used offline.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Done") { store.isModelManagerPresented = false }
                    .keyboardShortcut(.defaultAction)
                    .help("Close the transcription model manager")
            }
            List(store.transcriptionModels) { model in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: model.installed ? "checkmark.circle.fill" : "arrow.down.circle")
                        .foregroundStyle(model.installed ? Color.green : Color.secondary)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(model.name).font(.headline)
                        Text("\(model.downloadSize) · \(model.languages)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(model.description)
                            .font(.callout)
                    }
                    Spacer()
                    if model.installed {
                        Button("Remove", role: .destructive) { store.removeModel(model) }
                            .help("Remove the local download of \(model.name)")
                    } else {
                        Button("Download") { store.installModel(model) }
                            .buttonStyle(.borderedProminent)
                            .disabled(!model.downloadAllowed)
                            .help(model.downloadAllowed
                                ? "Download this model for offline transcription"
                                : "EnCap is reusing a compatible model already installed by another app")
                    }
                }
                .padding(.vertical, 6)
            }
            .overlay {
                if store.transcriptionModels.isEmpty {
                    ProgressView("Loading model catalog…")
                }
            }
        }
        .padding(20)
        .frame(minWidth: 660, minHeight: 440)
    }
}

private struct TranscriptRow: View {
    @Binding var segment: TranscriptSegment
    let showSpeaker: Bool
    let play: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Button(action: play) {
                Label(EnCapFormatters.timestamp(segment.startTimeSeconds), systemImage: "play.circle")
                    .labelStyle(.titleAndIcon)
                    .monospacedDigit()
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .frame(width: 84, alignment: .leading)
            .help("Play audio starting at \(EnCapFormatters.timestamp(segment.startTimeSeconds))")

            if showSpeaker {
                TextField("Speaker", text: $segment.speaker)
                    .frame(width: 120)
            }
            TextField("Transcript text", text: $segment.text, axis: .vertical)
                .lineLimit(1...5)
        }
        .padding(.vertical, 4)
    }
}
