import SwiftUI

struct TranscribeView: View {
    @ObservedObject var store: AppStore
    @State private var query = ""
    @State private var showSpeakers = true

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

                    Button("Transcribe", action: store.transcribe)
                        .buttonStyle(.borderedProminent)
                        .disabled(store.providers.isEmpty || store.isWorking)
                    Toggle("Show Speakers", isOn: $showSpeakers)
                    Spacer()
                    TextField("Search transcript", text: $query)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 220)
                }
                .padding(12)
                Divider()

                if filteredIndices.isEmpty {
                    EmptyStateView(
                        query.isEmpty ? "No Transcript" : "No Matching Segments",
                        systemImage: "captions.bubble",
                        description: query.isEmpty
                            ? "Choose an on-device engine and transcribe this episode."
                            : "Try another search or clear the search field."
                    )
                } else {
                    List {
                        ForEach(filteredIndices, id: \.self) { index in
                            TranscriptRow(
                                segment: segmentBinding(index),
                                showSpeaker: showSpeakers,
                                play: { playSegment(index) }
                            )
                        }
                    }
                    .listStyle(.inset)
                }
            }
        }
    }

    private var filteredIndices: [Int] {
        guard let segments = store.project?.transcriptSegments else { return [] }
        guard !query.isEmpty else { return Array(segments.indices) }
        return segments.indices.filter {
            segments[$0].text.localizedCaseInsensitiveContains(query)
                || segments[$0].speaker.localizedCaseInsensitiveContains(query)
        }
    }

    private func segmentBinding(_ index: Int) -> Binding<TranscriptSegment> {
        let original = store.project!.transcriptSegments[index]
        return Binding(
            get: {
                store.project?.transcriptSegments.first(where: { $0.id == original.id }) ?? original
            },
            set: { updated in
                guard let current = store.project?.transcriptSegments.firstIndex(where: { $0.id == original.id }) else { return }
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
