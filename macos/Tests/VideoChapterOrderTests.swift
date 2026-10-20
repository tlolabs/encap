import XCTest
@testable import EnCap

final class VideoChapterOrderTests: XCTestCase {
    private func fixture() -> ProjectDocument {
        var project = ProjectDocument()
        project.audioSources = [AudioSource(sourcePath: "/episode.wav", displayName: "Episode", durationSeconds: 30)]
        project.chapters = [
            Chapter(id: "a", startTimeSeconds: 0, durationSeconds: 10, chapterNumber: 1, title: "Opening"),
            Chapter(id: "b", startTimeSeconds: 10, durationSeconds: 10, chapterNumber: 1, title: "Middle"),
            Chapter(id: "c", startTimeSeconds: 20, durationSeconds: 10, chapterNumber: 1, title: "Closing")
        ]
        project.metadata.artworkPath = "/cover.png"
        return project
    }

    @MainActor
    func testVideoReorderPersistsWithoutChangingAudioChapterOrder() throws {
        let original = fixture()
        let store = AppStore()
        store.project = original
        store.videoCurrentTime = 12
        store.moveVideoChapter(id: "a", direction: 1)
        XCTAssertEqual(store.selectedVideoChapters.map(\.id), ["b", "a", "c"])
        XCTAssertEqual(store.videoCurrentTime, 0)
        store.moveVideoChapters(from: IndexSet(integer: 2), to: 0)
        XCTAssertEqual(store.selectedVideoChapters.map(\.id), ["c", "b", "a"])
        XCTAssertEqual(store.project?.chapters, original.chapters)
        XCTAssertEqual(store.project?.audioSources, original.audioSources)
        let data = try JSONEncoder().encode(XCTUnwrap(store.project))
        let reopened = try JSONDecoder().decode(ProjectDocument.self, from: data)
        XCTAssertEqual(reopened.video.exportSettings.selectedChapterIds, ["c", "b", "a"])
    }

    @MainActor
    func testExcludedChapterCanBeReincludedAfterReordering() {
        let store = AppStore()
        store.project = fixture()
        let middle = store.project!.chapters[1]
        store.setVideoChapter(middle, selected: false)
        store.moveVideoChapter(id: "c", direction: -1)
        XCTAssertEqual(store.selectedVideoChapters.map(\.id), ["c", "a"])
        store.setVideoChapter(middle, selected: true)
        XCTAssertEqual(store.selectedVideoChapters.map(\.id), ["c", "a", "b"])
        XCTAssertEqual(store.selectedVideoDuration, 30)
        XCTAssertEqual(store.project?.chapters.map(\.id), ["a", "b", "c"])
    }

    @MainActor
    func testVideoExportAvailabilityTracksInclusionArtworkAndWork() {
        let store = AppStore()
        XCTAssertFalse(store.canExportVideo)
        store.project = fixture()
        XCTAssertTrue(store.canExportVideo)
        store.selectAllVideoChapters(false)
        XCTAssertFalse(store.canExportVideo)
        store.selectAllVideoChapters(true)
        store.project?.metadata.artworkPath = nil
        XCTAssertFalse(store.canExportVideo)
        store.project?.metadata.artworkPath = "/cover.png"
        store.isWorking = true
        XCTAssertFalse(store.canExportVideo)
    }
}
