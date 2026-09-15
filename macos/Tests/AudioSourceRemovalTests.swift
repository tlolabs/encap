import XCTest
@testable import EnCap

final class AudioSourceRemovalTests: XCTestCase {
    private func fixture() -> ProjectDocument {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/a.wav", displayName: "A", durationSeconds: 10),
            AudioSource(sourcePath: "/b.wav", displayName: "B", durationSeconds: 20),
            AudioSource(sourcePath: "/c.wav", displayName: "C", durationSeconds: 30),
            AudioSource(sourcePath: "/d.wav", displayName: "D", durationSeconds: 40)
        ]
        project.chapters = [
            Chapter(id: "a", startTimeSeconds: 0, durationSeconds: 10, chapterNumber: 1, title: "Chapter 1"),
            Chapter(id: "b", startTimeSeconds: 10, durationSeconds: 20, chapterNumber: 2, title: "Chapter 2"),
            Chapter(id: "c", startTimeSeconds: 30, durationSeconds: 30, chapterNumber: 3, title: "Chapter 3"),
            Chapter(id: "d", startTimeSeconds: 60, durationSeconds: 40, chapterNumber: 4, title: "Closing", linkUrl: "https://example.com", imagePath: "/art.png")
        ]
        project.video.exportSettings.selectedChapterIds = ["d", "b", "c"]
        project.video.exportSettings.selectionInitialized = true
        return project
    }

    func testDeleteMiddleTrackPreservesSourceLinksTitlesAndMetadata() throws {
        var project = fixture()
        project.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(project.audioSources.map(\.id), ["/a.wav", "/c.wav", "/d.wav"])
        XCTAssertEqual(project.chapters.map(\.id), ["a", "c", "d"])
        XCTAssertEqual(project.chapters.map(\.chapterNumber), [1, 2, 3])
        XCTAssertEqual(project.chapters.map(\.title), ["Chapter 1", "Chapter 2", "Closing"])
        XCTAssertEqual(project.chapters.map(\.startTimeSeconds), [0, 10, 40])
        XCTAssertEqual(project.chapters.map(\.durationSeconds), [10, 30, 40])
        XCTAssertEqual(project.chapters.last?.linkUrl, "https://example.com")
        XCTAssertEqual(project.chapters.last?.imagePath, "/art.png")
        XCTAssertEqual(project.video.exportSettings.selectedChapterIds, ["d", "c"])
        let reopened = try JSONDecoder().decode(ProjectDocument.self, from: JSONEncoder().encode(project))
        XCTAssertEqual(reopened, project)
    }

    func testDeleteMultipleTracksAndAllTheirChapters() {
        var project = fixture()
        project.chapters.insert(Chapter(id: "b-extra", startTimeSeconds: 15, durationSeconds: 5, chapterNumber: 2, title: "Extra"), at: 2)
        project.removeAudioSources(ids: ["/a.wav", "/b.wav"])
        XCTAssertEqual(project.chapters.map(\.id), ["c", "d"])
        XCTAssertEqual(project.chapters.map(\.chapterNumber), [1, 2])
        XCTAssertEqual(project.chapters.map(\.startTimeSeconds), [0, 30])
    }

    func testRemovalUsesSourceReferenceWhenChaptersAreReorderedOrMissing() {
        var project = fixture()
        project.chapters = [project.chapters[3], project.chapters[1]]
        project.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(project.chapters.map(\.id), ["d"])
        XCTAssertEqual(project.chapters.first?.chapterNumber, 3)
        XCTAssertEqual(project.chapters.first?.startTimeSeconds, 40)
    }

    func testTranscriptRemovesDeletedAudioAndShiftsRemainingWords() {
        var project = fixture()
        project.transcriptSegments = [
            TranscriptSegment(id: "before", startTimeSeconds: 0, endTimeSeconds: 5, speaker: "A", text: "Before"),
            TranscriptSegment(id: "overlap", startTimeSeconds: 9, endTimeSeconds: 11, speaker: "A", text: "Crosses cut"),
            TranscriptSegment(id: "deleted", startTimeSeconds: 10, endTimeSeconds: 15, speaker: "A", text: "Deleted"),
            TranscriptSegment(id: "after", startTimeSeconds: 30, endTimeSeconds: 35, speaker: "A", text: "After", words: [
                TranscriptWord(id: "word", startTimeSeconds: 31, endTimeSeconds: 32, text: "After")
            ])
        ]
        project.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(project.transcriptSegments.map(\.id), ["before", "after"])
        XCTAssertEqual(project.transcriptSegments.last?.startTimeSeconds, 10)
        XCTAssertEqual(project.transcriptSegments.last?.endTimeSeconds, 15)
        XCTAssertEqual(project.transcriptSegments.last?.words.first?.startTimeSeconds, 11)
        XCTAssertEqual(project.transcriptSegments.last?.words.first?.endTimeSeconds, 12)
    }

    func testUnknownSelectionIsNoOpAndDeletingAllLeavesEmptyProject() {
        var project = fixture()
        let original = project
        project.removeAudioSources(ids: ["/unknown.wav"])
        XCTAssertEqual(project, original)
        project.removeAudioSources(ids: Set(project.audioSources.map(\.id)))
        XCTAssertTrue(project.audioSources.isEmpty)
        XCTAssertTrue(project.chapters.isEmpty)
        XCTAssertTrue(project.video.exportSettings.selectedChapterIds.isEmpty)
    }

    func testAppendAfterTriageUsesRemainingTimelineAndSkipsDuplicates() {
        var project = fixture()
        project.removeAudioSources(ids: ["/b.wav"])
        let originalChapters = project.chapters
        let added = AudioSource(sourcePath: "/new.wav", displayName: "New", durationSeconds: 15)
        project.appendAudioSources([project.audioSources[0], added, added], namingStyle: .numbered)
        XCTAssertEqual(project.audioSources.count, 4)
        XCTAssertEqual(Array(project.chapters.dropLast()), originalChapters)
        XCTAssertEqual(project.chapters.last?.title, "Chapter 4")
        XCTAssertEqual(project.chapters.last?.chapterNumber, 4)
        XCTAssertEqual(project.chapters.last?.startTimeSeconds, 80)
        XCTAssertEqual(project.chapters.last?.durationSeconds, 15)
        XCTAssertEqual(project.video.exportSettings.selectedChapterIds, ["d", "c"])
    }

    func testAppendToEmptyProjectCreatesChapterAndVideoSelection() {
        var project = ProjectDocument()
        project.video.exportSettings.selectionInitialized = true
        project.appendAudioSources([
            AudioSource(sourcePath: "/09082026061816_DN-700R.wav", displayName: "Recording", durationSeconds: 10)
        ], namingStyle: .time)
        XCTAssertEqual(project.chapters.first?.title, "6:18 AM")
        XCTAssertEqual(project.chapters.first?.startTimeSeconds, 0)
        XCTAssertEqual(project.video.exportSettings.selectedChapterIds, project.chapters.map(\.id))
    }

    @MainActor
    func testOnlyOneRecordingCanPlayAcrossSwitchesAndPauseResume() {
        let store = AppStore()
        let sources = fixture().audioSources
        defer { store.stopPlayback() }
        store.togglePlayback(source: sources[0])
        XCTAssertEqual(sources.filter { store.isPlaying(source: $0) }.map(\.id), [sources[0].id])
        store.togglePlayback(source: sources[1])
        XCTAssertEqual(sources.filter { store.isPlaying(source: $0) }.map(\.id), [sources[1].id])
        store.togglePlayback(source: sources[1])
        XCTAssertFalse(sources.contains { store.isPlaying(source: $0) })
        store.togglePlayback(source: sources[1])
        XCTAssertEqual(sources.filter { store.isPlaying(source: $0) }.map(\.id), [sources[1].id])
        store.togglePlayback(source: sources[0])
        XCTAssertEqual(sources.filter { store.isPlaying(source: $0) }.map(\.id), [sources[0].id])
    }

    @MainActor


    func testStoreBlocksDeletionDuringWorkAndResetsPreviewOnRemoval() {
        let store = AppStore()
        store.project = fixture()
        store.isWorking = true
        store.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(store.project, fixture())
        store.isWorking = false
        store.videoCurrentTime = 45
        store.removeAudioSources(ids: ["/b.wav"])
        XCTAssertEqual(store.project?.audioSources.count, 3)
        XCTAssertEqual(store.videoCurrentTime, 0)
        XCTAssertNil(store.playingSourceID)
        XCTAssertFalse(store.isPlaying)
    }
}
