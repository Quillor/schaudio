import Foundation

/// Wire format shared with the web app. Any change here must match the JSON
/// emitted by tools/ingest.py and tools/narrate.py.

struct Book: Codable, Identifiable, Sendable, Hashable {
    let slug: String
    let title: String
    let subtitle: String
    let author: String
    let chapters: [Chapter]

    var id: String { slug }
}

struct Chapter: Codable, Identifiable, Sendable, Hashable {
    let n: Int
    let title: String
    let paragraphs: [String]

    var id: Int { n }
}

struct Manifest: Codable, Sendable {
    let chapter: Int
    let voice: String
    let totalMs: Int
    let paragraphs: [ManifestParagraph]
}

struct ManifestParagraph: Codable, Sendable {
    let id: Int
    let audio: String
    let startMs: Int
    let durationMs: Int
    let words: [WordTiming]
}

struct WordTiming: Codable, Sendable {
    let text: String
    let startMs: Int
    let endMs: Int
}

/// One displayed token with the audio span it belongs to. Built once per
/// chapter by aligning the book's own text (punctuation intact) against the
/// synthesizer's word boundaries, which split on punctuation too.
struct Token: Sendable, Hashable {
    let text: String
    let paragraph: Int
    let index: Int
    /// Milliseconds from the start of the chapter.
    let startMs: Int
    let endMs: Int
}

enum Voice: String, CaseIterable, Identifiable, Sendable {
    case sam, morgan

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .sam: "Sam"
        case .morgan: "Morgan"
        }
    }

    var blurb: String {
        switch self {
        case .sam: "Warm, clear and engaging — the house narrator"
        case .morgan: "Deep, slow and relaxing, with an unhurried cadence"
        }
    }
}

/// Aligns display tokens to measured word timings.
enum TokenBuilder {
    static func build(chapter: Chapter, manifest: Manifest) -> [Token] {
        var tokens: [Token] = []
        for (pIndex, text) in chapter.paragraphs.enumerated() {
            guard pIndex < manifest.paragraphs.count else { break }
            let mp = manifest.paragraphs[pIndex]
            let offset = mp.startMs
            let words = mp.words
            var j = 0
            var lastEnd = offset

            for raw in text.split(separator: " ", omittingEmptySubsequences: true) {
                let target = normalize(String(raw))
                var start: Int?
                var end: Int?

                if !target.isEmpty, j < words.count {
                    var acc = ""
                    var k = j
                    while k < words.count, acc.count < target.count {
                        acc += normalize(words[k].text)
                        k += 1
                        if acc == target { break }
                    }
                    if acc == target {
                        start = offset + words[j].startMs
                        end = offset + words[k - 1].endMs
                        j = k
                    } else if normalize(words[j].text).hasPrefix(target) || target.hasPrefix(normalize(words[j].text)) {
                        start = offset + words[j].startMs
                        end = offset + words[j].endMs
                        j += 1
                    }
                }

                let s = start ?? lastEnd
                let e = end ?? s
                lastEnd = e
                tokens.append(Token(text: String(raw), paragraph: pIndex,
                                    index: tokens.count, startMs: s, endMs: e))
            }
        }
        return tokens
    }

    private static func normalize(_ s: String) -> String {
        s.lowercased().unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
            .reduce(into: "") { $0.unicodeScalars.append($1) }
    }
}
