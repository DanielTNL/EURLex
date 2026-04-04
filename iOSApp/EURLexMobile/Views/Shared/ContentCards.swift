import SwiftUI

enum SectionTitleTone {
    case page
    case card
    case reader
}

struct SectionTitle: View {
    let title: String
    let subtitle: String?
    var accent: Color = AppTheme.cobalt
    var tone: SectionTitleTone = .card

    private var titleColor: Color {
        switch tone {
        case .page:
            return AppTheme.pageTitle
        case .card:
            return AppTheme.ink
        case .reader:
            return AppTheme.ink
        }
    }

    private var subtitleColor: Color {
        switch tone {
        case .page:
            return AppTheme.pageSubtext
        case .card:
            return AppTheme.slate
        case .reader:
            return AppTheme.heroSubtext
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Circle()
                    .fill(accent)
                    .frame(width: 10, height: 10)

                Text(title)
                    .font(.title2.weight(.bold))
                    .fontDesign(.serif)
                    .foregroundStyle(titleColor)
            }

            if let subtitle, !subtitle.isEmpty {
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(subtitleColor)
            }
        }
    }
}


struct PageHeroHeader: View {
    let title: String
    let subtitle: String
    var accent: Color = AppTheme.cobalt

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                RoundedRectangle(cornerRadius: 999, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [accent, AppTheme.lavender],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: 46, height: 8)

                Text("Platform View")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(AppTheme.heroSubtext)
                    .textCase(.uppercase)
            }

            Text(title)
                .font(.system(size: 36, weight: .bold, design: .serif))
                .foregroundStyle(
                    LinearGradient(
                        colors: [AppTheme.heroText, Color.white.opacity(0.84)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            Text(subtitle)
                .font(.subheadline)
                .foregroundStyle(AppTheme.heroSubtext)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 32, tint: accent, padding: 22)
        .overlay(alignment: .topTrailing) {
            Circle()
                .fill(accent.opacity(0.20))
                .frame(width: 118, height: 118)
                .blur(radius: 24)
                .offset(x: 24, y: -26)
                .allowsHitTesting(false)
        }
    }
}

struct PostCardView: View {
    let post: Post

    private var accent: Color { AppTheme.accent(for: post.source) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 8) {
                    sourceBadge

                    if let reference = post.reference {
                        Text(reference)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(AppTheme.plumSoft)
                    }
                }
                Spacer()
                Text(post.displayDateText)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(AppTheme.slate)
            }

            Text(post.displayTitle)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .multilineTextAlignment(.leading)

            if post.hasDistinctOriginalTitle {
                Text(post.originalTitleDisplay)
                    .font(.caption)
                    .foregroundStyle(AppTheme.plumSoft)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }

            Text(post.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)
                .multilineTextAlignment(.leading)

            TagStrip(tags: post.primaryTags)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: accent)
    }

    private var sourceBadge: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(accent)
                .frame(width: 8, height: 8)
            Text(post.source.uppercased())
                .font(.caption.weight(.bold))
        }
        .foregroundStyle(accent)
    }
}

struct ReportCardView: View {
    let report: Report

    private var accent: Color {
        report.tags.contains("weekly") ? AppTheme.coral : AppTheme.cobalt
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                labelBadge(report.typeLabel, color: accent)
                Spacer()
                Text(report.displayDateText)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(AppTheme.slate)
            }

            Text(report.displayTitle)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .multilineTextAlignment(.leading)

            Text(report.abstractPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)

            HStack(spacing: 12) {
                Label("\(report.keyItems.count) key items", systemImage: "list.bullet.rectangle")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)

                if !report.tags.isEmpty {
                    Text(report.tags.joined(separator: " • "))
                        .font(.caption)
                        .foregroundStyle(AppTheme.slate)
                        .lineLimit(1)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: accent)
    }
}

struct DigestCardView: View {
    let item: DigestItem

    private var accent: Color { AppTheme.accent(for: item.docType) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                labelBadge(item.docType, color: accent)
                Spacer()
                Text(item.displayDateText)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(AppTheme.slate)
            }

            Text(item.title)
                .font(.headline.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .multilineTextAlignment(.leading)

            Text(item.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)

            TagStrip(tags: item.topicTags)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: accent)
    }
}

struct TimelineEventCardView: View {
    let event: TimelineEvent

    private var accent: Color { AppTheme.accent(for: event.stage + event.docType) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                labelBadge(event.stage.isEmpty ? event.docType : event.stage, color: accent)
                Spacer()
                Text(event.displayDateText)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(AppTheme.slate)
            }

            Text(event.title)
                .font(.headline.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .multilineTextAlignment(.leading)

            Text(event.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)

            TagStrip(tags: Array((event.programme + event.techArea).uniquePreservingOrder().prefix(4)))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: accent)
    }
}

private func labelBadge(_ title: String, color: Color) -> some View {
    HStack(spacing: 8) {
        Circle()
            .fill(color)
            .frame(width: 8, height: 8)
        Text(title.uppercased())
            .font(.caption.weight(.bold))
    }
    .foregroundStyle(color)
}
