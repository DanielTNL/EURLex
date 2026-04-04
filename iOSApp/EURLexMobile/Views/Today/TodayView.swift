import SwiftUI

struct TodayView: View {
    @ObservedObject var model: AppModel
    @Binding var selectedTab: AppTab

    @State private var selectedDay: Date?
    @State private var selectedReport: Report?
    @State private var selectedPost: Post?
    @State private var selectedBriefingReader: DailyBriefingEntry?
    @State private var selectedSundayEdition: SundayEditionEntry?
    @State private var showingRelatedArticles = false
    @State private var showingCategories = false

    private var calendar: Calendar { .autoupdatingCurrent }

    private var availableDays: [Date] {
        let editorialDays = model.briefings.items.compactMap(\.briefingDate)
        if !editorialDays.isEmpty {
            return editorialDays
        }

        var unique = Set<Date>()
        var ordered: [Date] = []

        let candidates = model.posts.compactMap { $0.addedDate }
            + model.reports.compactMap { $0.reportDate }
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

    private var activeBriefing: DailyBriefingEntry? {
        model.briefing(for: activeDay)
    }

    private var weeklyReport: Report? {
        model.reports.first { $0.tags.contains("weekly") }
    }

    private var sundayEdition: SundayEditionEntry? {
        model.latestSundayEdition
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    PageHeroHeader(
                        title: "Briefing",
                        subtitle: "The daily front page for the brief, key points, and linked documents.",
                        accent: AppTheme.cobalt
                    )

                    dayOverviewCard

                    if !editorialImportantDocuments.isEmpty || !daySnapshot.prominentDocuments.isEmpty {
                        importantDocumentsSection
                    }

                    if !editorialCategories.isEmpty || !daySnapshot.topCategories.isEmpty {
                        categoriesSection
                    }

                    if !editorialRelatedDocuments.isEmpty || !daySnapshot.relatedPosts.isEmpty {
                        relatedDocumentsSection
                    }

                    daySelector

                    if let sundayEdition {
                        sundayEditionSection(edition: sundayEdition)
                    } else if let weeklyReport {
                        sundayEditionSection(report: weeklyReport)
                    }
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
        .navigationDestination(item: $selectedReport) { report in
            ReportDetailView(report: report)
        }
        .navigationDestination(item: $selectedPost) { post in
            PostDetailView(post: post)
        }
        .navigationDestination(item: $selectedBriefingReader) { briefing in
            BriefingReaderView(briefing: briefing)
        }
        .navigationDestination(item: $selectedSundayEdition) { edition in
            SundayEditionReaderView(edition: edition)
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
            if let briefing = activeBriefing {
                EditorialDocumentsSheet(title: "Related documents", subtitle: "Original source titles and links attached to this briefing.", documents: briefing.relatedDocuments)
            } else {
                BriefingRelatedArticlesSheet(posts: daySnapshot.relatedPosts)
            }
        }
        .sheet(isPresented: $showingCategories) {
            BriefingCategoriesSheet(categories: daySnapshot.topCategories)
        }
    }

    private var editorialImportantDocuments: [EditorialDocument] {
        activeBriefing?.importantDocuments ?? []
    }

    private var editorialRelatedDocuments: [EditorialDocument] {
        activeBriefing?.relatedDocuments ?? []
    }

    private var editorialCategories: [String] {
        activeBriefing?.categories ?? []
    }

    private var dayOverviewCard: some View {
        if let briefing = activeBriefing {
            AnyView(editorialDayOverviewCard(briefing))
        } else {
            AnyView(legacyDayOverviewCard)
        }
    }

    private func editorialDayOverviewCard(_ briefing: DailyBriefingEntry) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("AI Daily Brief", systemImage: "sparkles.rectangle.stack")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.mint)

                    Text(briefing.title)
                        .font(.system(size: 30, weight: .bold, design: .serif))
                        .foregroundStyle(AppTheme.ink)

