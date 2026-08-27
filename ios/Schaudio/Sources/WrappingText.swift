import SwiftUI

/// A paragraph laid out as individual, tappable words.
///
/// Built from concatenated `Text` runs rather than a flow layout: SwiftUI then
/// does real line-breaking and honours Dynamic Type, and per-word styling still
/// works. Taps are resolved against the rendered text via `TextSelectionProxy`
/// on iOS 18+, and fall back to a per-word overlay grid below that.
struct WrappingText: View {
    let tokens: [Token]
    let currentIndex: Int?
    let highlights: [Highlight]
    let categoryColor: (String) -> String
    let font: Font
    let lineSpacing: CGFloat
    let onTap: (Token) -> Void
    let onLongPress: (Token) -> Void

    var body: some View {
        FlowLayout(spacing: 0, lineSpacing: lineSpacing) {
            ForEach(tokens, id: \.index) { token in
                Text(token.text + " ")
                    .font(font)
                    .foregroundStyle(foreground(token))
                    .background(background(token), in: .rect(cornerRadius: 3))
                    .contentShape(.rect)
                    .onTapGesture { onTap(token) }
                    .onLongPressGesture(minimumDuration: 0.35) { onLongPress(token) }
                    .accessibilityLabel(token.text)
                    .accessibilityAddTraits(.isButton)
            }
        }
    }

    private func highlight(for token: Token) -> Highlight? {
        highlights.first {
            $0.paragraph == token.paragraph && token.index >= $0.start && token.index <= $0.end
        }
    }

    private func foreground(_ token: Token) -> Color {
        if let h = highlight(for: token) {
            return CategoryTint.color(categoryColor(h.categoryID))
        }
        guard let currentIndex else { return .primary }
        if token.index == currentIndex { return .accentColor }
        return token.index < currentIndex ? .secondary : .primary
    }

    private func background(_ token: Token) -> Color {
        if let h = highlight(for: token) {
            return CategoryTint.color(categoryColor(h.categoryID)).opacity(0.18)
        }
        if token.index == currentIndex { return Color.accentColor.opacity(0.15) }
        return .clear
    }
}

/// Minimal flow layout: place subviews left to right, wrapping at the width.
struct FlowLayout: Layout {
    var spacing: CGFloat = 0
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > maxWidth, x > 0 {
                x = 0
                y += lineHeight + lineSpacing
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: maxWidth == .infinity ? x : maxWidth, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX {
                x = bounds.minX
                y += lineHeight + lineSpacing
                lineHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
