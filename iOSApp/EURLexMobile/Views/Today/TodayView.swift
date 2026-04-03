import SwiftUI

struct TodayView: View {
    @ObservedObject var model: AppModel
    @Binding var selectedTab: AppTab

    private let newspaperColumns = [
        GridItem(.flexible(), spacing: 14),
        GridItem(.flexible(), spacing: 14)
    ]

    @State private var selectedDay: Date?
    @State private var selectedReport: Report?
    @State private var selectedPost: Post?
    @State private var showingRelatedArticles = false
    @State private var showingCategories = false

    private var calendar: Calendar { .autoupdatingCurrent }

    private var availableDays: [Date] {
        var unique = Set<Date>()
        var ordered: [Date] = []

        let candidates = model.posts.compactMap(\.addedDate)
            + model.reports.compactMap(\.reportDate)
            + model.timeline.events.compactMap { EURLexDate.parse($0.date) }
            + [model.digest?.generatedDate].compactMap { $0 }

        for date in candidates.sorted(by: >) {
            let start = calendar.startOfDay(for: date)
            if unique.insert(start).inserted {
                ordered.append(start)
            }
        }

        return ordered.isEmpty ? [calendar.startOfDay(for: Date())] : ordered
    }

    private var activeDay: Date {
        if let selectedDay {
            return selectedDay
        }
        return availableDays.first ?? calendar.startOfDay(for: Date())
    }

    private var daySnapshot: DaySnapshot {
        snapshot(for: activeDay)
    }

    private var weeklyReport: Report? {
        model.reports.first { $0.tags.contains("weekly") }
    }

    private var weeklyPosts: [Post] {
        guard let reportDate = weeklyReport?.reportDate else { return [] }
        return model.posts.filter {
            guard let date = $0.addedDate else { return false }
            return calendar.isDate(date, equalTo: reportDate, toGranularity: .weekOfYear)
        }
        .prefix(4)
        .map { $0 }
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    dayOverviewCard
                    daySelector
                    if let weeklyReport {
                        sundayEditionSection(report: weeklyReport)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 30)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("Briefing")
        .navigationDestination(item: $selectedReport) { report in
            ReportDetailView(report: report)
        }
        .navigationDestination(item: $selectedPost) { post in
            PostDetailView(post: post)
        }
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
        .onChange(of: availableDays.first) { _, newValue in
            guard let newValue, selectedDay == nil else { return }
            selectedDay = newValue
        }
        .sheet(isPresented: $showingRelatedArticles) {
            BriefingRelatedArticlesSheet(posts: daySnapshot.posts)
        }
        .sheet(isPresented: $showingCategories) {
            BriefingCategoriesSheet(categories: daySnapshot.topCategories)
        }
    }

