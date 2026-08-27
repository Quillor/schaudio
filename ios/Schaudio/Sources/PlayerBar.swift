import SwiftUI

struct PlayerBar: View {
    @Binding var sheet: ReaderSheet?

    @Environment(Player.self) private var player
    @Environment(Store.self) private var store

    @State private var scrubbing = false
    @State private var scrubValue: Double = 0

    private static let rates: [Float] = [0.8, 1.0, 1.25, 1.5, 2.0]

    var body: some View {
        VStack(spacing: 10) {
            scrubber
            transport
            menuRow
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 6)
        .background(.bar)
    }

    private var scrubber: some View {
        VStack(spacing: 2) {
            Slider(
                value: Binding(
                    get: { scrubbing ? scrubValue : Double(player.positionMs) },
                    set: { scrubValue = $0 }
                ),
                in: 0...Double(max(player.totalMs, 1)),
                onEditingChanged: { editing in
                    scrubbing = editing
                    if !editing { player.seek(toMs: Int(scrubValue)) }
                }
            )
            .disabled(player.totalMs == 0)
            .accessibilityLabel("Playback position")

            HStack {
                Text(Self.time(scrubbing ? Int(scrubValue) : player.positionMs))
                Spacer()
                Text("−" + Self.time(max(0, player.totalMs - (scrubbing ? Int(scrubValue) : player.positionMs))))
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.secondary)
        }
    }

    private var transport: some View {
        HStack(spacing: 28) {
            Button {
                let next = Self.rates.firstIndex(of: store.rate).map { (($0 + 1) % Self.rates.count) } ?? 1
                store.rate = Self.rates[next]
                player.rate = store.rate
                store.save()
            } label: {
                Text(Self.rateLabel(store.rate))
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .frame(minWidth: 48)
            }
            .accessibilityLabel("Playback speed \(Self.rateLabel(store.rate))")

            Button { player.skip(seconds: -15) } label: {
                Image(systemName: "gobackward.15").font(.title2)
            }
            .accessibilityLabel("Back 15 seconds")

            Button { player.toggle() } label: {
                Image(systemName: player.isPlaying ? "pause.circle.fill" : "play.circle.fill")
                    .font(.system(size: 56))   // primary control: sized for a thumb, not for text
                    .symbolRenderingMode(.hierarchical)
            }
            .disabled(player.totalMs == 0)
            .accessibilityLabel(player.isPlaying ? "Pause" : "Play")

            Button { player.skip(seconds: 15) } label: {
                Image(systemName: "goforward.15").font(.title2)
            }
            .accessibilityLabel("Forward 15 seconds")

            Button { addBookmark() } label: {
                Image(systemName: "bookmark").font(.title3)
            }
            .accessibilityLabel("Add bookmark")
        }
        .buttonStyle(.plain)
    }

    private var menuRow: some View {
        HStack {
            item("textformat", "Text") { sheet = .text }
            item("mic", "Voice") { sheet = .voice }
            item("list.bullet", "Chapters") { sheet = .chapters }
            item("doc.text", "Notes") { sheet = .notes }
        }
    }

    private func item(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 2) {
                Image(systemName: symbol).font(.body)
                Text(label).font(.caption2)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private func addBookmark() {
        guard let i = player.currentTokenIndex, i < player.tokens.count else { return }
        let words = player.tokens[i...].prefix(4).map(\.text).joined(separator: " ")
        // The reader owns book/chapter identity; the bar only knows the player,
        // so the label is derived here and stored by the enclosing view's state.
        NotificationCenter.default.post(
            name: .schaudioAddBookmark,
            object: nil,
            userInfo: ["ms": player.positionMs, "label": words + "…"]
        )
    }

    static func time(_ ms: Int) -> String {
        let s = max(0, ms / 1000)
        let h = s / 3600, m = (s % 3600) / 60, sec = s % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    static func rateLabel(_ r: Float) -> String {
        r == floor(r) ? String(format: "%.1f×", r) : String(format: "%.2f×", r)
    }
}

extension Notification.Name {
    static let schaudioAddBookmark = Notification.Name("schaudio.addBookmark")
}
