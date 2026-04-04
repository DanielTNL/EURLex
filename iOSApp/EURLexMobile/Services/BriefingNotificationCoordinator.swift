import Foundation
import UserNotifications

actor BriefingNotificationCoordinator {
    static let shared = BriefingNotificationCoordinator()

    private let center = UNUserNotificationCenter.current()
    private let defaults = UserDefaults.standard

    private let authSeedKey = "eurlex.notifications.auth.seeded"
    private let dailyKey = "eurlex.notifications.lastDailyBriefing"
    private let sundayKey = "eurlex.notifications.lastSundayEdition"

    func requestAuthorizationIfNeeded() async {
        let status = await center.notificationSettings().authorizationStatus
        guard status == .notDetermined else { return }

        do {
            let granted = try await center.requestAuthorization(options: [.alert, .badge, .sound])
            if granted, !defaults.bool(forKey: authSeedKey) {
                defaults.set(true, forKey: authSeedKey)
            }
        } catch {
            return
        }
    }

    func process(
        latestBriefing: DailyBriefingEntry?,
        latestSundayEdition: SundayEditionEntry?
    ) async {
        await handleDailyBriefing(latestBriefing)
        await handleSundayEdition(latestSundayEdition)
    }

    private func handleDailyBriefing(_ briefing: DailyBriefingEntry?) async {
        guard let briefing else { return }
        let key = briefing.id
        let stored = defaults.string(forKey: dailyKey)

        guard let stored else {
            defaults.set(key, forKey: dailyKey)
            return
        }

        guard stored != key else { return }
        defaults.set(key, forKey: dailyKey)

        let content = UNMutableNotificationContent()
        content.title = "Daily Brief Ready"
        content.body = briefing.headline
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "eurlex.daily.\(key)",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )

        try? await center.add(request)
    }

    private func handleSundayEdition(_ edition: SundayEditionEntry?) async {
        guard let edition else { return }
        let key = edition.id
        let stored = defaults.string(forKey: sundayKey)

        guard let stored else {
            defaults.set(key, forKey: sundayKey)
            return
        }

        guard stored != key else { return }
        defaults.set(key, forKey: sundayKey)

        let content = UNMutableNotificationContent()
        content.title = "Sunday Edition Ready"
        content.body = edition.headline
        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "eurlex.sunday.\(key)",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 1, repeats: false)
        )

        try? await center.add(request)
    }
}
