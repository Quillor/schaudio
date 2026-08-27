import Foundation
import SwiftUI

struct Highlight: Codable, Identifiable, Sendable, Hashable {
    /// A free-form string, not a UUID: the web app mints ids like "h1756…",
    /// and sync must round-trip them unchanged or the same highlight would
    /// duplicate on every device.
    var id: String = "h" + String(Int(Date().timeIntervalSince1970 * 1000)) + String(Int.random(in: 100...999))
    var paragraph: Int
    var start: Int          // token index
    var end: Int
    var categoryID: String
    var note: String
    var quote: String
    var createdAt: Date = .now
}

struct Bookmark: Codable, Identifiable, Sendable, Hashable {
    var id: String = "b" + String(Int(Date().timeIntervalSince1970 * 1000)) + String(Int.random(in: 100...999))
    var ms: Int
    var label: String
}

struct Category: Codable, Identifiable, Sendable, Hashable {
    var id: String
    var name: String
    var tint: String        // semantic name, resolved in CategoryTint

    static let defaults: [Category] = [
        .init(id: "c1", name: "Key concept", tint: "accent"),
        .init(id: "c2", name: "Definition", tint: "success"),
        .init(id: "c3", name: "Question", tint: "warning"),
        .init(id: "c4", name: "For the exam", tint: "danger"),
    ]
}

struct ChapterState: Codable, Sendable {
    var positionMs: Int = 0
    var highlights: [Highlight] = []
    var bookmarks: [Bookmark] = []
}

struct BookState: Codable, Sendable {
    var chapter: Int = 1
    var chapters: [String: ChapterState] = [:]
}

struct Appearance: Codable, Sendable {
    var textSize: Int = 2       // 0...6, offset applied to the body text style
    var serif: Bool = true
    var lineSpacing: Int = 0    // 0 regular, 1 relaxed, 2 loose
}

/// Everything the reader accumulates, persisted as one JSON document. Mirrors
/// the web app's shape so a future sync can hand the same blob to Supabase.
@Observable
@MainActor
final class Store {
    var books: [String: BookState] = [:]
    var categories: [Category] = Category.defaults
    var voice: Voice = .sam
    var rate: Float = 1.0
    var appearance = Appearance()
    var lastBook: String?
    /// Epoch milliseconds; the tiebreaker when a phone and a browser disagree.
    var updatedAt: Double = 0

    /// Set by SyncService so a local edit schedules a push.
    var onLocalChange: (() -> Void)?

    private let file: URL = URL.documentsDirectory.appending(path: "schaudio-state.json")

    init() { load() }

    // MARK: - Accessors

    func bookState(_ slug: String) -> BookState {
        books[slug] ?? BookState()
    }

    func chapterState(_ slug: String, _ chapter: Int) -> ChapterState {
        bookState(slug).chapters[String(chapter)] ?? ChapterState()
    }

    func update(_ slug: String, _ chapter: Int, _ mutate: (inout ChapterState) -> Void) {
        var b = bookState(slug)
        var c = b.chapters[String(chapter)] ?? ChapterState()
        mutate(&c)
        b.chapters[String(chapter)] = c
        books[slug] = b
        save()
    }

    func setChapter(_ slug: String, _ chapter: Int) {
        var b = bookState(slug)
        b.chapter = chapter
        books[slug] = b
        lastBook = slug
        save()
    }

    func category(_ id: String) -> Category {
        categories.first { $0.id == id } ?? categories[0]
    }

    /// Chapters with any listening progress, for the library tiles.
    func startedChapters(_ slug: String) -> Int {
        bookState(slug).chapters.values.filter { $0.positionMs > 1000 }.count
    }

    // MARK: - Persistence

    private struct Payload: Codable {
        var books: [String: BookState]
        var categories: [Category]
        var voice: String
        var rate: Float
        var appearance: Appearance
        var lastBook: String?
        var updatedAt: Double?
    }

    /// A local edit: stamp it, persist it, and let sync know.
    func save() {
        updatedAt = Date().timeIntervalSince1970 * 1000
        saveLocalOnly()
        onLocalChange?()
    }

    /// Persist without stamping or notifying — used when applying remote state.
    func saveLocalOnly() {
        let payload = Payload(books: books, categories: categories,
                              voice: voice.rawValue, rate: rate,
                              appearance: appearance, lastBook: lastBook,
                              updatedAt: updatedAt)
        // Small document, written atomically off the render path.
        guard let data = try? JSONEncoder().encode(payload) else { return }
        let url = file
        Task.detached(priority: .utility) {
            try? data.write(to: url, options: .atomic)
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: file),
              let p = try? JSONDecoder().decode(Payload.self, from: data) else { return }
        books = p.books
        categories = p.categories.isEmpty ? Category.defaults : p.categories
        voice = Voice(rawValue: p.voice) ?? .sam
        rate = p.rate
        appearance = p.appearance
        lastBook = p.lastBook
        updatedAt = p.updatedAt ?? 0
    }
}

/// Category colours, resolved from the asset catalog so they adapt to dark mode.
enum CategoryTint {
    static func color(_ name: String) -> Color {
        switch name {
        case "success": .green
        case "warning": .orange
        case "danger": .red
        case "info": .teal
        case "secondary": .purple
        default: .accentColor
        }
    }
}
