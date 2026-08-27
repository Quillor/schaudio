import Foundation
import Observation

/// Explicit offline downloads: a book you download plays with no signal at all,
/// and is excluded from iCloud backup so a large audio library doesn't eat the
/// user's storage quota.
@Observable
@MainActor
final class Downloads {
    enum State: Equatable {
        case none
        case downloading(done: Int, total: Int)
        case complete(bytes: Int64)

        var fraction: Double {
            if case .downloading(let done, let total) = self, total > 0 {
                return Double(done) / Double(total)
            }
            return 0
        }
    }

    private(set) var states: [String: State] = [:]      // key: slug
    private var tasks: [String: Task<Void, Never>] = [:]

    private let root: URL = {
        let dir = URL.documentsDirectory.appending(path: "offline", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    func state(_ slug: String) -> State { states[slug] ?? .none }

    /// Local file for a remote audio path, if it has been downloaded.
    func localURL(slug: String, relativePath: String) -> URL? {
        let url = root.appending(path: slug).appending(path: relativePath)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    func refresh(_ book: Book) {
        let dir = root.appending(path: book.slug)
        guard FileManager.default.fileExists(atPath: dir.path) else {
            states[book.slug] = .none
            return
        }
        states[book.slug] = .complete(bytes: Self.size(of: dir))
    }

    /// Downloads every chapter of the book in the given voice.
    func download(book: Book, voice: Voice, library: Library) {
        guard tasks[book.slug] == nil else { return }
        states[book.slug] = .downloading(done: 0, total: book.chapters.count)

        tasks[book.slug] = Task { [weak self] in
            guard let self else { return }
            var completed = 0
            for chapter in book.chapters {
                if Task.isCancelled { break }
                guard let manifest = await library.manifest(slug: book.slug, voice: voice, chapter: chapter.n) else {
                    completed += 1
                    self.states[book.slug] = .downloading(done: completed, total: book.chapters.count)
                    continue
                }
                for paragraph in manifest.paragraphs {
                    if Task.isCancelled { break }
                    await self.fetch(slug: book.slug, relativePath: paragraph.audio, library: library)
                }
                completed += 1
                self.states[book.slug] = .downloading(done: completed, total: book.chapters.count)
            }
            self.tasks[book.slug] = nil
            if Task.isCancelled {
                self.refresh(book)
            } else {
                self.states[book.slug] = .complete(bytes: Self.size(of: self.root.appending(path: book.slug)))
            }
        }
    }

    func cancel(_ slug: String) {
        tasks[slug]?.cancel()
        tasks[slug] = nil
    }

    func remove(_ book: Book) {
        cancel(book.slug)
        try? FileManager.default.removeItem(at: root.appending(path: book.slug))
        states[book.slug] = .none
    }

    // MARK: - Internals

    private func fetch(slug: String, relativePath: String, library: Library) async {
        let destination = root.appending(path: slug).appending(path: relativePath)
        guard !FileManager.default.fileExists(atPath: destination.path) else { return }
        let remote = library.audioURL(slug: slug, relativePath: relativePath)
        guard let (temp, response) = try? await URLSession.shared.download(from: remote),
              let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return }

        let folder = destination.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? FileManager.default.removeItem(at: destination)
        try? FileManager.default.moveItem(at: temp, to: destination)

        // Downloadable-again content must not count against the user's iCloud
        // quota, and Apple rejects apps that back this up.
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutable = destination
        try? mutable.setResourceValues(values)
    }

    private static func size(of directory: URL) -> Int64 {
        guard let enumerator = FileManager.default.enumerator(
            at: directory, includingPropertiesForKeys: [.fileSizeKey]) else { return 0 }
        var total: Int64 = 0
        for case let url as URL in enumerator {
            total += Int64((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        }
        return total
    }

    static func formatted(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}