    private var dayOverviewCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("AI Daily Brief", systemImage: "sparkles.rectangle.stack")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.mint)

                    Text(dayTitle(for: activeDay))
                        .font(.system(size: 34, weight: .bold, design: .serif))
                        .foregroundStyle(AppTheme.ink)

                    Text(daySnapshot.introParagraph)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                        .lineSpacing(4)
                }

                Spacer(minLength: 12)
                SyncStatusBadge(state: model.loadState)
            }

            publishedPulse

            VStack(alignment: .leading, spacing: 12) {
                if !daySnapshot.headline.isEmpty {
                    Text(daySnapshot.headline)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                }

                HStack(spacing: 10) {
                    Button {
                        openPrimaryBriefingDestination()
                    } label: {
                        Label("View more", systemImage: "arrow.right.circle")
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())

                    Button {
                        showingRelatedArticles = true
                    } label: {
                        Label("Related articles", systemImage: "newspaper")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                    .disabled(daySnapshot.posts.isEmpty)
                }

                HStack(spacing: 10) {
                    Button {
                        showingCategories = true
                    } label: {
                        Label("Categories", systemImage: "square.grid.2x2")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                    .disabled(daySnapshot.topCategories.isEmpty)

                    Button {
                        selectedTab = .feed
                    } label: {
                        Label("Open feed", systemImage: "text.append")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                }
            }
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.cobalt, padding: 22)
    }

    private var publishedPulse: some View {
        HStack(spacing: 8) {
            Text("\(daySnapshot.signalCount) published signals")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(AppTheme.ink)

            Circle()
                .fill(AppTheme.border)
                .frame(width: 4, height: 4)

            Text("\(daySnapshot.reports.count) reports")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            Circle()
                .fill(AppTheme.border)
                .frame(width: 4, height: 4)

            Text("\(daySnapshot.timelineEvents.count) timeline items")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(AppTheme.panelSoft, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(AppTheme.border, lineWidth: 1)
        )
    }

    private var daySelector: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Other days",
                subtitle: "Tap a date to shift the briefing without leaving the main tab.",
                accent: AppTheme.lavender,
                tone: .page
            )

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(availableDays.prefix(8), id: \.self) { day in
                        let snapshot = snapshot(for: day)
                        Button {
                            selectedDay = day
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(shortWeekday(for: day).uppercased())
                                    .font(.caption2.weight(.bold))
                                    .foregroundStyle(isSelected(day) ? Color.white.opacity(0.84) : AppTheme.slate)
                                Text(dayNumber(for: day))
                                    .font(.title3.weight(.bold))
                                    .foregroundStyle(AppTheme.ink)
                                Text("\(snapshot.signalCount) signals")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(isSelected(day) ? Color.white.opacity(0.84) : AppTheme.slate)
                            }
                            .frame(width: 88, alignment: .leading)
                            .padding(14)
                            .background {
                                RoundedRectangle(cornerRadius: 24, style: .continuous)
                                    .fill(isSelected(day) ? AppTheme.coral.opacity(0.88) : AppTheme.panelSoft)
                                    .overlay {
                                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                                            .fill(.ultraThinMaterial)
                                            .opacity(isSelected(day) ? 0.10 : 0.24)
                                    }
                            }
                            .overlay {
                                RoundedRectangle(cornerRadius: 24, style: .continuous)
                                    .strokeBorder(isSelected(day) ? Color.white.opacity(0.20) : AppTheme.border, lineWidth: 1)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
            }
            .mask {
                HorizontalEdgeFadeMask(fadeWidth: 26)
            }
        }
    }

    private func sundayEditionSection(report: Report) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            SectionTitle(
                title: "Sunday Edition",
                subtitle: "A more editorial weekly read, designed to feel like a compact newspaper.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("WEEKEND FRONT PAGE")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(AppTheme.lavender)

                        Text(report.title)
                            .font(.system(size: 30, weight: .bold, design: .serif))
                            .foregroundStyle(AppTheme.ink)

                        Text(report.abstractPreview)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.slate)
                    }

                    Spacer(minLength: 12)

                    VStack(alignment: .trailing, spacing: 6) {
                        Text(report.displayDateText)
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(AppTheme.ink)
                        Text("Sunday morning edition")
                            .font(.caption)
                            .foregroundStyle(AppTheme.slate)
                    }
                }

                NavigationLink(destination: ReportDetailView(report: report)) {
                    Label("Read full weekly edition", systemImage: "newspaper.fill")
                }
                .buttonStyle(PrimaryCapsuleButtonStyle())
            }
            .glassCard(cornerRadius: 34, tint: AppTheme.lavender, padding: 22)

            LazyVGrid(columns: newspaperColumns, spacing: 14) {
                ForEach(Array(report.keyItems.prefix(4).enumerated()), id: \.offset) { index, item in
                    newspaperTile(
                        kicker: "Section \(index + 1)",
                        headline: item,
                        body: supportingStory(for: index),
                        tint: index.isMultiple(of: 2) ? AppTheme.cobalt : AppTheme.coral
                    )
                }
            }

            if !weeklyPosts.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Related reading")
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)

                    ForEach(weeklyPosts) { post in
                        NavigationLink(destination: PostDetailView(post: post)) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(post.source.uppercased())
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(AppTheme.mint)
                                Text(post.title)
                                    .font(.headline.weight(.semibold))
                                    .foregroundStyle(AppTheme.ink)
                                Text(post.summaryPreview)
                                    .font(.subheadline)
                                    .foregroundStyle(AppTheme.slate)
                                    .lineLimit(3)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func newspaperTile(kicker: String, headline: String, body: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(kicker)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)

            Text(headline)
                .font(.headline.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(body)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, minHeight: 180, alignment: .topLeading)
        .glassCard(cornerRadius: 28, tint: tint, padding: 18)
    }

    private func snapshot(for day: Date) -> DaySnapshot {
        let reports = model.reports.filter { report in
            guard let reportDate = report.reportDate else { return false }
            return calendar.isDate(reportDate, inSameDayAs: day)
        }

        let posts = model.posts.filter { post in
            guard let addedDate = post.addedDate else { return false }
            return calendar.isDate(addedDate, inSameDayAs: day)
        }
        .prefix(5)
        .map { $0 }

        let timelineEvents = model.timeline.events.filter { event in
            guard let date = EURLexDate.parse(event.date) else { return false }
            return calendar.isDate(date, inSameDayAs: day)
        }
        .prefix(4)
        .map { $0 }

        var digestItems = (model.digest?.items ?? []).filter { item in
            guard let publishedDate = item.publishedDate, let date = EURLexDate.parse(publishedDate) else { return false }
            return calendar.isDate(date, inSameDayAs: day)
        }

        if digestItems.isEmpty,
           let digestDate = model.digest?.generatedDate,
           calendar.isDate(digestDate, inSameDayAs: day) {
            digestItems = Array((model.digest?.items ?? []).prefix(4))
        }

        return DaySnapshot(
            day: day,
            digestItems: Array(digestItems.prefix(4)),
            posts: posts,
            reports: reports,
            timelineEvents: timelineEvents
        )
    }

    private func supportingStory(for index: Int) -> String {
        let fallback = [
            "The weekly edition will read more like a compact newspaper once the backend assembles sections automatically.",
            "This slot is intended for AI-written context, section decks, and clearer editorial transitions.",
            "Related source material from the same week can sit beneath the editorial summary for fast drilling in.",
            "The Sunday morning refresh can combine the weekly report with selected article cards and source citations."
        ]

        if weeklyPosts.indices.contains(index) {
            return weeklyPosts[index].summaryPreview
        }

        return fallback[index % fallback.count]
    }

    private func dayTitle(for day: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE d MMMM"
        return formatter.string(from: day)
    }

    private func shortWeekday(for day: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEE"
        return formatter.string(from: day)
    }

    private func dayNumber(for day: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "d"
        return formatter.string(from: day)
    }

    private func isSelected(_ day: Date) -> Bool {
        calendar.isDate(day, inSameDayAs: activeDay)
    }

    private func openPrimaryBriefingDestination() {
        if let report = daySnapshot.dailyReport {
            selectedReport = report
            return
        }

        if let firstDigestURL = daySnapshot.digestItems.first?.destinationURL {
            selectedPost = nil
            UIApplication.shared.open(firstDigestURL)
            return
        }

        if let post = daySnapshot.posts.first {
            selectedPost = post
            return
        }

        if let weeklyReport {
            selectedReport = weeklyReport
            return
        }

        selectedTab = .feed
    }
}

