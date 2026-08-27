import Foundation

/// The document stored in Supabase `user_state.data`.
///
/// The field names here are the WEB app's names, deliberately. The iOS models
/// use Swift-natural names, so this file is the translation layer that lets a
/// phone and a browser read and write the same row. Change nothing here without
/// changing app/app.js to match.
struct SyncPayload: Codable, Sendable {
    var books: [String: SyncBook]
    var categories: [SyncCategory]
    var voice: String
    var speed: Double
    var appearance: SyncAppearance
    var lastBook: String?
    var updatedAt: Double        // epoch milliseconds, matches Date.now() in JS

    struct SyncBook: Codable, Sendable {
        var chapter: Int
        var chapters: [String: SyncChapter]
    }

    struct SyncChapter: Codable, Sendable {
        var positionMs: Int
        var highlights: [SyncHighlight]
        var bookmarks: [SyncBookmark]
    }

    struct SyncHighlight: Codable, Sendable {
        var id: String
        var p: Int
        var w0: Int
        var w1: Int
        var catId: String
        var note: String
        var quote: String
        var createdMs: Double
    }

    struct SyncBookmark: Codable, Sendable {
        var id: String
        var ms: Int
        var label: String
    }

    struct SyncCategory: Codable, Sendable {
        var id: String
        var name: String
        var color: String
    }

    struct SyncAppearance: Codable, Sendable {
        var size: Int
        var font: String     // "serif" | "sans" | "legible"
        var space: String    // "regular" | "relaxed" | "loose"
    }
}

extension Store {
    /// Local state → the shared wire document.
    func makePayload() -> SyncPayload {
        var out: [String: SyncPayload.SyncBook] = [:]
        for (slug, book) in books {
            var chapters: [String: SyncPayload.SyncChapter] = [:]
            for (key, chapter) in book.chapters {
                chapters[key] = SyncPayload.SyncChapter(
                    positionMs: chapter.positionMs,
                    highlights: chapter.highlights.map {
                        .init(id: $0.id, p: $0.paragraph, w0: $0.start, w1: $0.end,
                              catId: $0.categoryID, note: $0.note, quote: $0.quote,
                              createdMs: $0.createdAt.timeIntervalSince1970 * 1000)
                    },
                    bookmarks: chapter.bookmarks.map {
                        .init(id: $0.id, ms: $0.ms, label: $0.label)
                    }
                )
            }
            out[slug] = .init(chapter: book.chapter, chapters: chapters)
        }
        return SyncPayload(
            books: out,
            categories: categories.map { .init(id: $0.id, name: $0.name, color: $0.tint) },
            voice: voice.rawValue,
            speed: Double(rate),
            appearance: .init(size: appearance.textSize,
                              font: appearance.serif ? "serif" : "sans",
                              space: ["regular", "relaxed", "loose"][min(appearance.lineSpacing, 2)]),
            lastBook: lastBook,
            updatedAt: updatedAt
        )
    }

    /// The shared wire document → local state.
    func apply(_ payload: SyncPayload) {
        var out: [String: BookState] = [:]
        for (slug, book) in payload.books {
            var chapters: [String: ChapterState] = [:]
            for (key, chapter) in book.chapters {
                chapters[key] = ChapterState(
                    positionMs: chapter.positionMs,
                    highlights: chapter.highlights.map {
                        Highlight(id: $0.id,
                                  paragraph: $0.p, start: $0.w0, end: $0.w1,
                                  categoryID: $0.catId, note: $0.note, quote: $0.quote,
                                  createdAt: Date(timeIntervalSince1970: $0.createdMs / 1000))
                    },
                    bookmarks: chapter.bookmarks.map {
                        Bookmark(id: $0.id, ms: $0.ms, label: $0.label)
                    }
                )
            }
            out[slug] = BookState(chapter: book.chapter, chapters: chapters)
        }
        books = out
        if !payload.categories.isEmpty {
            categories = payload.categories.map { Category(id: $0.id, name: $0.name, tint: $0.color) }
        }
        voice = Voice(rawValue: payload.voice) ?? voice
        rate = Float(payload.speed)
        appearance = Appearance(
            textSize: payload.appearance.size,
            serif: payload.appearance.font != "sans",
            lineSpacing: ["regular": 0, "relaxed": 1, "loose": 2][payload.appearance.space] ?? 0
        )
        lastBook = payload.lastBook
        updatedAt = payload.updatedAt
        saveLocalOnly()
    }
}
