import SwiftUI

/// The web app's token layer, ported. `app/app.css` re-bases Flavor DS to the
/// cream-and-leather palette of the book icon in light mode, and keeps Flavor's
/// neutral dark surfaces with a lifted leather accent in dark mode. These are
/// the same hex values — change one side and change the other.
enum Palette {
    // Surfaces
    static let surfacePage = dynamic(light: 0xF6F0E4, dark: 0x101112)
    static let surface1    = dynamic(light: 0xFAF6EE, dark: 0x0A0A0B)
    static let surface2    = dynamic(light: 0xF3ECDF, dark: 0x161719)
    static let surface3    = dynamic(light: 0xEBE1CF, dark: 0x1C1E21)

    // Text
    static let textPrimary   = dynamic(light: 0x33261A, dark: 0xE9EBEE)
    static let textSecondary = dynamic(light: 0x5C4A38, dark: 0xC3C8CD)
    static let textTertiary  = dynamic(light: 0x8D7962, dark: 0xA9AEB5)

    // Borders
    static let borderSubtle  = dynamic(light: 0xE7DCC8, dark: 0x1C1E21)
    static let borderDefault = dynamic(light: 0xD6C8AE, dark: 0x31363C)

    // Accent — leather red-brown, lifted in dark for contrast
    static let accent       = dynamic(light: 0x8B3D2A, dark: 0xB05538)
    static let accentFg     = dynamic(light: 0xFFF8EF, dark: 0xFFF5EC)
    static let accentText   = dynamic(light: 0x7A3322, dark: 0xE89A76)
    static let accentSubtle = dynamic(light: 0xF3E0D6, dark: 0x3A241B)

    private static func dynamic(light: UInt32, dark: UInt32) -> Color {
        Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(rgb: dark) : UIColor(rgb: light) })
    }
}

private extension UIColor {
    convenience init(rgb: UInt32) {
        self.init(red: CGFloat((rgb >> 16) & 0xFF) / 255,
                  green: CGFloat((rgb >> 8) & 0xFF) / 255,
                  blue: CGFloat(rgb & 0xFF) / 255,
                  alpha: 1)
    }
}
