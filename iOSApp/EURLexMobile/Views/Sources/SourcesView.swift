import SwiftUI

struct SourcesView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    heroCard
                    currentSources
                    expansionCards
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 30)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("Sources")
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Grow the intake")
                .font(.system(size: 34, weight: .bold, design: .serif))
                .foregroundStyle(AppTheme.ink)

            Text("GitHub remains the reliable daily engine for now. In the backend phase, this screen becomes the control room for RSS feeds, watchlists, and source rules added directly from the app.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            HStack(spacing: 12) {
                sourceStat(title: "Live sources", value: "\(model.availableSources.count)", tint: AppTheme.coral)
                sourceStat(title: "Categories", value: "\(model.availableCategories.count)", tint: AppTheme.cobalt)
            }
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.coral, padding: 22)
    }

    private var currentSources: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Current GitHub-fed sources",
                subtitle: "These are already flowing through the existing pipeline.",
                accent: AppTheme.cobalt,
                tone: .page
            )

            if model.availableSources.isEmpty {
                Text("No sources are visible yet. Once the feed loads, current source labels will appear here.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
            } else {
                TagStrip(tags: model.availableSources)
                    .glassCard(cornerRadius: 26, tint: AppTheme.cobalt, padding: 16)
            }
        }
    }

    private var expansionCards: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Planned source types",
                subtitle: "Ready for the backend after the redesign.",
                accent: AppTheme.mint,
                tone: .page
            )

            planCard(
                title: "RSS and Atom feeds",
                subtitle: "Paste a feed URL in the app, validate it, and include it in the next daily refresh.",
                icon: "dot.radiowaves.left.and.right",
                tint: AppTheme.mint
            )
            planCard(
                title: "Website watchers",
                subtitle: "Add public pages that should be checked on a schedule and summarized into the corpus.",
                icon: "globe",
                tint: AppTheme.coral
            )
            planCard(
                title: "Source rules",
                subtitle: "Give sources labels, topic tags, and refresh rules so the app stays curated instead of chaotic.",
                icon: "slider.horizontal.3",
                tint: AppTheme.lavender
            )
        }
    }

    private func sourceStat(title: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.title2.weight(.bold))
                .foregroundStyle(AppTheme.ink)
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.white.opacity(0.58), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Color.white.opacity(0.76), lineWidth: 1)
        )
    }

    private func planCard(title: String, subtitle: String, icon: String, tint: Color) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title3.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 42, height: 42)
                .background(tint, in: RoundedRectangle(cornerRadius: 14, style: .continuous))

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .multilineTextAlignment(.leading)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 26, tint: tint, padding: 16)
    }
}
