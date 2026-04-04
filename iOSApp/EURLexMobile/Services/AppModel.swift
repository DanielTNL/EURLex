import Combine
import Foundation

enum AppLoadState: Equatable {
    case idle
    case loading
    case loaded(Date)
    case failed(String)
}

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var loadState: AppLoadState = .idle
    @Published private(set) var posts: [Post] = []
    @Published private(set) var reports: [Report] = []
    @Published private(set) var audio: AudioPayload = .empty
    @Published private(set) var timeline: TimelinePayload = .empty
    @Published private(set) var digest: DailyDigest?
    @Published private(set) var briefings: DailyBriefingPayload = .empty
    @Published private(set) var sundayEditions: SundayEditionPayload = .empty
    @Published private(set) var library: LibraryPayload = .empty

    private let client: EURLexAPIClient
    private let notifications: BriefingNotificationCoordinator

    init(
        client: EURLexAPIClient = .live,
        notifications: BriefingNotificationCoordinator = .shared
    ) {
        self.client = client
        self.notifications = notifications
        if let cachedSnapshot = client.cachedSnapshot() {
            apply(snapshot: cachedSnapshot)
        }
    }

    var shouldLoad: Bool {
        if case .idle = loadState { return true }
        return false
    }

    var isLoading: Bool {
        if case .loading = loadState { return true }
        return false
    }

    var hasContent: Bool {
        !posts.isEmpty || !reports.isEmpty || !audio.items.isEmpty || digest != nil || !briefings.items.isEmpty || !library.items.isEmpty
    }

    var availableSources: [String] {
        Set(posts.map(\.source)).sorted()
    }

    var availableCategories: [String] {
        Set(posts.flatMap(\.categories)).sorted()
    }

    var featuredPosts: [Post] {
        Array(posts.prefix(6))
    }

    var featuredReports: [Report] {
        Array(reports.prefix(4))
    }

    var featuredTimelineEvents: [TimelineEvent] {
        Array(timeline.events.prefix(4))
    }

    var digestItems: [DigestItem] {
        Array((digest?.items ?? []).prefix(5))
    }

    var dailyDigestCount: Int {
        digest?.items.count ?? 0
    }

    var latestSyncText: String {
        switch loadState {
        case .idle:
            return "Waiting to sync"
        case .loading:
            return "Refreshing live feeds"
        case .loaded(let date):
            return EURLexDate.medium(digest?.generatedDate ?? date)
        case .failed(let message):
            return message
        }
    }

    var latestBriefing: DailyBriefingEntry? {
        briefings.items.first
    }

    var latestSundayEdition: SundayEditionEntry? {
        sundayEditions.items.first
    }

    var libraryDocuments: [LibraryDocument] {
        library.items
    }

    func briefing(for date: Date) -> DailyBriefingEntry? {
        briefings.items.first { entry in
            guard let briefingDate = entry.briefingDate else { return false }
            return Calendar.autoupdatingCurrent.isDate(briefingDate, inSameDayAs: date)
        }
    }

    func prepareNotifications() async {
        await notifications.requestAuthorizationIfNeeded()
    }

    func reload() async {
        guard !isLoading else { return }
        loadState = .loading

        do {
            let snapshot = try await client.fetchSnapshot()
            apply(snapshot: snapshot)
            await notifications.process(
                latestBriefing: latestBriefing,
                latestSundayEdition: latestSundayEdition
            )
            loadState = .loaded(Date())
        } catch is CancellationError {
            return
        } catch {
            loadState = .failed(error.localizedDescription)
        }
    }

    private func apply(snapshot: AppSnapshot) {
        posts = Self.unique(snapshot.posts, using: \.dedupeKey)
            .sorted { $0.sortDate > $1.sortDate }
        reports = Self.unique(snapshot.reports, using: \.dedupeKey)
            .sorted { $0.sortDate > $1.sortDate }
        let sortedAudioItems = Self.unique(snapshot.audio.items, using: \.dedupeKey)
            .sorted { EURLexDate.parse($0.date) ?? .distantPast > EURLexDate.parse($1.date) ?? .distantPast }
        audio = AudioPayload(
            googleDrive: snapshot.audio.googleDrive,
            monthly: Self.unique(snapshot.audio.monthly, using: \.dedupeKey)
                .sorted { EURLexDate.parse($0.date) ?? .distantPast > EURLexDate.parse($1.date) ?? .distantPast },
            requests: Self.unique(snapshot.audio.requests, using: \.dedupeKey)
                .sorted { EURLexDate.parse($0.date) ?? .distantPast > EURLexDate.parse($1.date) ?? .distantPast },
            items: sortedAudioItems
        )
        timeline = TimelinePayload(
            window: snapshot.timeline.window,
            events: Self.unique(snapshot.timeline.events, using: \.dedupeKey)
                .sorted { EURLexDate.parse($0.date) ?? .distantPast > EURLexDate.parse($1.date) ?? .distantPast }
        )
        digest = snapshot.digest.deduped()
        briefings = DailyBriefingPayload(
            generatedAt: snapshot.briefings.generatedAt,
            latestDate: snapshot.briefings.latestDate,
            items: snapshot.briefings.items.sorted {
                EURLexDate.parse($0.date) ?? .distantPast > EURLexDate.parse($1.date) ?? .distantPast
            }
        )
        sundayEditions = SundayEditionPayload(
            generatedAt: snapshot.sundayEditions.generatedAt,
            latestEndDate: snapshot.sundayEditions.latestEndDate,
            items: snapshot.sundayEditions.items.sorted {
                EURLexDate.parse($0.weekEnd) ?? .distantPast > EURLexDate.parse($1.weekEnd) ?? .distantPast
            }
        )
        library = LibraryPayload(
            generatedAt: snapshot.library.generatedAt,
            count: snapshot.library.items.count,
            items: Self.unique(snapshot.library.items, using: \.dedupeKey)
                .sorted { EURLexDate.parse($0.updatedAt) ?? .distantPast > EURLexDate.parse($1.updatedAt) ?? .distantPast }
        )
    }

    private static func unique<T>(_ items: [T], using keyPath: KeyPath<T, String>) -> [T] {
        var seen = Set<String>()
        return items.filter { seen.insert($0[keyPath: keyPath]).inserted }
    }
}
