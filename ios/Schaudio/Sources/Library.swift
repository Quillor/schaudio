import Foundation

/// Content lives where the web app's `window.SCHAUDIO.mediaBase` points so the
/// phone and the browser never drift apart. The 2.6 GB corpus moved off Vercel
/// to Cloudflare R2 (see tools/publish_r2.py) — the old /app/books path now
/// 404s, so this must match `app/index.html`. Everything fetched is cached on
/// disk, so a chapter you have already opened keeps working with no signal.
@Observable
@MainActor
final class Library {
    static let base = URL(string: "https://pub-83aebd7fcc2b48538b1f792814c1fc14.r2.dev/books")!
    static let slugs = ["lifespan", "counseling", "research-methods", "wampold-common-factors"]

    private(set) var books: [Book] = []
    private(set) var loadError: String?
    private var manifests: [String: Manifest] = [:]   // "slug-voice-chapter"

    private let cache: URL = {
        let dir = URL.cachesDirectory.appending(path: "schaudio", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }()

    func load() async {
        guard books.isEmpty else { return }
        var loaded: [Book] = []
        for slug in Self.slugs {
            do {
                let data = try await fetch(path: "\(slug)/book.json")
                loaded.append(try JSONDecoder().decode(Book.self, from: data))
            } catch {
                loadError = "Couldn't load \(slug): \(error.localizedDescription)"
            }
        }
        books = loaded
        if !loaded.isEmpty { loadError = nil }
    }

    func manifest(slug: String, voice: Voice, chapter: Int) async -> Manifest? {
        let key = "\(slug)-\(voice.rawValue)-\(chapter)"
        if let m = manifests[key] { return m }
        let name = String(format: "%@-ch%02d.json", voice.rawValue, chapter)
        do {
            let data = try await fetch(path: "\(slug)/manifests/\(name)")
            let m = try JSONDecoder().decode(Manifest.self, from: data)
            manifests[key] = m
            return m
        } catch {
            return nil
        }
    }

    func coverURL(slug: String) -> URL { Self.base.appending(path: "\(slug)/cover.png") }

    func audioURL(slug: String, relativePath: String) -> URL {
        Self.base.appending(path: "\(slug)/\(relativePath)")
    }

    /// Network first, disk cache as the offline fallback.
    private func fetch(path: String) async throws -> Data {
        let file = cache.appending(path: path.replacingOccurrences(of: "/", with: "_"))
        do {
            let (data, response) = try await URLSession.shared.data(from: Self.base.appending(path: path))
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                throw URLError(.badServerResponse)
            }
            try? data.write(to: file)
            return data
        } catch {
            if let cached = try? Data(contentsOf: file) { return cached }
            throw error
        }
    }
}
