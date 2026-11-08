import Foundation

extension ProjectDocument {
    /// Remove imported tracks without deleting the user's original recordings.
    mutating func removeAudioSources(ids: Set<AudioSource.ID>) {
        guard audioSources.contains(where: { ids.contains($0.id) }) else { return }
        let removedSourceIDs = Set(audioSources.filter { ids.contains($0.id) }.map(\.transcriptionSourceID))

        var sourceNumbers: [Int: Int] = [:]
        var removedRanges: [Range<Double>] = []
        var sourceStart = 0.0
        var retainedStart = 0.0
        var retainedSourcePositions: [String: (start: Double, duration: Double)] = [:]
        var retainedSources: [AudioSource] = []
        for (index, source) in audioSources.enumerated() {
            let end = sourceStart + source.durationSeconds
            if ids.contains(source.id) {
                removedRanges.append(sourceStart..<end)
            } else {
                retainedSourcePositions[source.transcriptionSourceID] = (retainedStart, source.durationSeconds)
                retainedStart += source.durationSeconds
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
            guard updated.durationSeconds > 0 else { return nil }
            if chapter.title == "Chapter \(oldNumber)" {
                updated.title = "Chapter \(newNumber)"
            }
            return updated
        }
        audioSources = retainedSources

        // Transcription uses the concatenated source timeline too. Remove text
        // touching deleted audio and shift intact segments and word timestamps.
        let previousSegments = transcriptSegments
        transcriptSegments = previousSegments.compactMap { segment in
            if let sourceID = segment.avidCore?.sourceID, removedSourceIDs.contains(sourceID) { return nil }
            if let sourceID = segment.avidCore?.sourceID,
               let position = retainedSourcePositions[sourceID],
               segment.avidCore?.sourceTimelineOffsetSeconds != nil {
                var updated = segment
                updated.reprojectToSource(start: position.start, duration: position.duration)
                return updated
            }
            guard !removedRanges.contains(where: { range in
                segment.startTimeSeconds < range.upperBound && segment.endTimeSeconds > range.lowerBound
            }) else { return nil }
            var updated = segment
            updated.startTimeSeconds = adjustedTime(segment.startTimeSeconds)
            updated.endTimeSeconds = adjustedTime(segment.endTimeSeconds)
            if let offset = updated.avidCore?.sourceTimelineOffsetSeconds {
                updated.avidCore?.sourceTimelineOffsetSeconds = offset + updated.startTimeSeconds - segment.startTimeSeconds
            }
            updated.words = segment.words.map { word in
                var updatedWord = word
                updatedWord.startTimeSeconds = adjustedTime(word.startTimeSeconds)
                updatedWord.endTimeSeconds = adjustedTime(word.endTimeSeconds)
                return updatedWord
            }
            return updated
        }
        transferRemovedTranscriptHistory(from: previousSegments)
        if audioSources.isEmpty {
            chapters = []
            transcriptSegments = []
        }
        let knownChapterIDs = Set(chapters.map(\.id))
        video.exportSettings.selectedChapterIds.removeAll { !knownChapterIDs.contains($0) }
    }

    private mutating func transferRemovedTranscriptHistory(from previous: [TranscriptSegment]) {
        guard !audioSources.isEmpty else {
            avidTranscriptHistory = nil
            avidReconciliationWarning = nil
            return
        }
        let retainedIDs = Set(transcriptSegments.map(\.id))
        var histories: [JSONValue] = []
        var warnings: [String] = []
        for segment in previous where !retainedIDs.contains(segment.id) {
            guard case .object(let fields)? = segment.avidCore?.payload else { continue }
            if case .array(let values)? = fields["previous_transcript"] { histories += values }
            if case .string(let warning)? = fields["reconciliation_warning"] { warnings.append(warning) }
        }
        guard !histories.isEmpty || !warnings.isEmpty else { return }
        let carrier = transcriptSegments.firstIndex(where: { $0.avidCore != nil })
        var fields: [String: JSONValue] = [:]
        if let carrier, case .object(let origin)? = transcriptSegments[carrier].avidCore?.payload { fields = origin }
        var merged = avidTranscriptHistory ?? []
        if carrier != nil {
            if case .array(let values)? = fields["previous_transcript"] { merged = values }
            else { merged = [] }
        }
        for value in histories where !merged.contains(value) { merged.append(value) }
        var mergedWarnings: [String] = avidReconciliationWarning.map { [$0] } ?? []
        if carrier != nil {
            if case .string(let warning)? = fields["reconciliation_warning"] { mergedWarnings = [warning] }
            else { mergedWarnings = [] }
        }
        for warning in warnings where !mergedWarnings.contains(warning) { mergedWarnings.append(warning) }
        if let carrier {
            if !merged.isEmpty { fields["previous_transcript"] = .array(merged) }
            if !mergedWarnings.isEmpty { fields["reconciliation_warning"] = .string(mergedWarnings.joined(separator: "\n")) }
            transcriptSegments[carrier].avidCore?.payload = .object(fields)
        } else {
            if !merged.isEmpty { avidTranscriptHistory = merged }
            if !mergedWarnings.isEmpty { avidReconciliationWarning = mergedWarnings.joined(separator: "\n") }
        }
    }
}

private extension TranscriptSegment {
    mutating func reprojectToSource(start: Double, duration: Double) {
        guard let previousStart = avidCore?.sourceTimelineOffsetSeconds else { return }
        func projected(_ time: Double) -> Double { min(duration, max(0, time - previousStart)) + start }
        startTimeSeconds = projected(startTimeSeconds)
        endTimeSeconds = projected(endTimeSeconds)
        words = words.map { word in
            var updated = word
            updated.startTimeSeconds = projected(word.startTimeSeconds)
            updated.endTimeSeconds = projected(word.endTimeSeconds)
            return updated
        }
        if endTimeSeconds <= startTimeSeconds {
            words = []
            avidCore?.timingStatus = "untimed"
        } else if words.contains(where: { $0.endTimeSeconds <= $0.startTimeSeconds }) {
            words = []
            if avidCore?.timingStatus != "untimed" { avidCore?.timingStatus = "invalidated" }
        }
        avidCore?.sourceTimelineOffsetSeconds = start
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
