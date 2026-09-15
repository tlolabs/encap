import SwiftUI

struct SourceWaveform: Shape {
    var peaks: [Double]
    func path(in rect: CGRect) -> Path {
        var path = Path()
        guard !peaks.isEmpty, rect.width >= 3, rect.height > 0 else { return path }
        let count = min(64, max(1, Int(rect.width / 3)))
        for bar in 0..<count {
            let first = peaks.count * bar / count
            let end = peaks.count * (bar + 1) / count
            let peak = first < end ? peaks[first..<end].max() ?? 0 : 0
            let height = max(1, rect.height * min(1, max(0, peak)))
            let step = rect.width / CGFloat(count)
            path.addRoundedRect(in: CGRect(x: rect.minX + CGFloat(bar) * step, y: rect.maxY - height,
                                           width: max(1, step - 1), height: height), cornerSize: CGSize(width: 0.6, height: 0.6))
        }
        return path
    }
}

/// Visible rows enqueue work; a single background engine job runs at a time.
@MainActor
final class SourceWaveforms: ObservableObject {
    @Published private(set) var peaks: [String: [Double]] = [:]
    private var visible: Set<String> = []
    private var pending: [String] = []
    private var active: String?
    private var worker: Task<Void, Never>?
    private let engine = EngineClient()
    private var generation = UUID()

    func show(_ path: String) {
        visible.insert(path)
        guard peaks[path] == nil, active != path, !pending.contains(path) else { return }
        pending.append(path)
        guard worker == nil else { return }
        let generation = generation
        worker = Task(priority: .utility) { [weak self] in
            try? await Task.sleep(nanoseconds: 150_000_000)
            guard let self else { return }
            while !Task.isCancelled, self.generation == generation, !pending.isEmpty {
                let path = pending.removeFirst()
                guard visible.contains(path) else { continue }
                active = path
                let result = try? await engine.waveform(path: path)
                guard !Task.isCancelled, self.generation == generation else { return }
                peaks[path] = result?.peaks ?? []
                if peaks.count > 512, let unused = peaks.keys.first(where: { !self.visible.contains($0) }) { peaks.removeValue(forKey: unused) }
                active = nil
            }
            if self.generation == generation { worker = nil }
        }
    }

    func hide(_ path: String) { visible.remove(path); pending.removeAll { $0 == path } }
    func stop() {
        generation = UUID()
        worker?.cancel(); worker = nil
        engine.cancelCurrentOperation()
        pending.removeAll(); visible.removeAll(); active = nil
    }
    func retain(_ paths: Set<String>) { peaks = peaks.filter { paths.contains($0.key) } }
}

struct WaveformResponse: Decodable { let peaks: [Double] }
