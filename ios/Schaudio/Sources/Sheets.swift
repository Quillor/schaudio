import SwiftUI

// MARK: - Chapters

struct ChaptersSheet: View {
    let book: Book
    let onPick: (Int) -> Void

    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss

    private var narratedCount: Int { book.chapters.filter { !$0.isBibliography }.count }
    private var startedCount: Int {
        book.chapters.filter { !$0.isBibliography && store.chapterState(book.slug, $0.n).positionMs > 1000 }.count
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(book.chapters) { chapter in
                        row(chapter)
                            // Full-bleed: the current row's tint reaches the
                            // sheet's edges instead of floating inside a gutter.
                            .listRowInsets(EdgeInsets())
                            .listRowBackground(background(chapter))
                            .listRowSeparatorTint(Palette.borderSubtle)
                    }
                } header: {
                    Text("Chapter \(store.bookState(book.slug).chapter) of \(narratedCount) · \(startedCount) started")
                        .font(.caption.weight(.semibold))
                        .kerning(0.6)
                        .textCase(.uppercase)
                        .foregroundStyle(Palette.textTertiary)
                }
            }
            .listStyle(.plain)
            .background(Palette.surface1)
            .navigationTitle("Chapters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }

    @ViewBuilder
    private func row(_ chapter: Chapter) -> some View {
        let state = progress(chapter)
        Button {
            onPick(chapter.n)
            dismiss()
        } label: {
            HStack(spacing: 12) {
                // Accent rail on the chapter you're on.
                Rectangle()
                    .fill(isCurrent(chapter) ? Palette.accent : .clear)
                    .frame(width: 3)

                numberColumn(chapter)

                VStack(alignment: .leading, spacing: 2) {
                    Text(chapter.title)
                        .font(.subheadline.weight(isCurrent(chapter) ? .semibold : .medium))
                        .foregroundStyle(isCurrent(chapter) ? Palette.accentText
                                         : chapter.isBibliography ? Palette.textTertiary : Palette.textPrimary)
                        .multilineTextAlignment(.leading)
                    Text(subtitle(chapter))
                        .font(.caption)
                        .foregroundStyle(Palette.textTertiary)
                    if state.fraction > 0, state.fraction < 0.98, !isCurrent(chapter) {
                        progressBar(state.fraction)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                // The glyph is an affordance, not the focal point: quiet on
                // idle rows, accented only on the one that's playing.
                Image(systemName: chapter.isBibliography ? "book"
                                  : isCurrent(chapter) ? "speaker.wave.2.fill" : "play.fill")
                    .font(.footnote)
                    .foregroundStyle(isCurrent(chapter) ? Palette.accent : Palette.textTertiary)
            }
            .padding(.trailing, 20)
            .padding(.vertical, 10)
            .frame(minHeight: 52)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .disabled(chapter.isBibliography)
        .accessibilityLabel("Chapter \(chapter.displayLabel), \(chapter.title), \(accessibilityStatus(chapter))")
    }

    @ViewBuilder
    private func numberColumn(_ chapter: Chapter) -> some View {
        let finished = progress(chapter).fraction >= 0.98
        Group {
            if finished, !isCurrent(chapter) {
                Image(systemName: "checkmark").font(.footnote.weight(.semibold))
            } else {
                Text(chapter.displayLabel)
                    .font(.footnote.monospacedDigit())
                    .fontWeight(isCurrent(chapter) ? .bold : .regular)
            }
        }
        .foregroundStyle(isCurrent(chapter) ? Palette.accentText : Palette.textTertiary)
        .frame(width: 30, alignment: .trailing)
    }

    private func progressBar(_ fraction: Double) -> some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Palette.borderDefault)
                Capsule().fill(Palette.accent).frame(width: geo.size.width * fraction)
            }
        }
        .frame(height: 3)
        .frame(maxWidth: 220)
        .padding(.top, 4)
    }

    private func background(_ chapter: Chapter) -> some View {
        (isCurrent(chapter) ? Palette.accentSubtle : Palette.surface1)
    }

    private func isCurrent(_ chapter: Chapter) -> Bool {
        store.bookState(book.slug).chapter == chapter.n
    }

    /// How far through the chapter the reader is. Duration is only known once a
    /// manifest has been fetched, so fall back to the word-count estimate — the
    /// same fallback the web app uses, so both surfaces agree.
    private func progress(_ chapter: Chapter) -> (positionMs: Int, fraction: Double) {
        let pos = store.chapterState(book.slug, chapter.n).positionMs
        let est = chapter.estimatedMs
        guard est > 0 else { return (pos, 0) }
        return (pos, min(1, Double(pos) / Double(est)))
    }

    private func subtitle(_ chapter: Chapter) -> String {
        if chapter.isBibliography { return "Text only — references" }
        let (pos, fraction) = progress(chapter)
        let duration = chapter.estimatedMs > 0 ? PlayerBar.time(chapter.estimatedMs) : ""
        // The speaker glyph already marks the playing row; a "Now playing"
        // badge next to it was saying the same thing twice.
        let status: String
        if isCurrent(chapter) { status = "" }
        else if fraction >= 0.98 { status = "Finished" }
        else if pos > 1000 {
            status = "\(Int(fraction * 100))% · \(PlayerBar.time(max(0, chapter.estimatedMs - pos))) left"
        } else { status = "Not started" }
        return [status, duration].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func accessibilityStatus(_ chapter: Chapter) -> String {
        if chapter.isBibliography { return "text only, references" }
        if isCurrent(chapter) { return "now playing" }
        let (pos, fraction) = progress(chapter)
        if fraction >= 0.98 { return "finished" }
        return pos > 1000 ? "\(Int(fraction * 100)) percent listened" : "not started"
    }
}

