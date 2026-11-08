import SwiftUI

struct TranscriptView: View {
    @ObservedObject var store: AppStore

    var body: some View {
        if store.project == nil {
            EmptyStateView(
                "No Project", systemImage: "text.bubble",
                description: "Import audio before creating a transcript."
            )
        } else {
            VStack(spacing: 0) {
                controls
                    .padding(12)
                Divider()
                if filteredIndices.isEmpty {
                    EmptyStateView(
                        store.transcriptSearch.isEmpty ? "No Transcript" : "No Matching Segments",
                        systemImage: "captions.bubble",
                        description: store.transcriptSearch.isEmpty
                            ? "Install a shared AVID model, then transcribe this episode locally."
                            : "Try another search or clear the search field."
                    )
                } else {
                    List {
                        ForEach(filteredIndices, id: \.self) { index in
                            TranscriptRow(
                                segment: segmentBinding(index), showSpeaker: store.transcriptShowsSpeakers,
                                play: { playSegment(index) }
                            )
                        }
                    }
                    .listStyle(.inset)
                    .disabled(store.isWorking)
                }
            }
            .sheet(isPresented: $store.isModelManagerPresented) { ModelManagerView(store: store) }
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !store.transcriptionAvailability.available {
                Label(store.transcriptionAvailability.reason ?? "AVID Core transcription is unavailable on this system.",
                      systemImage: "info.circle")
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            if let warning = store.transcriptionReconciliationWarning {
                Label(warning, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.orange)
                    .textSelection(.enabled)
                    .accessibilityLabel("Transcript metadata review: \(warning)")
            }
            HStack {
                Picker("Recognition model", selection: $store.selectedProviderID) {
                    if !store.providers.contains(where: { $0.id == "whisper-large-v3" }) {
                        Text("Whisper large-v3 — quality default (install model)").tag("whisper-large-v3")
                    }
                    if store.selectedProviderID != "whisper-large-v3",
                       !store.providers.contains(where: { $0.id == store.selectedProviderID }) {
                        Text("\(store.selectedProviderID) — unavailable").tag(store.selectedProviderID)
                    }
                    ForEach(store.providers) { provider in Text(provider.name).tag(provider.id) }
                }
                .frame(maxWidth: 420)
                .disabled(store.isWorking || !store.transcriptionAvailability.available)
                Button("Transcribe", action: store.transcribe)
                    .buttonStyle(.borderedProminent)
                    .disabled(!store.canTranscribe)
                    .help("Replace the transcript using verified local model files")
                Button("Manage Models…", action: store.presentModelManager)
                    .help("Install, import or remove models in the shared AVID cache")
                Spacer()
                TextField("Search transcript", text: $store.transcriptSearch)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 220)
            }
            HStack {
                Picker("Alignment", selection: $store.selectedAlignmentModelID) {
                    Text("Native timing only").tag("")
                    if !store.selectedAlignmentModelID.isEmpty,
                       !store.alignmentModels.contains(where: { $0.id == store.selectedAlignmentModelID }) {
                        Text("\(store.selectedAlignmentModelID) — install model").tag(store.selectedAlignmentModelID)
                    }
                    ForEach(store.alignmentModels) { model in Text(model.name).tag(model.id) }
                }
                .frame(maxWidth: 340)
                .help("Optional forced alignment. Recognition and alignment have separate language support.")
                TextField("Language code (blank = automatic)", text: $store.transcriptionLanguage)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 240)
                    .help("Use a language code such as en or pt-BR. Unsupported alignment languages return an error.")
                Button("Realign Edited Text", action: store.realignTranscript)
                    .disabled(!store.canRealign)
                    .help("Align the saved transcript text without recognizing it again. Install and select an alignment model first.")
            }
            .disabled(store.isWorking || !store.transcriptionAvailability.available)
            HStack {
                Toggle("Word timing", isOn: Binding(
                    get: { store.project?.transcriptSettings.includeWordTimestamps ?? false },
                    set: { store.project?.transcriptSettings.includeWordTimestamps = $0 }
                ))
                .help("Retain available word timing; untimed models require an alignment model for timed words")
                Toggle("Show Speakers", isOn: $store.transcriptShowsSpeakers)
                Spacer()
                Button("Word Captions SRT…") { store.presentTranscriptSavePanel(format: "srt", wordCaptions: true) }
                    .disabled(!store.canExportWordCaptions)
                    .help("Group valid timed words into SRT cues using AVID Core")
                Button("Word Captions WebVTT…") { store.presentTranscriptSavePanel(format: "vtt", wordCaptions: true) }
                    .disabled(!store.canExportWordCaptions)
                    .help("Export valid timed word captions as WebVTT. Subtitle files do not include animated video rendering.")
            }
            .disabled(store.isWorking)
            Text("Text edits clear word alignment. Speaker names stay editable; choose Realign Edited Text to restore word timing. Models and audio remain on this device.")
                .font(.caption).foregroundStyle(.secondary)
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
        let fallback = TranscriptSegment(id: UUID().uuidString, startTimeSeconds: 0,
                                         endTimeSeconds: 0, speaker: "", text: "")
        guard let segments = store.project?.transcriptSegments, segments.indices.contains(index) else {
            return .constant(fallback)
        }
        let targetID = segments[index].id
        return Binding(
            get: { store.project?.transcriptSegments.first(where: { $0.id == targetID }) ?? segments[index] },
            set: { updated in
                guard let current = store.project?.transcriptSegments.firstIndex(where: { $0.id == targetID }) else { return }
                var retained = updated
                let original = store.project!.transcriptSegments[current]
                if original.text != updated.text {
                    // Pass the previous text through the model operation so the
                    // immutable recognition payload survives while words expire.
                    retained = original
                    retained.speaker = updated.speaker
                    retained.replaceText(updated.text)
                }
                store.project?.transcriptSegments[current] = retained
            }
        )
    }

