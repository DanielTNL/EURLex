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
            return AppTheme.coral
        case .feed:
            return AppTheme.cobalt
        case .askAI:
            return AppTheme.mint
        case .sources:
            return AppTheme.amber
        case .library:
            return AppTheme.lavender
        }
    }
}

struct AppView: View {
    @StateObject private var model = AppModel()
    @State private var selectedTab: AppTab = .briefing
    @State private var loadedTabs: Set<AppTab> = [.briefing]
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            AmbientBackground()
            tabShell

            if let overlayMode = launchOverlayMode {
                LaunchOverlay(mode: overlayMode) {
                    Task { await model.reload() }
                }
                .padding(24)
                .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
        }
        .tint(AppTheme.cobalt)
        .animation(.spring(response: 0.35, dampingFraction: 0.9), value: model.loadState)
        .task {
            await model.prepareNotifications()
            if model.shouldLoad {
                await model.reload()
            }
        }
        .onChange(of: selectedTab) { _, newValue in
            loadedTabs.insert(newValue)
        }
        .onChange(of: scenePhase) { _, newPhase in
            guard newPhase == .active else { return }
            Task { await model.reload() }
        }
    }

    private var tabShell: some View {
        ZStack {
            ForEach(AppTab.allCases) { tab in
                if loadedTabs.contains(tab) {
                    tabScreen(tab)
                        .opacity(selectedTab == tab ? 1 : 0)
                        .allowsHitTesting(selectedTab == tab)
                        .zIndex(selectedTab == tab ? 1 : 0)
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            BottomDock(selectedTab: $selectedTab)
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 6)
        }
    }

    @ViewBuilder
    private func tabScreen(_ tab: AppTab) -> some View {
        switch tab {
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
                LibraryView(model: model, selectedTab: $selectedTab)
            }
        }
    }

    private var launchOverlayMode: LaunchOverlay.Mode? {
        guard !model.hasContent else { return nil }

        switch model.loadState {
        case .idle, .loading:
            return .loading
        case .failed(let message):
            return .error(message)
        case .loaded:
            return nil
        }
    }
}

struct BottomDock: View {
    @Binding var selectedTab: AppTab

    var body: some View {
        Group {
            if #available(iOS 26, *) {
                GlassEffectContainer(spacing: 8) {
                    dockContent
                }
            } else {
                dockContent
            }
        }
        .padding(8)
        .background {
            GlassCapsuleBackground(tint: AppTheme.cobalt, isSelected: false, interactive: false)
        }
        .shadow(color: AppTheme.shadow, radius: 24, x: 0, y: 12)
    }

    private var dockContent: some View {
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
                    .foregroundStyle(selectedTab == tab ? Color.white : AppTheme.pageBody)
                    .background {
                        if selectedTab == tab {
                            Capsule(style: .continuous)
                                .fill(
                                    LinearGradient(
                                        colors: [tab.accent, tab.accent.opacity(0.80)],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                                .overlay {
                                    Capsule(style: .continuous)
                                        .fill(.ultraThinMaterial)
                                        .opacity(0.10)
                                }
                                .overlay(alignment: .topLeading) {
                                    Capsule(style: .continuous)
                                        .strokeBorder(
                                            LinearGradient(
                                                colors: [
                                                    Color.white.opacity(0.48),
                                                    Color.white.opacity(0.14),
                                                    Color.clear
                                                ],
                                                startPoint: .topLeading,
                                                endPoint: .bottomTrailing
                                            ),
                                            lineWidth: 1
                                        )
                                }
                                .overlay {
                                    Capsule(style: .continuous)
                                        .strokeBorder(Color.white.opacity(0.28), lineWidth: 1)
                                }
                        }
                    }
                    .shadow(color: selectedTab == tab ? tab.accent.opacity(0.18) : .clear, radius: 10, x: 0, y: 6)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

private struct LaunchOverlay: View {
    enum Mode: Equatable {
        case loading
        case error(String)
    }

    let mode: Mode
    let retry: () -> Void

    var body: some View {
        VStack(spacing: 16) {
            switch mode {
            case .loading:
                ProgressView()
                    .controlSize(.large)
                    .tint(AppTheme.cobalt)

                Text("Loading EURLex")
                    .font(.title3.weight(.semibold))
                    .fontDesign(.rounded)
                    .foregroundStyle(AppTheme.pageTitle)

                Text("Pulling the latest GitHub briefing feed. The first simulator launch can take a little while after a fresh Xcode install.")
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(AppTheme.pageBody)
                    .lineSpacing(4)
            case .error(let message):
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 42))
                    .foregroundStyle(AppTheme.pageTitle)

                Text("Could not reach the published feeds")
                    .font(.title2.weight(.semibold))
                    .fontDesign(.rounded)
                    .foregroundStyle(AppTheme.pageTitle)

                Text(message)
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(AppTheme.pageBody)
                    .lineSpacing(4)

                Button("Retry", action: retry)
                    .buttonStyle(PrimaryCapsuleButtonStyle())
                    .padding(.top, 4)
            }
        }
        .frame(maxWidth: 420)
        .padding(24)
        .glassCard(cornerRadius: 32, tint: AppTheme.cobalt)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
