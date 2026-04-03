import SwiftUI

struct AudioView: View {
    @ObservedObject var model: AppModel

    @State private var selectedURL: IdentifiedURL?

    private var monthlyItems: [AudioItem] {
        let direct = model.audio.monthly
        if !direct.isEmpty { return direct }
        return model.audio.items.filter { $0.kind == "monthly_roundtable" }
    }

    private var requestedItems: [AudioItem] {
        let direct = model.audio.requests
        if !direct.isEmpty { return direct }
        return model.audio.items.filter { $0.kind == "requested_weekly_brief" }
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    SectionTitle(
                        title: "Voice overview",
                        subtitle: monthlyItems.isEmpty ? "Monthly roundtables will appear here" : "\(monthlyItems.count) monthly discussions published",
                        tone: .page
                    )

                    overviewCard

                    if let latestMonthly = monthlyItems.first {
                        monthlyHeroCard(for: latestMonthly)
                    } else {
                        ContentUnavailableView(
                            "No monthly roundtable yet",
                            systemImage: "waveform.slash",
                            description: Text("The GitHub pipeline will publish a monthly two-person roundtable here.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 16)
                    }

                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(
                            title: "Requested weekly briefings",
                            subtitle: requestedItems.isEmpty ? "Ask AI can request a weekly audio recap once the backend trigger is wired." : "\(requestedItems.count) generated weekly briefings",
                            accent: AppTheme.coral
                        )

                        if requestedItems.isEmpty {
                            Text("No requested weekly audio has been uploaded yet.")
                                .font(.subheadline)
                                .foregroundStyle(AppTheme.slate)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .glassCard(cornerRadius: 26, tint: AppTheme.coral, padding: 16)
                        } else {
                            ForEach(requestedItems) { item in
                                audioCard(for: item, tint: AppTheme.coral)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("Audio")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await model.reload() }
                } label: {
                    if model.isLoading {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .tint(AppTheme.cobalt)
            }
        }
        .refreshable {
            await model.reload()
        }
        .sheet(item: $selectedURL) { destination in
            SafariSheet(url: destination.url)
        }
    }

    private var overviewCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("This space is now reserved for a monthly roundtable: a more critical conversation between two different voices about the biggest events of the month. Requested weekly audio briefs will appear below after they are generated.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            if let driveURL = model.audio.driveURL {
                Button {
                    selectedURL = IdentifiedURL(url: driveURL)
                } label: {
                    Label("Open Drive folder", systemImage: "folder")
                }
                .buttonStyle(PrimaryCapsuleButtonStyle())
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dossierCard()
    }

    private func monthlyHeroCard(for item: AudioItem) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("MONTHLY ROUNDTABLE")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.lavender)

                    Text(item.displayTitle)
                        .font(.system(size: 28, weight: .bold, design: .serif))
                        .foregroundStyle(AppTheme.ink)

                    Text(item.summaryPreview)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                }

                Spacer(minLength: 12)

                Text(item.displayDateText)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)
            }

            HStack(spacing: 12) {
                if let url = item.playbackURL {
                    Button {
                        selectedURL = IdentifiedURL(url: url)
                    } label: {
                        Label("Play discussion", systemImage: "play.circle.fill")
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())
                }

                if let url = item.playbackURL {
                    ShareLink(item: url) {
                        Label("Share", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 32, tint: AppTheme.lavender, padding: 20)
    }

    private func audioCard(for item: AudioItem, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(item.displayDateText)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(tint)
                Spacer()
                Text(item.series)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(AppTheme.slate)
            }

            Text(item.displayTitle)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)

            Text(item.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)

            HStack(spacing: 12) {
                if let url = item.playbackURL {
                    Button {
                        selectedURL = IdentifiedURL(url: url)
                    } label: {
                        Label("Play", systemImage: "play.circle")
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())

                    ShareLink(item: url) {
                        Label("Share", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                } else {
                    Text("This audio item does not have a valid playback URL.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: tint, padding: 18)
    }
}
