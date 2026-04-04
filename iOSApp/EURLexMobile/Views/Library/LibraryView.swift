import SwiftUI

struct LibraryView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    PageHeroHeader(
                        title: "Library",
                        subtitle: "Your archive of reports, audio, and documents in one place.",
                        accent: AppTheme.lavender
                    )

                    heroCard
                    reportsSection
                    audioSection
                    uploadsSection
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 30)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Your knowledge shelf")
                .font(.system(size: 34, weight: .bold, design: .serif))
                .foregroundStyle(AppTheme.ink)

            Text("This is where the polished archive lives now, and where uploaded PDFs, notes, and reference documents will join the corpus in the backend phase.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            HStack(spacing: 12) {
                sourceMetric(title: "Reports", value: "\(model.reports.count)", tint: AppTheme.cobalt)
                sourceMetric(title: "Audio", value: "\(model.audio.items.count)", tint: AppTheme.mint)
                sourceMetric(title: "Uploads", value: "Soon", tint: AppTheme.lavender)
            }
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.lavender, padding: 22)
    }

    private var reportsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Report archive",
                subtitle: "Already live from GitHub today.",
                accent: AppTheme.cobalt,
                tone: .page
            )

            if model.reports.isEmpty {
                Text("Reports will appear here as soon as the published feed loads.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
            } else {
                ForEach(Array(model.reports.prefix(3))) { report in
                    NavigationLink(destination: ReportDetailView(report: report)) {
                        ReportCardView(report: report)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var audioSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Audio briefings",
                subtitle: "The weekly recordings can stay in the same elegant archive.",
                accent: AppTheme.mint,
                tone: .page
            )

            if model.audio.items.isEmpty {
                Text("No audio feed is currently published, but the space is reserved for it.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.mint, padding: 16)
            } else {
                ForEach(Array(model.audio.items.prefix(2))) { item in
                    VStack(alignment: .leading, spacing: 10) {
                        Text(item.title)
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(AppTheme.ink)
                        Text(item.displayDateText)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.slate)
                        if let url = item.playbackURL {
                            ShareLink(item: url) {
                                Label("Share MP3", systemImage: "waveform")
                            }
                            .buttonStyle(SecondaryCapsuleButtonStyle())
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassCard(cornerRadius: 26, tint: AppTheme.mint, padding: 16)
                }
            }
        }
    }

    private var uploadsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Uploaded documents",
                subtitle: "NotebookLM-style ingestion comes in the backend phase.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(alignment: .leading, spacing: 10) {
                Text("Planned flow")
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)
                Text("1. Upload PDFs, notes, or briefs\n2. Extract and index them\n3. Fold them into Ask AI answers with citations")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
        }
    }

    private func sourceMetric(title: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.title3.weight(.bold))
                .foregroundStyle(AppTheme.ink)
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.white.opacity(0.58), in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.white.opacity(0.76), lineWidth: 1)
        )
    }
}
