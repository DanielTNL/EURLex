import Foundation

enum AppConfiguration {
    private static let publishedDataFallback = "https://danieltnl.github.io/EURLex/"

    static var publishedDataBaseURL: URL {
        if
            let configured = Bundle.main.object(forInfoDictionaryKey: "EURLexPublishedDataBaseURL") as? String,
            let url = normalizedURL(from: configured)
        {
            return url
        }

        return URL(string: publishedDataFallback)!
    }

    static var backendBaseURL: URL? {
        let configured = Bundle.main.object(forInfoDictionaryKey: "EURLexBackendBaseURL") as? String
        return normalizedURL(from: configured)
    }

    private static func normalizedURL(from raw: String?) -> URL? {
        guard let raw else { return nil }
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }

        let normalized = trimmed.hasSuffix("/") ? trimmed : trimmed + "/"
        return URL(string: normalized)
    }
}
