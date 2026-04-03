import SwiftUI

struct SyncStatusBadge: View {
    let state: AppLoadState

    var body: some View {
        Label(title, systemImage: iconName)
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                Capsule(style: .continuous)
                    .fill(backgroundColor)
            )
            .foregroundStyle(foregroundColor)
    }

    private var title: String {
        switch state {
        case .idle:
            return "Waiting"
        case .loading:
            return "Refreshing"
        case .loaded:
            return "Live"
        case .failed:
            return "Offline"
        }
    }

    private var iconName: String {
        switch state {
        case .idle:
            return "clock"
        case .loading:
            return "arrow.triangle.2.circlepath"
        case .loaded:
            return "checkmark.seal.fill"
        case .failed:
            return "wifi.slash"
        }
    }

    private var backgroundColor: Color {
        switch state {
        case .idle:
            return AppTheme.panelSoft
        case .loading:
            return AppTheme.coral.opacity(0.44)
        case .loaded:
            return AppTheme.cobalt.opacity(0.40)
        case .failed:
            return AppTheme.lavender.opacity(0.36)
        }
    }

    private var foregroundColor: Color {
        switch state {
        case .failed:
            return .white
        default:
            return .white
        }
    }
}
