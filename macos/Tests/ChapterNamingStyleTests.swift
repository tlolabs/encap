import XCTest
@testable import EnCap

final class ChapterNamingStyleTests: XCTestCase {
    func testSharedPlatformTimestampCases() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let text = try String(contentsOf: root.appendingPathComponent("tests/fixtures/chapter-times.tsv"), encoding: .utf8)
        let lines = text.split(separator: "\n").filter { !$0.hasPrefix("#") }
        XCTAssertFalse(lines.isEmpty)
        for line in lines {
            let fields = line.split(separator: "\t").map(String.init)
            XCTAssertEqual(fields.count, 2)
            guard fields.count == 2 else { continue }
            XCTAssertEqual(ChapterNamingStyle.roundedTime(from: fields[0]), fields[1] == "-" ? nil : fields[1], fields[0])
        }
    }

    func testArchivedSourcesAndSplitChaptersUseOriginalTimeAndDisplayOrder() {
        var project = ProjectDocument()
        project.audioSources = [AudioSource(sourcePath: "/session/audio/001-09082026061816_DN-700R.wav", displayName: "09082026061816_DN-700R", durationSeconds: 60)]
        project.chapters = [
            Chapter(startTimeSeconds: 0, durationSeconds: 30, chapterNumber: 1, title: "Opening"),
            Chapter(startTimeSeconds: 30, durationSeconds: 30, chapterNumber: 1, title: "Closing")
        ]
        project.applyChapterNames(.time)
        XCTAssertEqual(project.chapters.map(\.title), ["6:18 AM", "6:18 AM"])
        project.applyChapterNames(.numbered)
        XCTAssertEqual(project.chapters.map(\.title), ["Chapter 1", "Chapter 2"])
        XCTAssertEqual(project.chapters.map(\.chapterNumber), [1, 1])
    }

    func testFilenameTimeRoundsToNearestMinute() {
        let cases = [
            "09082026061816_DN-700R.wav": "6:18 AM",
            "09082026061829_DN-700R.wav": "6:18 AM",
            "09082026061830_DN-700R.wav": "6:19 AM",
            "09082026062958_DN-700R.wav": "6:30 AM",
            "09082026115930_DN-700R.wav": "12:00 PM",
            "09082026120000_DN-700R.wav": "12:00 PM",
            "12312026235959_DN-700R.wav": "12:00 AM",
            "01012026000000_DN-700R.wav": "12:00 AM",
            "02292024183030_DN-700R.aiff": "6:31 PM"
        ]
        for (filename, expected) in cases {
            XCTAssertEqual(ChapterNamingStyle.roundedTime(from: "/recordings/\(filename)"), expected, filename)
        }
    }

    func testInvalidTimestampsKeepOriginalName() {
        for filename in ["Interview.wav", "09082026.wav", "0908202606xx00.wav", "02292025061816.wav",
                         "02302026061816.wav", "13082026061816.wav", "09082026240000.wav",
                         "09082026066000.wav", "09082026061860.wav", "09080000061816.wav"] {
            let source = AudioSource(sourcePath: filename, displayName: "Original name", durationSeconds: 30)
            XCTAssertNil(ChapterNamingStyle.roundedTime(from: filename), filename)
            XCTAssertEqual(ChapterNamingStyle.time.title(for: source, chapterNumber: 1), "Original name")
        }
    }

    func testNamingCanBeReappliedWithoutLosingChapterMetadata() throws {
        var project = ProjectDocument()
        project.audioSources = [
            AudioSource(sourcePath: "/audio/09082026061816_DN-700R.wav", displayName: "09082026061816_DN-700R", durationSeconds: 36),
            AudioSource(sourcePath: "/audio/09082026062958_DN-700R.wav", displayName: "09082026062958_DN-700R", durationSeconds: 24)
        ]
        project.chapters = [
            Chapter(id: "first", startTimeSeconds: 0, durationSeconds: 36, chapterNumber: 1, title: "Edited", linkUrl: "https://example.com", imagePath: "/artwork.png"),
            Chapter(id: "second", startTimeSeconds: 36, durationSeconds: 24, chapterNumber: 2, title: "Edited too"),
            Chapter(id: "manual", startTimeSeconds: 60, durationSeconds: 5, chapterNumber: 3, title: "Closing")
        ]
        let original = project.chapters
        project.applyChapterNames(.custom)
        XCTAssertEqual(project.chapters, original)
        project.applyChapterNames(.time)
        XCTAssertEqual(project.chapters.map(\.title), ["6:18 AM", "6:30 AM", "Closing"])
        project.applyChapterNames(.original)
        XCTAssertEqual(project.chapters.map(\.title), project.audioSources.map(\.displayName) + ["Closing"])
        project.applyChapterNames(.numbered)
        XCTAssertEqual(project.chapters.map(\.title), ["Chapter 1", "Chapter 2", "Chapter 3"])
        for index in original.indices {
            var chapter = project.chapters[index]
            chapter.title = original[index].title
            XCTAssertEqual(chapter, original[index])
        }
        let reopened = try JSONDecoder().decode(ProjectDocument.self, from: JSONEncoder().encode(project))
        XCTAssertEqual(reopened.chapters, project.chapters)
    }
}
