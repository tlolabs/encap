import Foundation

extension ProjectDocument {
    /// Remove imported tracks without deleting the user's original recordings.
    mutating func removeAudioSources(ids: Set<AudioSource.ID>) {
        guard audioSources.contains(where: { ids.contains($0.id) }) else { return }

        var sourceNumbers: [Int: Int] = [:]
        var removedRanges: [Range<Double>] = []
        var sourceStart = 0.0
        var retainedSources: [AudioSource] = []
        for (index, source) in audioSources.enumerated() {
            let end = sourceStart + source.durationSeconds
            if ids.contains(source.id) {
                removedRanges.append(sourceStart..<end)
            } else {
                retainedSources.append(source)
                sourceNumbers[index + 1] = retainedSources.count
            }
            sourceStart = end
        }

        func adjustedTime(_ time: Double) -> Double {
            time - removedRanges.reduce(0) { removed, range in
                removed + max(0, min(time, range.upperBound) - range.lowerBound)
            }
        }

        chapters = chapters.compactMap { chapter in
            // chapterNumber is a source reference, not the chapter's row position.
            let oldNumber = audioSources.indices.contains(chapter.chapterNumber - 1)
                ? chapter.chapterNumber : audioSourceIndex(at: chapter.startTimeSeconds) + 1
            guard let newNumber = sourceNumbers[oldNumber] else { return nil }
            var updated = chapter
            updated.chapterNumber = newNumber
            updated.startTimeSeconds = adjustedTime(chapter.startTimeSeconds)
            updated.durationSeconds = max(0, adjustedTime(chapter.startTimeSeconds + chapter.durationSeconds) - updated.startTimeSeconds)
            if chapter.title == "Chapter \(oldNumber)" {
                updated.title = "Chapter \(newNumber)"
            }
            return updated
        }
        audioSources = retainedSources

        // Transcription uses the concatenated source timeline too. Remove text
        // touching deleted audio and shift intact segments and word timestamps.
        transcriptSegments = transcriptSegments.compactMap { segment in
            guard !removedRanges.contains(where: { range in
                segment.startTimeSeconds < range.upperBound && segment.endTimeSeconds > range.lowerBound
            }) else { return nil }
            var updated = segment
            updated.startTimeSeconds = adjustedTime(segment.startTimeSeconds)
            updated.endTimeSeconds = adjustedTime(segment.endTimeSeconds)
            updated.words = segment.words.map { word in
                var updatedWord = word
                updatedWord.startTimeSeconds = adjustedTime(word.startTimeSeconds)
                updatedWord.endTimeSeconds = adjustedTime(word.endTimeSeconds)
                return updatedWord
            }
            return updated
        }
        if audioSources.isEmpty {
            chapters = []
            transcriptSegments = []
        }
        let knownChapterIDs = Set(chapters.map(\.id))
        video.exportSettings.selectedChapterIds.removeAll { !knownChapterIDs.contains($0) }
    }
}

extension ProjectDocument {
    mutating func appendAudioSources(_ sources: [AudioSource], namingStyle: ChapterNamingStyle) {
        var known = Set(audioSources.map(\.id))
        var start = audioSources.reduce(0) { $0 + $1.durationSeconds }
        let selectNewChapters = !video.exportSettings.selectionInitialized
            || Set(video.exportSettings.selectedChapterIds) == Set(chapters.map(\.id))
        for source in sources where known.insert(source.id).inserted {
            audioSources.append(source)
            let number = audioSources.count
            let chapter = Chapter(
                startTimeSeconds: start,
                durationSeconds: source.durationSeconds,
                chapterNumber: number,
                title: namingStyle.title(for: source, chapterNumber: chapters.count + 1) ?? source.displayName
            )
            chapters.append(chapter)
            if selectNewChapters && video.exportSettings.selectionInitialized {
                video.exportSettings.selectedChapterIds.append(chapter.id)
            }
            start += source.durationSeconds
        }
    }
}