                    Text(briefing.headline)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(AppTheme.heroSubtext)
                }

                Spacer(minLength: 12)
                SyncStatusBadge(state: model.loadState)
            }

            Text(briefing.intro)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
                .lineSpacing(5)

            if !briefing.keyPoints.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Key points")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.lavender)

                    ForEach(Array(briefing.keyPoints.prefix(4).enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(AppTheme.cobalt)
                                .frame(width: 7, height: 7)
                                .padding(.top, 6)

                            Text(item)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(AppTheme.ink)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }

            HStack(spacing: 10) {
                briefingMetaPill(title: "Signals", value: briefing.signalCounts.posts + briefing.signalCounts.digestItems + briefing.signalCounts.timelineEvents, tint: AppTheme.cobalt)
                briefingMetaPill(title: "Docs", value: briefing.importantDocuments.count, tint: AppTheme.lavender)
                briefingMetaPill(title: "Themes", value: briefing.categories.count, tint: AppTheme.mint)
            }

            Button {
                selectedBriefingReader = briefing
            } label: {
                Label("View full briefing", systemImage: "text.document")
            }
            .buttonStyle(PrimaryCapsuleButtonStyle())
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.cobalt, padding: 22)
    }

    private var legacyDayOverviewCard: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 10) {
                    Label("AI Daily Brief", systemImage: "sparkles.rectangle.stack")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.mint)

                    Text(dayTitle(for: activeDay))
                        .font(.system(size: 34, weight: .bold, design: .serif))
                        .foregroundStyle(AppTheme.ink)
                }

                Spacer(minLength: 12)
                SyncStatusBadge(state: model.loadState)
            }

            Text(daySnapshot.introParagraph)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
                .lineSpacing(5)

            if !daySnapshot.topLines.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Key points")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.lavender)

                    ForEach(Array(daySnapshot.topLines.prefix(3).enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(AppTheme.cobalt)
                                .frame(width: 7, height: 7)
                                .padding(.top, 6)

                            Text(item)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(AppTheme.ink)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }

            briefingMetaRow

            Button {
                openPrimaryBriefingDestination()
            } label: {
                Label("View more", systemImage: "arrow.right.circle")
            }
            .buttonStyle(PrimaryCapsuleButtonStyle())
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.cobalt, padding: 22)
    }

    private var briefingMetaRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                briefingMetaPill(title: "Signals", value: daySnapshot.signalCount, tint: AppTheme.cobalt)
                briefingMetaPill(title: "Reports", value: daySnapshot.reports.count, tint: AppTheme.lavender)
                briefingMetaPill(title: "Categories", value: daySnapshot.topCategories.count, tint: AppTheme.mint)
                briefingMetaPill(title: "Timeline", value: daySnapshot.timelineEvents.count, tint: AppTheme.coral)
            }
            .padding(.vertical, 2)
        }
    }

    private func briefingMetaPill(title: String, value: Int, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(value)")
                .font(.headline.weight(.bold))
                .foregroundStyle(AppTheme.ink)
            Text(title.uppercased())
                .font(.caption2.weight(.bold))
                .foregroundStyle(tint)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(AppTheme.panelSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(AppTheme.border, lineWidth: 1)
        )
    }

    private var importantDocumentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Important documents",
                subtitle: "The clearest entry points for this day.",
                accent: AppTheme.cobalt,
                tone: .page
            )

            if let briefing = activeBriefing, !briefing.importantDocuments.isEmpty {
                ForEach(briefing.importantDocuments) { document in
                    Button {
                        open(document)
                    } label: {
                        EditorialDocumentCard(document: document)
                    }
                    .buttonStyle(.plain)
                }
            } else {
                ForEach(daySnapshot.prominentDocuments) { document in
                    Button {
                        open(document)
                    } label: {
                        BriefingDocumentCard(document: document)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var categoriesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Categories",
                subtitle: "The strongest themes attached to this day so far.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(alignment: .leading, spacing: 12) {
                TagStrip(tags: activeBriefing?.categories ?? daySnapshot.topCategories)

                Button {
                    showingCategories = true
                } label: {
                    Label("View all categories", systemImage: "square.grid.2x2")
                }
                .buttonStyle(SecondaryCapsuleButtonStyle())
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
        }
    }

    private var relatedDocumentsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Related documents",
                subtitle: "A few nearby reads if you want to go deeper.",
                accent: AppTheme.mint,
                tone: .page
            )

            if let briefing = activeBriefing, !briefing.relatedDocuments.isEmpty {
                ForEach(Array(briefing.relatedDocuments.prefix(2))) { document in
                    Button {
                        open(document)
                    } label: {
                        EditorialDocumentCard(document: document, accent: AppTheme.mint)
                    }
                    .buttonStyle(.plain)
                }
            } else {
                ForEach(Array(daySnapshot.relatedPosts.prefix(2))) { post in
                    Button {
                        selectedPost = post
                    } label: {
                        BriefingRelatedPostCard(post: post)
                    }
                    .buttonStyle(.plain)
                }
            }

            Button {
                showingRelatedArticles = true
            } label: {
                Label("Browse related documents", systemImage: "newspaper")
            }
            .buttonStyle(SecondaryCapsuleButtonStyle())
        }
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
                                    .foregroundStyle(isSelected(day) ? Color.white.opacity(0.90) : AppTheme.slate)
                                Text(dayNumber(for: day))
                                    .font(.title3.weight(.bold))
                                    .foregroundStyle(AppTheme.ink)
                                Text(dayChipLabel(for: day, snapshot: snapshot))
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(isSelected(day) ? Color.white.opacity(0.90) : AppTheme.slate)
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
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Sunday Edition",
                subtitle: "The weekly newspaper-style overview lives here each Sunday morning.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("WEEKEND FRONT PAGE")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(AppTheme.lavender)

                        Text(report.displayTitle)
                            .font(.system(size: 28, weight: .bold, design: .serif))
                            .foregroundStyle(AppTheme.ink)

                        Text(report.abstractPreview)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.slate)
                            .lineLimit(4)
                    }

                    Spacer(minLength: 12)

                    Text(report.displayDateText)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                }

                NavigationLink(destination: ReportDetailView(report: report)) {
                    Label("Read full weekly edition", systemImage: "newspaper.fill")
                }
                .buttonStyle(PrimaryCapsuleButtonStyle())
            }
            .glassCard(cornerRadius: 34, tint: AppTheme.lavender, padding: 22)
        }
    }

    private func sundayEditionSection(edition: SundayEditionEntry) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(
                title: "Sunday Edition",
                subtitle: "A structured weekly read with original titles and source links close at hand.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("WEEKEND FRONT PAGE")
                            .font(.caption.weight(.bold))
                            .foregroundStyle(AppTheme.lavender)

                        Text(edition.headline)
                            .font(.system(size: 28, weight: .bold, design: .serif))
                            .foregroundStyle(AppTheme.ink)

                        Text(edition.intro)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.slate)
                            .lineLimit(4)
                    }

                    Spacer(minLength: 12)

                    Text(edition.displayWeekRange)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                }

                if !edition.keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(Array(edition.keyPoints.prefix(3).enumerated()), id: \.offset) { _, item in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(AppTheme.lavender)
                                    .frame(width: 7, height: 7)
                                    .padding(.top, 6)

                                Text(item)
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(AppTheme.ink)
                            }
                        }
                    }
                }

                Button {
                    selectedSundayEdition = edition
                } label: {
                    Label("Read full weekly edition", systemImage: "newspaper.fill")
                }
                .buttonStyle(PrimaryCapsuleButtonStyle())
            }
            .glassCard(cornerRadius: 34, tint: AppTheme.lavender, padding: 22)
        }
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
        .prefix(6)
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

    private func dayChipLabel(for day: Date, snapshot: DaySnapshot) -> String {
        if let briefing = model.briefing(for: day) {
            return "\(briefing.importantDocuments.count) docs"
        }
        return "\(snapshot.signalCount) signals"
    }

    private func openPrimaryBriefingDestination() {
        if let briefing = activeBriefing {
            selectedBriefingReader = briefing
            return
        }

        if let document = daySnapshot.prominentDocuments.first {
            open(document)
            return
        }

        if let firstDigestURL = daySnapshot.digestItems.first?.destinationURL {
            UIApplication.shared.open(firstDigestURL)
            return
        }

        if let weeklyReport {
            selectedReport = weeklyReport
            return
        }

        selectedTab = .feed
    }

    private func open(_ document: BriefingDocument) {
        switch document {
        case .report(let report):
            selectedReport = report
        case .post(let post):
            selectedPost = post
        }
    }

    private func open(_ document: EditorialDocument) {
        if let report = model.reports.first(where: { $0.urlHtml.caseInsensitiveCompare(document.url) == .orderedSame }) {
            selectedReport = report
            return
        }

        if let post = model.posts.first(where: { $0.url.caseInsensitiveCompare(document.url) == .orderedSame }) {
            selectedPost = post
            return
        }

        if let url = document.destinationURL {
            UIApplication.shared.open(url)
        }
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

    var summary: String {
        if let dailyReport {
            return dailyReport.abstractPreview
        }

        let digestSummary = digestItems.prefix(2).map { $0.summaryPreview }.joined(separator: " ")
        if !digestSummary.isEmpty {
            return trimmed(digestSummary, limit: 260)
        }

        if let firstPost = posts.first {
            return trimmed("The feed for this day is led by \(firstPost.displayTitle). \(posts.count) source articles and \(timelineEvents.count) timeline signals are currently attached to this briefing day.", limit: 260)
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

        return trimmed("\(opener) \(summary)", limit: 300)
    }

    var topLines: [String] {
        if let dailyReport, !dailyReport.keyItems.isEmpty {
            return Array(dailyReport.keyItems.prefix(3))
        }

        let digestTitles = digestItems.map { $0.title }
        if !digestTitles.isEmpty {
            return Array(digestTitles.prefix(3))
        }

        let postTitles = posts.map { $0.displayTitle }
        if !postTitles.isEmpty {
            return Array(postTitles.prefix(3))
        }

        return Array(timelineEvents.map { $0.title }.prefix(3))
    }

    var topCategories: [String] {
        Array(posts.flatMap { $0.categories }.uniquePreservingOrder().prefix(8))
    }

    var prominentDocuments: [BriefingDocument] {
        var items: [BriefingDocument] = []

        if let dailyReport {
            items.append(.report(dailyReport))
        } else if let firstReport = reports.first {
            items.append(.report(firstReport))
        }

        let primaryPostCount = items.isEmpty ? 2 : 1
        items.append(contentsOf: posts.prefix(primaryPostCount).map { .post($0) })
        return items
    }

    var relatedPosts: [Post] {
        let consumed = Set(prominentDocuments.compactMap { document in
            switch document {
            case .post(let post):
                return post.id
            case .report:
                return nil
            }
        })

        return posts.filter { !consumed.contains($0.id) }
    }

    private func trimmed(_ text: String, limit: Int) -> String {
        guard text.count > limit else { return text }
        return String(text.prefix(limit - 1)) + "…"
    }
}

private enum BriefingDocument: Identifiable, Hashable {
    case report(Report)
    case post(Post)

    var id: String {
        switch self {
        case .report(let report):
            return "report-\(report.id)"
        case .post(let post):
            return "post-\(post.id)"
        }
    }

    var title: String {
        switch self {
        case .report(let report):
            return report.displayTitle
        case .post(let post):
            return post.displayTitle
        }
    }

    var subtitle: String {
        switch self {
        case .report(let report):
            return report.abstractPreview
        case .post(let post):
            return post.summaryPreview
        }
    }

    var kicker: String {
        switch self {
        case .report(let report):
            return report.typeLabel
        case .post(let post):
            return post.source
        }
    }

    var accent: Color {
        switch self {
        case .report(let report):
            return report.tags.contains("weekly") ? AppTheme.coral : AppTheme.cobalt
        case .post(let post):
            return AppTheme.accent(for: post.source)
        }
    }
}

private struct BriefingDocumentCard: View {
    let document: BriefingDocument

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(document.kicker.uppercased())
                .font(.caption.weight(.bold))
                .foregroundStyle(document.accent)

            Text(document.title)
                .font(.headline.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(document.subtitle)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 26, tint: document.accent, padding: 16)
    }
}

