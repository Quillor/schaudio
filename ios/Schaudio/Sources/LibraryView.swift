import SwiftUI

struct LibraryView: View {
    @Environment(Library.self) private var library
    @Environment(Store.self) private var store
    @Environment(Player.self) private var player
    @Environment(SyncService.self) private var sync
    @Environment(Downloads.self) private var downloads

    @State private var opened: Book?
    @State private var showAccount = false

    /// Debug-only: lets an automated run land straight in the reader.
    /// Never compiled into a release build.
    /// Debug-only: open the account sheet, and optionally kick off a download,
    /// so an automated run can verify both. Not compiled into release builds.
    private var autoAccount: Bool {
        #if DEBUG
        ProcessInfo.processInfo.environment["SCHAUDIO_SHOW_ACCOUNT"] == "1"
        #else
        false
        #endif
    }

    private var autoDownloadSlug: String? {
        #if DEBUG
        ProcessInfo.processInfo.environment["SCHAUDIO_TEST_DOWNLOAD"]
        #else
        nil
        #endif
    }

    private var autoOpenSlug: String? {
        #if DEBUG
        ProcessInfo.processInfo.environment["SCHAUDIO_OPEN_BOOK"]
        #else
        nil
        #endif
    }

    private let columns = [GridItem(.adaptive(minimum: 140, maximum: 220), spacing: 20)]

    var body: some View {
        NavigationStack {
            ScrollView {
                if let error = library.loadError, library.books.isEmpty {
                    ContentUnavailableView {
                        Label("Can't reach your library", systemImage: "wifi.exclamationmark")
                    } description: {
                        Text(error)
                    } actions: {
                        Button("Try again") { Task { await library.load() } }
                    }
                    .padding(.top, 60)
                } else if library.books.isEmpty {
                    ProgressView("Loading your library")
                        .padding(.top, 80)
                } else {
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 24) {
                        ForEach(library.books) { book in
                            Button { opened = book } label: { tile(book) }
                                .buttonStyle(.plain)
                                .accessibilityLabel(
                                    "\(book.title) by \(book.author), \(store.startedChapters(book.slug)) of \(book.chapters.count) chapters started"
                                )
                        }
                    }
                    .padding(20)
                }
            }
            .navigationTitle("Book FM")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showAccount = true } label: {
                        if let avatar = sync.account?.avatar {
                            AsyncImage(url: avatar) { $0.resizable().scaledToFill() }
                                placeholder: { Circle().fill(.quaternary) }
                                .frame(width: 28, height: 28)
                                .clipShape(.circle)
                        } else {
                            Image(systemName: "person.crop.circle")
                        }
                    }
                    .accessibilityLabel(sync.account == nil ? "Sign in" : "Account")
                }
            }
            .sheet(isPresented: $showAccount) { AccountView() }
            .background(Color(.systemGroupedBackground))
            .fullScreenCover(item: $opened) { book in
                ReaderView(book: book)
            }
            .onChange(of: library.books.count) { _, _ in
                if opened == nil, let slug = autoOpenSlug,
                   let book = library.books.first(where: { $0.slug == slug }) {
                    opened = book
                }
                if autoAccount { showAccount = true }
                if let slug = autoDownloadSlug,
                   let book = library.books.first(where: { $0.slug == slug }) {
                    downloads.download(book: book, voice: store.voice, library: library)
                }
            }
        }
    }

    @ViewBuilder
    private func tile(_ book: Book) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack(alignment: .bottom) {
                Color.clear
                AsyncImage(url: library.coverURL(slug: book.slug)) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFill()
                    default:
                        Rectangle().fill(.quaternary)
                    }
                }
                .clipped()
                let started = store.startedChapters(book.slug)
                if started > 0 {
                    GeometryReader { geo in
                        Rectangle()
                            .fill(Color.accentColor)
                            .frame(width: geo.size.width * CGFloat(started) / CGFloat(book.chapters.count),
                                   height: 4)
                            .frame(maxHeight: .infinity, alignment: .bottom)
                    }
                }
            }
            .aspectRatio(39.0/50.0, contentMode: .fit)
            .frame(maxWidth: .infinity)
            .clipShape(.rect(cornerRadius: 10))
            .shadow(color: .black.opacity(0.15), radius: 4, y: 2)

            Text(book.title)
                .font(.subheadline.weight(.semibold))
                .lineLimit(2)
            HStack(spacing: 4) {
                if case .complete = downloads.state(book.slug) {
                    Image(systemName: "arrow.down.circle.fill")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("Downloaded")
                }
                Text("\(book.author) · \(book.chapters.count) chapters")
            }
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
    }
}
