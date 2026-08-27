import SwiftUI

/// Sign-in state and per-book offline storage, in one place.
struct AccountView: View {
    @Environment(SyncService.self) private var sync
    @Environment(Library.self) private var library
    @Environment(Store.self) private var store
    @Environment(Downloads.self) private var downloads
    @Environment(\.dismiss) private var dismiss

    @State private var busy = false
    @State private var failure: String?

    var body: some View {
        NavigationStack {
            List {
                accountSection
                offlineSection
            }
            .navigationTitle("Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
            .alert("Sign-in failed", isPresented: .constant(failure != nil)) {
                Button("OK") { failure = nil }
            } message: {
                Text(failure ?? "")
            }
        }
    }

    // MARK: - Account

    @ViewBuilder
    private var accountSection: some View {
        Section {
            if let account = sync.account {
                HStack(spacing: 12) {
                    AsyncImage(url: account.avatar) { image in
                        image.resizable().scaledToFill()
                    } placeholder: {
                        Circle().fill(.quaternary)
                    }
                    .frame(width: 44, height: 44)
                    .clipShape(.circle)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(account.name).font(.headline)
                        Text(account.email).font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)

                Label(syncLabel, systemImage: syncSymbol)
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                Button("Sync now") { Task { await sync.pull() } }
                Button("Sign out", role: .destructive) { sync.signOut() }
            } else {
                Button {
                    Task { await signIn() }
                } label: {
                    HStack {
                        Image(systemName: "person.crop.circle.badge.checkmark")
                        Text(busy ? "Signing in…" : "Sign in with Google")
                        if busy { Spacer(); ProgressView() }
                    }
                }
                .disabled(busy)

                Text("Signing in syncs your progress, highlights, notes and bookmarks with the Schaudio website and your other devices.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        } header: {
            Text("Account")
        }
    }

    private var syncLabel: String {
        switch sync.status {
        case .syncing: "Syncing…"
        case .error(let message): message
        default: "Synced with your other devices"
        }
    }

    private var syncSymbol: String {
        switch sync.status {
        case .syncing: "arrow.triangle.2.circlepath"
        case .error: "exclamationmark.triangle"
        default: "checkmark.icloud"
        }
    }

    private func signIn() async {
        busy = true
        defer { busy = false }
        do {
            let result = try await GoogleSignIn.run(from: PresentationAnchor.current)
            await sync.signIn(idToken: result.idToken, nonce: result.nonce)
            if case .error(let message) = sync.status { failure = message }
        } catch let error as GoogleSignIn.Failure {
            if case .cancelled = error { return }   // user backed out; not an error
            failure = error.errorDescription
        } catch {
            failure = error.localizedDescription
        }
    }

    // MARK: - Offline

    private var offlineSection: some View {
        Section {
            ForEach(library.books) { book in
                offlineRow(book)
            }
        } header: {
            Text("Offline")
        } footer: {
            Text("Downloaded books play with no connection, in the voice selected when you downloaded them.")
        }
    }

    @ViewBuilder
    private func offlineRow(_ book: Book) -> some View {
        let state = downloads.state(book.slug)
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(book.title).font(.subheadline).lineLimit(1)
                switch state {
                case .none:
                    Text("\(book.chapters.count) chapters · not downloaded")
                        .font(.caption).foregroundStyle(.secondary)
                case .downloading(let done, let total):
                    Text("Downloading \(done) of \(total)…")
                        .font(.caption).foregroundStyle(.secondary)
                case .complete(let bytes):
                    Text("Available offline · \(Downloads.formatted(bytes))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            switch state {
            case .none:
                Button {
                    downloads.download(book: book, voice: store.voice, library: library)
                } label: {
                    Image(systemName: "arrow.down.circle")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Download \(book.title)")
            case .downloading:
                Button {
                    downloads.cancel(book.slug)
                    downloads.refresh(book)
                } label: {
                    ProgressView(value: state.fraction).progressViewStyle(.circular)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Cancel download")
            case .complete:
                Button(role: .destructive) {
                    downloads.remove(book)
                } label: {
                    Image(systemName: "trash")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel("Remove download of \(book.title)")
            }
        }
        .task { downloads.refresh(book) }
    }
}
