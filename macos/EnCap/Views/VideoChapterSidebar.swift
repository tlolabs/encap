import AppKit
import SwiftUI

struct VideoChapterSidebar: View {
    @ObservedObject var store: AppStore
    @State private var selectedID: Chapter.ID?

    private var included: [Chapter] { store.selectedVideoChapters }
    private var excluded: [Chapter] {
        let ids = Set(included.map(\.id))
        return (store.project?.chapters ?? []).filter { !ids.contains($0.id) }
    }
    private var selectedIndex: Int? { included.firstIndex { $0.id == selectedID } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Video Chapters").font(.headline)
                Text("\(included.count) of \(store.project?.chapters.count ?? 0) included · \(EnCapFormatters.timestamp(store.selectedVideoDuration))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Select All") { store.selectAllVideoChapters(true) }
                    Button("Select None") { store.selectAllVideoChapters(false) }
                }
            }
            .padding(12)
            Divider()
            List(selection: $selectedID) {
                Section("Included · Video order") {
                    ForEach(included) { chapter in
                        chapterRow(chapter, isIncluded: true)
                            .tag(chapter.id)
                    }
                    .onMove(perform: store.moveVideoChapters)
                    if included.isEmpty {
                        Text("Check chapters below to include them.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if !excluded.isEmpty {
                    Section("Not included") {
                        ForEach(excluded) { chapter in
                            chapterRow(chapter, isIncluded: false)
                                .tag(chapter.id)
                        }
                    }
                }
            }
            .listStyle(.sidebar)
            .accessibilityLabel("Video chapter inclusion and order")
            Divider()
            VStack(alignment: .leading, spacing: 8) {
                Text("Drag included chapters to reorder.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Move Up") { moveSelected(-1) }
                        .disabled(selectedIndex == nil || selectedIndex == 0)
                        .help("Move the selected chapter earlier in the video")
                    Button("Move Down") { moveSelected(1) }
                        .disabled(selectedIndex == nil || selectedIndex == included.count - 1)
                        .help("Move the selected chapter later in the video")
                }
            }
            .padding(12)
        }
    }

    private func chapterRow(_ chapter: Chapter, isIncluded: Bool) -> some View {
        HStack(spacing: 8) {
            Toggle(isOn: Binding(
                get: { store.selectedVideoChapters.contains { $0.id == chapter.id } },
                set: { store.setVideoChapter(chapter, selected: $0) }
            )) {
                Text(title(for: chapter))
            }
            .labelsHidden()
            .toggleStyle(.checkbox)
            .accessibilityLabel("Include \(title(for: chapter)) in video")
            .help("Include or exclude this chapter from the video")
            thumbnail(chapter)
            VStack(alignment: .leading, spacing: 2) {
                Text(title(for: chapter)).lineLimit(1).help(title(for: chapter))
                Text(EnCapFormatters.timestamp(chapter.durationSeconds))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 3)
        .contentShape(Rectangle())
        .contextMenu {
            if isIncluded {
                Button("Preview Chapter") {
                    if let index = included.firstIndex(where: { $0.id == chapter.id }) {
                        store.jumpToVideoChapter(index)
                    }
                }
            }
        }
    }

    private func title(for chapter: Chapter) -> String {
        chapter.title.isEmpty ? "Chapter \(chapter.chapterNumber)" : chapter.title
    }

    private func moveSelected(_ direction: Int) {
        guard let selectedID else { return }
        store.moveVideoChapter(id: selectedID, direction: direction)
    }

    private func thumbnail(_ chapter: Chapter) -> some View {
        Group {
            if let url = store.effectiveArtwork(for: chapter), let image = NSImage(contentsOf: url) {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                Image(systemName: "photo").foregroundStyle(.secondary)
            }
        }
        .frame(width: 28, height: 28)
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .accessibilityHidden(true)
    }
}
