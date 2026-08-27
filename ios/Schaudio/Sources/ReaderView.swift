import SwiftUI

struct ReaderView: View {
    let book: Book

    @Environment(Library.self) private var library
    @Environment(Store.self) private var store
    @Environment(Player.self) private var player
    @Environment(Downloads.self) private var downloads
    @Environment(\.dismiss) private var dismiss

    @State private var chapter: Chapter?
    @State private var loading = true
    @State private var missingAudio = false
    @State private var followPlayback = true
    @State private var lastUserScroll = Date.distantPast
    @State private var sheet: ReaderSheet?
    @State private var selection: TokenRange?

    var body: some View {
        NavigationStack {
            Group {
                if loading {
                    ProgressView("Loading chapter").frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    readerBody
                }
            }
            .navigationTitle(chapter?.title ?? book.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        player.stop()
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                    }
                    .accessibilityLabel("Close book")
                }
            }
            .safeAreaInset(edge: .bottom) { PlayerBar(sheet: $sheet) }
        }
        .task { await open(chapterNumber: store.bookState(book.slug).chapter) }
        .onDisappear { player.stop() }
        .sheet(item: $sheet) { which in
            switch which {
            case .chapters:
                ChaptersSheet(book: book) { n in Task { await open(chapterNumber: n, autoplay: true) } }
            case .notes:
                NotesSheet(book: book, chapter: chapter?.n ?? 1)
            case .voice:
                VoiceSheet(book: book, chapter: chapter?.n ?? 1) { await reloadForVoiceChange() }
            case .text:
                TextSheet()
            }
        }
        .sheet(item: $selection) { range in
            HighlightSheet(book: book, chapter: chapter?.n ?? 1, range: range) { selection = nil }
        }
    }

    // MARK: - Body

    private var readerBody: some View {
        ScrollViewReader { proxy in
            ScrollView {
                if missingAudio {
                    Label("Narration for this chapter isn't available yet — the text is still readable.",
                          systemImage: "waveform.slash")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                LazyVStack(alignment: .leading, spacing: 20) {
                    ForEach(paragraphIndices, id: \.self) { p in
                        paragraphView(p)
                            .id(p)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 200)
            }
            .simultaneousGesture(DragGesture().onChanged { _ in lastUserScroll = .now })
            .onChange(of: player.currentTokenIndex) { _, new in
                guard followPlayback, player.isPlaying,
                      Date.now.timeIntervalSince(lastUserScroll) > 2,
                      let i = new, i < player.tokens.count else { return }
                withAnimation(.easeInOut(duration: 0.35)) {
                    proxy.scrollTo(player.tokens[i].paragraph, anchor: .center)
                }
            }
        }
    }

    private var paragraphIndices: [Int] {
        guard let chapter else { return [] }
        return Array(chapter.paragraphs.indices)
    }

    /// One paragraph, rendered as a run of words so the spoken one can be lit
    /// and any word can be tapped to seek.
    @ViewBuilder
    private func paragraphView(_ p: Int) -> some View {
        let tokens = player.tokens.filter { $0.paragraph == p }
        if tokens.isEmpty, let chapter, p < chapter.paragraphs.count {
            Text(chapter.paragraphs[p]).font(bodyFont).lineSpacing(lineSpacing)
        } else {
            WrappingText(
                tokens: tokens,
                currentIndex: player.currentTokenIndex,
                highlights: store.chapterState(book.slug, chapter?.n ?? 1).highlights,
                categoryColor: { store.category($0).tint },
                font: bodyFont,
                lineSpacing: lineSpacing,
                onTap: { token in
                    lastUserScroll = .distantPast
                    player.seek(toToken: token)
                },
                onLongPress: { token in
                    selection = TokenRange(paragraph: token.paragraph,
                                           start: token.index, end: token.index)
                }
            )
        }
    }

    private var bodyFont: Font {
        let a = store.appearance
        let base: Font = a.serif ? .system(.body, design: .serif) : .system(.body)
        // Dynamic Type still drives the base size; this only shifts it.
        switch a.textSize {
        case 0: return base.smallCaps().leading(.tight)
        case ...1: return .system(a.serif ? .callout : .callout, design: a.serif ? .serif : .default)
        case 3: return .system(a.serif ? .title3 : .title3, design: a.serif ? .serif : .default)
        case 4...: return .system(a.serif ? .title2 : .title2, design: a.serif ? .serif : .default)
        default: return base
        }
    }

    private var lineSpacing: CGFloat {
        switch store.appearance.lineSpacing {
        case 1: 10
        case 2: 16
        default: 6
        }
    }

    // MARK: - Loading

    private var debugAutoplay: Bool {
        #if DEBUG
        ProcessInfo.processInfo.environment["SCHAUDIO_AUTOPLAY"] == "1"
        #else
        false
        #endif
    }

    private func open(chapterNumber: Int, autoplay: Bool = false) async {
        loading = true
        missingAudio = false
        let target = book.chapters.first { $0.n == chapterNumber } ?? book.chapters[0]
        chapter = target
        store.setChapter(book.slug, target.n)

        var manifest = await library.manifest(slug: book.slug, voice: store.voice, chapter: target.n)
        if manifest == nil {
            for v in Voice.allCases where v != store.voice {
                if let fallback = await library.manifest(slug: book.slug, voice: v, chapter: target.n) {
                    manifest = fallback
                    break
                }
            }
        }

        if let manifest {
            let resume = store.chapterState(book.slug, target.n).positionMs
            player.load(book: book, chapter: target, manifest: manifest, library: library,
                        downloads: downloads, startAtMs: resume,
                        autoplay: autoplay || debugAutoplay)
            player.onChapterEnd = {
                Task { await advanceChapter(after: target.n) }
            }
        } else {
            missingAudio = true
            player.stop()
        }
        loading = false
    }

    private func advanceChapter(after n: Int) async {
        guard let idx = book.chapters.firstIndex(where: { $0.n == n }),
              idx + 1 < book.chapters.count else { return }
        await open(chapterNumber: book.chapters[idx + 1].n, autoplay: true)
    }

    private func reloadForVoiceChange() async {
        guard let chapter else { return }
        let fraction = player.totalMs > 0 ? Double(player.positionMs) / Double(player.totalMs) : 0
        if let manifest = await library.manifest(slug: book.slug, voice: store.voice, chapter: chapter.n) {
            player.load(book: book, chapter: chapter, manifest: manifest, library: library,
                        downloads: downloads,
                        startAtMs: Int(fraction * Double(manifest.totalMs)),
                        autoplay: player.isPlaying)
        }
    }
}

enum ReaderSheet: String, Identifiable {
    case chapters, notes, voice, text
    var id: String { rawValue }
}

struct TokenRange: Identifiable {
    var id = UUID()
    let paragraph: Int
    let start: Int
    let end: Int
}
