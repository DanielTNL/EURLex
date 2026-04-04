import SwiftUI

struct LibraryView: View {
    @ObservedObject var model: AppModel
    @State private var selectedSundayEdition: SundayEditionEntry?

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
                    sundayArchiveSection
                    reportsSection
                    audioSection
                    uploadsSection
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, AppTheme.screenBottomClearance)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $selectedSundayEdition) { edition in
            SundayEditionReaderView(edition: edition)
        }
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
                sourceMetric(title: "Docs", value: "\(model.libraryDocuments.count)", tint: AppTheme.lavender)
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

    private var sundayArchiveSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Sunday archive",
                subtitle: "The long-form weekly editions live here after Sunday so the main briefing stays focused.",
                accent: AppTheme.lavender,
                tone: .page
            )

            if model.sundayEditions.items.isEmpty {
                Text("Sunday editions will appear here once the weekly newsletter is published.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.lavender, padding: 16)
            } else {
                ForEach(Array(model.sundayEditions.items.prefix(4))) { edition in
                    Button {
                        selectedSundayEdition = edition
                    } label: {
                        VStack(alignment: .leading, spacing: 14) {
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("SUNDAY EDITION")
                                        .font(.caption.weight(.bold))
                                        .foregroundStyle(AppTheme.lavender)

                                    Text(edition.headline)
                                        .font(.title3.weight(.semibold))
                                        .fontDesign(.serif)
                                        .foregroundStyle(AppTheme.ink)
                                        .multilineTextAlignment(.leading)
                                }

                                Spacer(minLength: 12)

                                Text(edition.displayDateText)
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(AppTheme.slate)
                            }

                            Text(edition.intro)
                                .font(.subheadline)
                                .foregroundStyle(AppTheme.slate)
                                .lineLimit(4)

                            if !edition.keyPoints.isEmpty {
                                HStack(spacing: 8) {
                                    ForEach(Array(edition.keyPoints.prefix(2).enumerated()), id: \.offset) { _, item in
                                        Text(item)
                                            .font(.caption.weight(.semibold))
                                            .foregroundStyle(AppTheme.ink)
                                            .padding(.horizontal, 12)
                                            .padding(.vertical, 8)
                                            .background(
                                                Capsule(style: .continuous)
                                                    .fill(Color.white.opacity(0.10))
                                            )
                                            .lineLimit(1)
                                    }
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassCard(cornerRadius: 28, tint: AppTheme.lavender, padding: 18)
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
                subtitle: "Published library documents, notes, and uploads land here once GitHub finishes processing them.",
                accent: AppTheme.lavender,
                tone: .page
            )

            if model.libraryDocuments.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("No library documents yet")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                    Text("Add links, notes, or files from the Sources tab and they will appear here after GitHub processes the intake.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
            } else {
                ForEach(Array(model.libraryDocuments.prefix(4))) { document in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .top, spacing: 12) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(document.title)
                                    .font(.headline.weight(.semibold))
                                    .foregroundStyle(AppTheme.ink)

                                Text("\(document.displayStatus) • \(document.sizeText)")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(AppTheme.lavender)
                            }

                            Spacer(minLength: 0)

                            if let url = document.destinationURL {
                                ShareLink(item: url) {
                                    Image(systemName: "arrow.up.forward.app")
                                        .font(.subheadline.weight(.bold))
                                        .foregroundStyle(AppTheme.pageTitle)
                                        .frame(width: 34, height: 34)
                                        .background(Color.white.opacity(0.58), in: Circle())
                                }
                                .buttonStyle(.plain)
                            }
                        }

                        Text(document.summaryPreview)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.slate)
                            .lineLimit(4)

                        if !document.tags.isEmpty {
                            TagStrip(tags: document.tags)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
                }
            }
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