    private func playSegment(_ index: Int) {
        guard let project = store.project, project.transcriptSegments.indices.contains(index) else { return }
        guard project.transcriptSegments[index].avidCore?.timingStatus != "untimed" else { return }
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
                    Text("Shared AVID Transcription Models").font(.title2).bold()
                    Text("Anonymous pinned downloads are verified with SHA-256. Installed models run offline; source audio is never uploaded.")
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Done") { store.isModelManagerPresented = false }
                    .keyboardShortcut(.defaultAction)
            }
            Text("Removal affects the shared AVID cache used by other AVID apps. Imported source folders, legacy EnCap GGML files and other applications' caches are preserved. Legacy .bin weights require a replacement download.")
                .font(.callout).foregroundStyle(.secondary)
            if !store.transcriptionAvailability.available {
                Label(store.transcriptionAvailability.reason ?? "Transcription is unavailable.", systemImage: "info.circle")
            }
            List(store.transcriptionModels) { model in
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(model.name + (model.isDefault == true ? " — quality default" : "")).font(.headline)
                            Text("\(model.downloadSize) · \(model.isAligner ? "Alignment" : "Recognition") · \(model.installationSummary)")
                                .font(.caption).foregroundStyle(.secondary)
                            Text(model.description).font(.callout)
                        }
                        Spacer()
                        Button("Import…") { store.importModel(model) }
                            .help("Copy and verify exact catalog-compatible files, preserving the original folder")
                        if model.installed {
                            Button("Remove Shared Copy", role: .destructive) { store.removeModel(model) }
                        } else {
                            Button("Download") { store.installModel(model) }
                                .buttonStyle(.borderedProminent)
                                .disabled(!model.downloadAllowed)
                        }
                    }
                    Text("Recognition languages: \(model.recognitionLanguageSummary)")
                        .font(.caption).textSelection(.enabled)
                    Text("Word timing / alignment languages: \(model.timingLanguageSummary)")
                        .font(.caption).textSelection(.enabled)
                    if let license = model.license {
                        Text("License: \(license.identifier) · \(license.notice)")
                            .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    }
                }
                .padding(.vertical, 6)
                .disabled(store.isWorking || !store.transcriptionAvailability.available)
            }
            .overlay { if store.modelCatalogLoading { ProgressView("Loading shared model catalog…") } }
            if store.isWorking {
                HStack {
                    ProgressView().controlSize(.small)
                    Text(store.status)
                    Spacer()
                    Button("Cancel", action: store.cancelCurrentOperation)
                        .help("Cancel this operation; model kernels may finish before cleanup completes")
                }
            }
        }
        .padding(20)
        .frame(minWidth: 760, minHeight: 500)
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
                    .labelStyle(.titleAndIcon).monospacedDigit()
            }
            .buttonStyle(.plain).foregroundStyle(.secondary)
            .disabled(segment.avidCore?.timingStatus == "untimed")
            .frame(width: 84, alignment: .leading)
            .help("Play audio starting at \(EnCapFormatters.timestamp(segment.startTimeSeconds))")
            if showSpeaker { TextField("Speaker", text: $segment.speaker).frame(width: 120) }
            VStack(alignment: .leading, spacing: 2) {
                TextField("Transcript text", text: $segment.text, axis: .vertical).lineLimit(1...5)
                if segment.words.isEmpty {
                    Text(segment.avidCore?.timingStatus == "untimed" ? "Untimed text — align before timed export" : "No valid word alignment").font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}