private struct BriefingRelatedPostCard: View {
    let post: Post

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(post.source.uppercased())
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.accent(for: post.source))

            if let reference = post.reference {
                Text(reference)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(AppTheme.plumSoft)
            }

            Text(post.displayTitle)
                .font(.headline.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)
                .frame(maxWidth: .infinity, alignment: .leading)

            if post.hasDistinctOriginalTitle {
                Text(post.originalTitleDisplay)
                    .font(.caption)
                    .foregroundStyle(AppTheme.plumSoft)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            Text(post.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 24, tint: AppTheme.mint, padding: 16)
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
            .navigationTitle("Related documents")
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
                        .foregroundStyle(AppTheme.pageTitle)

                    Text("These are the strongest topic labels attached to the selected day so far.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageSubtext)

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

private struct EditorialDocumentCard: View {
    let document: EditorialDocument
    var accent: Color? = nil

    private var tint: Color {
        accent ?? AppTheme.accent(for: document.source + document.kind)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(document.sourceLabel.uppercased())
                        .font(.caption.weight(.bold))
                        .foregroundStyle(tint)

                    Text(document.title)
                        .font(.headline.weight(.semibold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.ink)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }

                if document.destinationURL != nil {
                    Image(systemName: "arrow.up.right")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.heroSubtext)
                }
            }

            HStack(spacing: 10) {
                Text(document.kind.uppercased())
                Text(document.displayDateText)
            }
            .font(.caption.weight(.semibold))
            .foregroundStyle(AppTheme.heroSubtext)

            Text(document.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)
                .lineLimit(4)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 26, tint: tint, padding: 16)
    }
}

