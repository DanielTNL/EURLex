import SwiftUI

enum AppTheme {
    static let midnight = Color(red: 0.05, green: 0.07, blue: 0.14)
    static let twilight = Color(red: 0.09, green: 0.10, blue: 0.22)
    static let nebula = Color(red: 0.14, green: 0.09, blue: 0.28)

    static let ink = Color(red: 0.94, green: 0.97, blue: 1.00)
    static let slate = Color(red: 0.76, green: 0.81, blue: 0.91)

    static let cobalt = Color(red: 0.18, green: 0.53, blue: 0.99)
    static let mint = Color(red: 0.34, green: 0.77, blue: 1.00)
    static let coral = Color(red: 0.37, green: 0.39, blue: 0.97)
    static let amber = Color(red: 0.52, green: 0.52, blue: 1.00)
    static let lavender = Color(red: 0.72, green: 0.49, blue: 1.00)
    static let plum = Color(red: 0.25, green: 0.21, blue: 0.52)
    static let plumSoft = Color(red: 0.39, green: 0.35, blue: 0.66)
    static let pageTitle = Color(red: 0.16, green: 0.13, blue: 0.36)
    static let pageBody = Color(red: 0.22, green: 0.20, blue: 0.46)
    static let pageSubtext = Color(red: 0.31, green: 0.30, blue: 0.56)
    static let heroText = Color(red: 0.95, green: 0.97, blue: 1.00)
    static let heroSubtext = Color(red: 0.80, green: 0.85, blue: 0.95)

    static let accentPalette: [Color] = [cobalt, coral, amber, lavender, mint]
    static let panel = Color(red: 0.10, green: 0.12, blue: 0.22).opacity(0.72)
    static let panelStrong = Color(red: 0.08, green: 0.10, blue: 0.20).opacity(0.84)
    static let panelSoft = Color(red: 0.12, green: 0.15, blue: 0.27).opacity(0.54)
    static let border = Color.white.opacity(0.14)
    static let shadow = Color.black.opacity(0.34)
    static let softShadow = Color.black.opacity(0.18)
    static let floatingDockReservedHeight: CGFloat = 118
    static let screenBottomClearance: CGFloat = 152
    static let composerBottomLift: CGFloat = 96

    static let background = LinearGradient(
        colors: [midnight, twilight, nebula],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static func accent(for seed: String) -> Color {
        let value = seed.unicodeScalars.reduce(0) { $0 + Int($1.value) }
        return accentPalette[value % accentPalette.count]
    }
}

struct AmbientBackground: View {
    var body: some View {
        GeometryReader { proxy in
            ZStack {
                AppTheme.background
                    .ignoresSafeArea()

                Circle()
                    .fill(AppTheme.cobalt.opacity(0.30))
                    .frame(width: proxy.size.width * 0.88)
                    .blur(radius: 68)
                    .offset(x: -proxy.size.width * 0.22, y: -proxy.size.height * 0.26)

                Circle()
                    .fill(AppTheme.lavender.opacity(0.26))
                    .frame(width: proxy.size.width * 0.78)
                    .blur(radius: 82)
                    .offset(x: proxy.size.width * 0.34, y: -proxy.size.height * 0.12)

                Circle()
                    .fill(AppTheme.mint.opacity(0.16))
                    .frame(width: proxy.size.width * 0.58)
                    .blur(radius: 72)
                    .offset(x: proxy.size.width * 0.18, y: proxy.size.height * 0.32)

                AngularGradient(
                    colors: [AppTheme.cobalt.opacity(0.14), AppTheme.lavender.opacity(0.06), .clear],
                    center: .topTrailing
                )
                .ignoresSafeArea()
            }
        }
    }
}

struct GlassCardModifier: ViewModifier {
    let cornerRadius: CGFloat
    let tint: Color
    let padding: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(AppTheme.panelStrong)
                    .overlay {
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .fill(.ultraThinMaterial)
                            .opacity(0.72)
                    }
                    .overlay {
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [Color.white.opacity(0.12), tint.opacity(0.14), Color.clear],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    }
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(AppTheme.border, lineWidth: 1)
            )
            .shadow(color: AppTheme.shadow, radius: 26, x: 0, y: 18)
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = 30, tint: Color = .white, padding: CGFloat = 18) -> some View {
        modifier(GlassCardModifier(cornerRadius: cornerRadius, tint: tint, padding: padding))
    }

    func dossierCard() -> some View {
        glassCard(cornerRadius: 28, tint: AppTheme.cobalt)
    }
}

struct PrimaryCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline.weight(.semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .foregroundStyle(.white)
            .background(
                Capsule(style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [AppTheme.cobalt, AppTheme.lavender],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
            )
            .shadow(color: AppTheme.cobalt.opacity(0.28), radius: 14, x: 0, y: 10)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.spring(response: 0.24, dampingFraction: 0.8), value: configuration.isPressed)
    }
}

struct SecondaryCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline.weight(.semibold))
            .padding(.horizontal, 18)
            .padding(.vertical, 12)
            .foregroundStyle(AppTheme.ink)
            .background(
                Capsule(style: .continuous)
                    .fill(AppTheme.panelSoft)
                    .overlay {
                        Capsule(style: .continuous)
                            .fill(.ultraThinMaterial)
                            .opacity(0.40)
                    }
            )
            .overlay(
                Capsule(style: .continuous)
                    .strokeBorder(AppTheme.border, lineWidth: 1)
            )
            .shadow(color: AppTheme.softShadow, radius: 10, x: 0, y: 6)
            .opacity(configuration.isPressed ? 0.88 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.spring(response: 0.24, dampingFraction: 0.8), value: configuration.isPressed)
    }
}