private struct DaySnapshot {
    let day: Date
    let digestItems: [DigestItem]
    let posts: [Post]
    let reports: [Report]
    let timelineEvents: [TimelineEvent]

    var dailyReport: Report? {
        reports.first { $0.tags.contains("daily") }
    }

    var signalCount: Int {
        digestItems.count + posts.count + timelineEvents.count
    }

    var headline: String {
        if let dailyReport {
            return dailyReport.title
        }
        if let digestItem = digestItems.first {
            return digestItem.title
        }
        if let post = posts.first {
            return post.title
        }
        if let event = timelineEvents.first {
            return event.title
        }
        return "No published briefing yet"
    }

    var summary: String {
        if let dailyReport {
            return dailyReport.abstractPreview
        }

        let digestSummary = digestItems.prefix(2).map(\.summaryPreview).joined(separator: " ")
        if !digestSummary.isEmpty {
            return trimmed(digestSummary, limit: 260)
        }

        if let firstPost = posts.first {
            return trimmed("The feed for this day is led by \(firstPost.title). \(posts.count) source articles and \(timelineEvents.count) timeline signals are currently attached to this briefing day.", limit: 260)
        }

        if let firstEvent = timelineEvents.first {
            return trimmed(firstEvent.summaryPreview, limit: 220)
        }

        return "The published corpus does not currently contain a daily briefing for this date, but the app keeps the day available so you can move through the archive quickly."
    }

    var introParagraph: String {
        let opener: String
        if dailyReport != nil {
            opener = "Today’s briefing opens with a published daily report."
        } else if !digestItems.isEmpty {
            opener = "Today’s briefing is assembled from the published digest and source flow so far."
        } else if !posts.isEmpty {
            opener = "Today’s picture is being shaped directly from the live source articles collected so far."
        } else if !timelineEvents.isEmpty {
            opener = "Today is currently led by forward-looking timeline signals rather than a full written brief."
        } else {
            opener = "No full briefing has been published for this date yet."
        }

        return trimmed("\(opener) \(summary)", limit: 280)
    }

    var topLines: [String] {
        if let dailyReport, !dailyReport.keyItems.isEmpty {
            return Array(dailyReport.keyItems.prefix(3))
        }

        let digestTitles = digestItems.map(\.title)
        if !digestTitles.isEmpty {
            return Array(digestTitles.prefix(3))
        }

        let postTitles = posts.map(\.title)
        if !postTitles.isEmpty {
            return Array(postTitles.prefix(3))
        }

        return timelineEvents.map(\.title).prefix(3).map { $0 }
    }

    var topCategories: [String] {
        Array(posts.flatMap(\.categories).uniquePreservingOrder().prefix(8))
    }

    private func trimmed(_ text: String, limit: Int) -> String {
        guard text.count > limit else { return text }
        return String(text.prefix(limit - 1)) + "…"
    }
}

private struct BriefingRelatedArticlesSheet: View {
    let posts: [Post]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if posts.isEmpty {
                        ContentUnavailableView(
                            "No related articles",
                            systemImage: "newspaper",
                            description: Text("This day does not yet have supporting source articles attached to it.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 40)
                    } else {
                        ForEach(posts) { post in
                            NavigationLink(destination: PostDetailView(post: post)) {
                                PostCardView(post: post)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(20)
                .padding(.bottom, 20)
            }
            .navigationTitle("Related articles")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct BriefingCategoriesSheet: View {
    let categories: [String]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("General categories")
                        .font(.title2.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.plum)

                    Text("These are the strongest topic labels attached to the selected day so far.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.plumSoft)

                    if categories.isEmpty {
                        ContentUnavailableView(
                            "No categories yet",
                            systemImage: "square.grid.2x2",
                            description: Text("The selected day does not yet expose category metadata.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 28)
                    } else {
                        TagStrip(tags: categories)
                            .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
                    }
                }
                .padding(20)
                .padding(.bottom, 20)
            }
            .navigationTitle("Categories")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
        .presentationDetents([.medium])
    }
}