private struct EditorialDocumentsSheet: View {
    let title: String
    let subtitle: String
    let documents: [EditorialDocument]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageSubtext)

                    if documents.isEmpty {
                        ContentUnavailableView(
                            "No linked documents",
                            systemImage: "doc.text",
                            description: Text("This editorial entry does not currently expose additional linked documents.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 40)
                    } else {
                        ForEach(documents) { document in
                            Link(destination: document.destinationURL ?? URL(string: "https://danieltnl.github.io/EURLex/")!) {
                                EditorialDocumentCard(document: document)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(20)
                .padding(.bottom, 20)
            }
            .navigationTitle(title)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct EditorialTextBlock: View {
    let text: String

    private var paragraphs: [String] {
        let rawParagraphs = text
            .split(separator: "\n", omittingEmptySubsequences: true)
            .map { TextSanitizer.clean(String($0)) }
            .filter { !$0.isEmpty }

        if rawParagraphs.count > 1 {
            return rawParagraphs
        }

        let compact = TextSanitizer.clean(text)
        guard compact.count > 260 else { return compact.isEmpty ? [] : [compact] }

        let sentences = compact.split(whereSeparator: { ".!?".contains($0) }).map { TextSanitizer.clean(String($0)) }.filter { !$0.isEmpty }
        guard !sentences.isEmpty else { return [compact] }

        var paragraphs: [String] = []
        var current = ""

        for sentence in sentences {
            let candidate = current.isEmpty ? sentence : "\(current). \(sentence)"
            if candidate.count > 240, !current.isEmpty {
                paragraphs.append(current + ".")
                current = sentence
            } else {
                current = candidate
            }
        }

        if !current.isEmpty {
            paragraphs.append(current + ".")
        }

        return paragraphs
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(Array(paragraphs.enumerated()), id: \.offset) { _, paragraph in
                Text(paragraph)
                    .font(.body)
                    .foregroundStyle(AppTheme.ink)
                    .lineSpacing(6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

private struct EditorialSectionCard: View {
    let section: EditorialSection
    var tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(section.title)
                .font(.title3.weight(.semibold))
                .fontDesign(.serif)
                .foregroundStyle(AppTheme.ink)

            EditorialTextBlock(text: section.body)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 28, tint: tint, padding: 18)
    }
}

private struct BriefingReaderView: View {
    let briefing: DailyBriefingEntry

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(briefing.title.uppercased())
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.cobalt)

                    Text(briefing.headline)
                        .font(.largeTitle.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.pageTitle)

                    Text(briefing.displayDateText)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageBody)
                }

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Introduction", subtitle: "A tighter editorial opener for the day.")
                    EditorialTextBlock(text: briefing.intro)
                }
                .dossierCard()

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Full brief", subtitle: "Detailed but mobile-readable analysis across the day’s material.")
                    EditorialTextBlock(text: briefing.summary)
                }
                .dossierCard()

                if !briefing.keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionTitle(title: "Key points", subtitle: nil)
                        ForEach(Array(briefing.keyPoints.enumerated()), id: \.offset) { _, item in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(AppTheme.cobalt)
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 6)
                                Text(item)
                                    .font(.body)
                                    .foregroundStyle(AppTheme.ink)
                            }
                        }
                    }
                    .dossierCard()
                }

                if !briefing.sections.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(title: "Structured reading", subtitle: "The core arguments, broken into readable sections.")
                        ForEach(briefing.sections) { section in
                            EditorialSectionCard(section: section, tint: AppTheme.cobalt)
                        }
                    }
                }

                if !briefing.importantDocuments.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(title: "Source documents", subtitle: "Original titles and links, kept close for lookup and verification.")
                        ForEach(briefing.importantDocuments) { document in
                            Link(destination: document.destinationURL ?? URL(string: "https://danieltnl.github.io/EURLex/")!) {
                                EditorialDocumentCard(document: document)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                if !briefing.relatedDocuments.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(title: "Related reading", subtitle: nil)
                        ForEach(briefing.relatedDocuments.prefix(3)) { document in
                            Link(destination: document.destinationURL ?? URL(string: "https://danieltnl.github.io/EURLex/")!) {
                                EditorialDocumentCard(document: document, accent: AppTheme.mint)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(20)
            .padding(.bottom, 120)
        }
        .navigationTitle("Daily Brief")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private struct SundayEditionReaderView: View {
    let edition: SundayEditionEntry

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("SUNDAY EDITION")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.lavender)

                    Text(edition.headline)
                        .font(.largeTitle.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.pageTitle)

                    Text(edition.displayWeekRange)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageBody)
                }

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Front page", subtitle: "The opening argument for the week.")
                    EditorialTextBlock(text: edition.intro)
                }
                .dossierCard()

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Weekly overview", subtitle: "A longer-form synthesis of the week’s publications.")
                    EditorialTextBlock(text: edition.summary)
                }
                .dossierCard()

                if !edition.keyPoints.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionTitle(title: "Key points", subtitle: nil)
                        ForEach(Array(edition.keyPoints.enumerated()), id: \.offset) { _, item in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(AppTheme.lavender)
                                    .frame(width: 8, height: 8)
                                    .padding(.top, 6)
                                Text(item)
                                    .font(.body)
                                    .foregroundStyle(AppTheme.ink)
                            }
                        }
                    }
                    .dossierCard()
                }

                if !edition.sections.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(title: "Sections", subtitle: "A cleaner newspaper-style structure for the weekly read.")
                        ForEach(edition.sections) { section in
                            EditorialSectionCard(section: section, tint: AppTheme.lavender)
                        }
                    }
                }

                if !edition.importantDocuments.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionTitle(title: "Source documents", subtitle: "Original titles and links behind the weekly edition.")
                        ForEach(edition.importantDocuments) { document in
                            Link(destination: document.destinationURL ?? URL(string: "https://danieltnl.github.io/EURLex/")!) {
                                EditorialDocumentCard(document: document, accent: AppTheme.lavender)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(20)
            .padding(.bottom, 120)
        }
        .navigationTitle("Sunday Edition")
        .navigationBarTitleDisplayMode(.inline)
    }
}
