import Foundation

enum ChapterNamingStyle: String, CaseIterable, Identifiable {
    case original = "Original"
    case numbered = "Chapter #"
    case time = "Time"
    case custom = "Custom"

    static let preferenceKey = "chapterNamingStyle"
    var id: String { rawValue }

    func title(for source: AudioSource?, chapterNumber: Int) -> String? {
        switch self {
        case .custom:
            return nil
        case .original:
            return source?.displayName
        case .numbered:
            return "Chapter \(chapterNumber)"
        case .time:
            guard let source else { return nil }
            return Self.roundedTime(from: source.displayName)
                ?? Self.roundedTime(from: source.sourcePath) ?? source.displayName
        }
    }

    static func roundedTime(from sourcePath: String) -> String? {
        let filename = URL(fileURLWithPath: sourcePath).lastPathComponent
        let digits = Array(filename.utf8.prefix(14))
        guard digits.count == 14, digits.allSatisfy({ (48...57).contains($0) }) else { return nil }
        func number(_ range: Range<Int>) -> Int {
            digits[range].reduce(0) { $0 * 10 + Int($1 - 48) }
        }
        let month = number(0..<2)
        let day = number(2..<4)
        let year = number(4..<8)
        let hour = number(8..<10)
        let minute = number(10..<12)
        let second = number(12..<14)
        guard (1...9999).contains(year), (1...12).contains(month), (1...31).contains(day),
              (0...23).contains(hour), (0...59).contains(minute), (0...59).contains(second) else { return nil }

        // Validate the date without interpreting the recorder's wall clock in the Mac's time zone.
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let components = DateComponents(year: year, month: month, day: day)
        guard let date = calendar.date(from: components),
              calendar.dateComponents([.year, .month, .day], from: date) == components else { return nil }

        let roundedMinutes = (hour * 60 + minute + (second >= 30 ? 1 : 0)) % (24 * 60)
        let roundedHour = roundedMinutes / 60
        let displayHour = roundedHour % 12 == 0 ? 12 : roundedHour % 12
        return String(format: "%d:%02d %@", displayHour, roundedMinutes % 60, roundedHour < 12 ? "AM" : "PM")
    }
}

extension ProjectDocument {
    mutating func applyChapterNames(_ style: ChapterNamingStyle) {
        for index in chapters.indices {
            // Chapter numbers use the same source lookup as audio/video playback and export.
            let sourceIndex = chapters[index].chapterNumber - 1
            let source = audioSources.indices.contains(sourceIndex) ? audioSources[sourceIndex] : nil
            if let title = style.title(for: source, chapterNumber: index + 1) {
                chapters[index].title = title
            }
        }
    }
}