// MARK: - Voice

struct VoiceSheet: View {
    let book: Book
    let chapter: Int
    let onChange: () async -> Void

    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(Voice.allCases) { voice in
                Button {
                    store.voice = voice
                    store.save()
                    Task { await onChange(); dismiss() }
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(voice.displayName).font(.headline)
                            Text(voice.blurb).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if store.voice == voice {
                            Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
            .navigationTitle("Voice")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }
}

// MARK: - Text settings

struct TextSheet: View {
    @Environment(Store.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var store = store
        NavigationStack {
            Form {
                Section("Size") {
                    Stepper(value: $store.appearance.textSize, in: 0...6) {
                        Text("Text size \(store.appearance.textSize + 1) of 7")
                    }
                    .onChange(of: store.appearance.textSize) { _, _ in store.save() }
                }
                Section("Style") {
                    Picker("Font", selection: $store.appearance.serif) {
                        Text("Serif").tag(true)
                        Text("Sans").tag(false)
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: store.appearance.serif) { _, _ in store.save() }

                    Picker("Spacing", selection: $store.appearance.lineSpacing) {
                        Text("Regular").tag(0)
                        Text("Relaxed").tag(1)
                        Text("Loose").tag(2)
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: store.appearance.lineSpacing) { _, _ in store.save() }
                }
                Section {
                    Text("Sizes follow your system text size setting as well.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Text")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }
}

// MARK: - Notes & bookmarks

struct NotesSheet: View {
    let book: Book
    let chapter: Int

    @Environment(Store.self) private var store
    @Environment(Player.self) private var player
    @Environment(\.dismiss) private var dismiss
    @State private var tab = 0

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("", selection: $tab) {
                    Text("Notes").tag(0)
                    Text("Bookmarks").tag(1)
                }
                .pickerStyle(.segmented)
                .padding()

                if tab == 0 { notesList } else { bookmarksList }
            }
            .navigationTitle("Notes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }

    private var notesList: some View {
        let items = store.chapterState(book.slug, chapter).highlights
            .sorted { ($0.paragraph, $0.start) < ($1.paragraph, $1.start) }
        return Group {
            if items.isEmpty {
                ContentUnavailableView("No highlights yet",
                                       systemImage: "highlighter",
                                       description: Text("Press and hold any word while you listen to highlight it."))
            } else {
                List {
                    ForEach(items) { h in
                        VStack(alignment: .leading, spacing: 6) {
                            Text("“\(h.quote)”").font(.callout)
                            if !h.note.isEmpty {
                                Text(h.note).font(.footnote).foregroundStyle(.secondary)
                            }
                            Label(store.category(h.categoryID).name, systemImage: "tag")
                                .font(.caption2)
                                .foregroundStyle(CategoryTint.color(store.category(h.categoryID).tint))
                        }
                        .padding(.vertical, 2)
                    }
                    .onDelete { offsets in
                        let ids = offsets.map { items[$0].id }
                        store.update(book.slug, chapter) { state in
                            state.highlights.removeAll { ids.contains($0.id) }
                        }
                    }
                }
            }
        }
    }

    private var bookmarksList: some View {
        let items = store.chapterState(book.slug, chapter).bookmarks.sorted { $0.ms < $1.ms }
        return Group {
            if items.isEmpty {
                ContentUnavailableView("No bookmarks",
                                       systemImage: "bookmark",
                                       description: Text("Tap the bookmark button in the player to pin a moment."))
            } else {
                List {
                    ForEach(items) { b in
                        Button {
                            player.seek(toMs: b.ms)
                            dismiss()
                        } label: {
                            HStack {
                                Image(systemName: "bookmark.fill").foregroundStyle(Color.accentColor)
                                Text(b.label).lineLimit(1)
                                Spacer()
                                Text(PlayerBar.time(b.ms))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                    .onDelete { offsets in
                        let ids = offsets.map { items[$0].id }
                        store.update(book.slug, chapter) { state in
                            state.bookmarks.removeAll { ids.contains($0.id) }
                        }
                    }
                }
            }
        }
    }
}

// MARK: - Creating a highlight

struct HighlightSheet: View {
    let book: Book
    let chapter: Int
    let range: TokenRange
    let onDone: () -> Void

    @Environment(Store.self) private var store
    @Environment(Player.self) private var player
    @Environment(\.dismiss) private var dismiss

    @State private var categoryID: String = Category.defaults[0].id
    @State private var note: String = ""
    @State private var extra: Int = 0     // words to extend the selection by

    var body: some View {
        NavigationStack {
            Form {
                Section("Passage") {
                    Text("“\(quote)”").font(.callout)
                    Stepper("Include \(extra + 1) word\(extra == 0 ? "" : "s")", value: $extra, in: 0...60)
                }
                Section("Category") {
                    Picker("Category", selection: $categoryID) {
                        ForEach(store.categories) { c in Text(c.name).tag(c.id) }
                    }
                    .pickerStyle(.inline)
                    .labelsHidden()
                }
                Section("Note") {
                    TextField("Optional note", text: $note, axis: .vertical).lineLimit(2...5)
                }
            }
            .navigationTitle("Highlight")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss(); onDone() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") { save() }.bold()
                }
            }
        }
    }

    private var endIndex: Int { range.end + extra }

    private var quote: String {
        player.tokens
            .filter { $0.index >= range.start && $0.index <= endIndex && $0.paragraph == range.paragraph }
            .map(\.text)
            .joined(separator: " ")
    }

    private func save() {
        store.update(book.slug, chapter) { state in
            state.highlights.append(
                Highlight(paragraph: range.paragraph, start: range.start, end: endIndex,
                          categoryID: categoryID, note: note, quote: quote)
            )
        }
        dismiss()
        onDone()
    }
}
