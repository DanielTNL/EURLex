import SwiftUI

enum AppTab: String, CaseIterable, Identifiable {
    case briefing
    case feed
    case askAI
    case sources
    case library

    var id: String { rawValue }

    var title: String {
        switch self {
        case .briefing:
            return "Briefing"
        case .feed:
            return "Feed"
        case .askAI:
            return "Ask AI"
        case .sources:
            return "Sources"
        case .library:
            return "Library"
        }
    }

    var systemImage: String {
        switch self {
        case .briefing:
            return "sun.max"
        case .feed:
            return "newspaper"
        case .askAI:
            return "sparkles"
        case .sources:
            return "dot.radiowaves.left.and.right"
        case .library:
            return "books.vertical"
        }
    }

    var accent: Color {
        switch self {
        case .briefing:
            return AppTheme.amber
        case .feed:
            return AppTheme.cobalt
        case .askAI:
            return AppTheme.mint
        case .sources:
            return AppTheme.coral
        case .library:
            return AppTheme.lavender
        }
    }
}

struct AppView: View {
    @StateObject private var model = AppModel()
    @State private var selectedTab: AppTab = .briefing

    var body: some View {
        ZStack {
            AmbientBackground()

            switch loadPresentation {
            case .loading:
                ProgressView("Loading EURLex")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .tint(.white)
            case .error(let message):
                VStack(spacing: 16) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.system(size: 42))
                        .foregroundStyle(AppTheme.ink)
                    Text("Could not reach the published feeds")
                        .font(.title2.weight(.semibold))
                        .fontDesign(.serif)
                    Text(message)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(AppTheme.slate)
                    Button("Retry") {
                        Task { await model.reload() }
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())
                }
                .padding(24)
                .glassCard(cornerRadius: 32, tint: AppTheme.coral)
                .padding(24)
            case .tabs:
                tabShell
            }
        }
        .tint(AppTheme.cobalt)
        .task {
            if model.shouldLoad {
                await model.reload()
            }
        }
    }

    private var tabShell: some View {
        ZStack {
            currentScreen
                .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.9), value: selectedTab)
        .safeAreaInset(edge: .bottom) {
            BottomDock(selectedTab: $selectedTab)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 6)
        }
    }

    @ViewBuilder
    private var currentScreen: some View {
        switch selectedTab {
        case .briefing:
            NavigationStack {
                TodayView(model: model, selectedTab: $selectedTab)
            }
        case .feed:
            NavigationStack {
                FeedView(model: model)
            }
        case .askAI:
            NavigationStack {
                AskAIView(model: model)
            }
        case .sources:
            NavigationStack {
                SourcesView(model: model)
            }
        case .library:
            NavigationStack {
                LibraryView(model: model)
            }
        }
    }

    private var loadPresentation: LoadPresentation {
        switch model.loadState {
        case .idle where !model.hasContent:
            return .loading
        case .loading where !model.hasContent:
            return .loading
        case .failed(let message) where !model.hasContent:
            return .error(message)
        default:
            return .tabs
        }
    }
}

struct BottomDock: View {
    @Binding var selectedTab: AppTab

    var body: some View {
        HStack(spacing: 8) {
            ForEach(AppTab.allCases) { tab in
                Button {
                    selectedTab = tab
                } label: {
                    VStack(spacing: 6) {
                        Image(systemName: tab.systemImage)
                            .font(.system(size: 17, weight: .semibold))
                        Text(tab.title)
                            .font(.caption2.weight(.semibold))
                            .lineLimit(1)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 11)
                    .foregroundStyle(selectedTab == tab ? Color.white : AppTheme.ink)
                    .background {
                        if selectedTab == tab {
                            Capsule(style: .continuous)
                                .fill(tab.accent.opacity(0.86))
                                .overlay {
                                    Capsule(style: .continuous)
                                        .fill(.ultraThinMaterial)
                                        .opacity(0.12)
                                }
                        }
                    }
                    .overlay {
                        if selectedTab == tab {
                            Capsule(style: .continuous)
                                .strokeBorder(Color.white.opacity(0.18), lineWidth: 1)
                        }
                    }
                    .shadow(color: selectedTab == tab ? tab.accent.opacity(0.20) : .clear, radius: 10, x: 0, y: 6)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(8)
        .background {
            Capsule(style: .continuous)
                .fill(AppTheme.panel)
                .overlay {
                    Capsule(style: .continuous)
                        .fill(.ultraThinMaterial)
                        .opacity(0.55)
                }
        }
        .overlay {
            Capsule(style: .continuous)
                .strokeBorder(AppTheme.border, lineWidth: 1)
        }
        .shadow(color: AppTheme.shadow, radius: 24, x: 0, y: 12)
    }
}

private enum LoadPresentation {
    case loading
    case error(String)
    case tabs
}
