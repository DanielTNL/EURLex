import Foundation

extension Array where Element: Hashable {
    func uniquePreservingOrder() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}

enum EURLexDate {
    private static let isoParsers: [ISO8601DateFormatter] = {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        let internet = ISO8601DateFormatter()
        internet.formatOptions = [.withInternetDateTime]

        return [fractional, internet]
    }()

    private static let dayOnlyParser: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let shortFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter
    }()

    private static let detailedFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }()

    static func parse(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }

        for formatter in isoParsers {
            if let date = formatter.date(from: raw) {
                return date
            }
        }

        return dayOnlyParser.date(from: raw)
    }

    static func short(_ raw: String?) -> String {
        guard let date = parse(raw) else {
            return raw ?? "Unknown date"
        }
        return shortFormatter.string(from: date)
    }

    static func medium(_ date: Date?) -> String {
        guard let date else { return "Unknown time" }
        return detailedFormatter.string(from: date)
    }

    static func relative(_ raw: String?) -> String {
        guard let date = parse(raw) else {
            return "Unknown date"
        }
        return RelativeDateTimeFormatter().localizedString(for: date, relativeTo: Date())
    }
}

enum TextSanitizer {
    static func clean(_ text: String) -> String {
        let squashed = text
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)

        guard !squashed.isEmpty else { return "" }

        let replacementCount = squashed.filter { $0 == "\u{FFFD}" }.count
        let controlCount = squashed.unicodeScalars.filter {
            CharacterSet.controlCharacters.contains($0) && $0 != "\n" && $0 != "\t"
        }.count

        guard replacementCount == 0, controlCount == 0 else {
            return ""
        }

        return squashed
    }
}

enum PostReaderFormatter {
    static func reference(from title: String) -> String? {
        let cleaned = TextSanitizer.clean(title)
        guard !cleaned.isEmpty else { return nil }

        let patterns = [
            "(CELEX:[A-Z0-9()./_-]+)",
            "\\b(Case\\s+[A-Z]-\\d+/\\d+)\\b",
            "\\b(CON/\\d{4}/\\d+)\\b",
            "\\b(P\\d+_TA\\(\\d{4}\\)\\d+)\\b"
        ]

        for pattern in patterns {
            if let match = firstMatch(in: cleaned, pattern: pattern) {
                return match
            }
        }

        return nil
    }

    static func displayTitle(from original: String, summary: String) -> String {
        let fallback = TextSanitizer.clean(original)
        guard !fallback.isEmpty else { return "Untitled" }

        var cleaned = fallback
        cleaned = cleaned.replacingOccurrences(
            of: #"^This document is an excerpt from the EUR-Lex website\b[:\s-]*"#,
            with: "",
            options: .regularExpression
        )
        cleaned = cleaned.replacingOccurrences(
            of: #"^Document\s+[A-Z0-9:/()._-]+\s*"#,
            with: "",
            options: .regularExpression
        )

        if let range = cleaned.range(of: #"^(CELEX:[^:]+):\s*(.+)$"#, options: .regularExpression) {
            let full = String(cleaned[range])
            if let titlePart = captureGroup(in: full, pattern: #"^(CELEX:[^:]+):\s*(.+)$"#, group: 2) {
                cleaned = titlePart
            }
        }

        if cleaned.isEmpty || cleaned.lowercased().hasPrefix("this document is an excerpt from the eur-lex website") {
            cleaned = derivedTitle(from: summary) ?? fallback
        }

        cleaned = cleaned
            .replacingOccurrences(of: ".#", with: ": ")
            .replacingOccurrences(of: #"\s*#\s*"#, with: " ", options: .regularExpression)
            .replacingOccurrences(of: #"\b(?:ELI:|Official Journal|Language of the case:)\b.*$"#, with: "", options: .regularExpression)

        cleaned = TextSanitizer.clean(cleaned)
        return cleaned.isEmpty ? fallback : cleaned.trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-"))
    }

    static func displaySummary(from summary: String, title: String) -> String {
        var cleaned = TextSanitizer.clean(summary)
        guard !cleaned.isEmpty else { return "" }

        cleaned = cleaned.replacingOccurrences(
            of: #"^This document is an excerpt from the EUR-Lex website\b[:\s-]*"#,
            with: "",
            options: .regularExpression
        )
        cleaned = cleaned.replacingOccurrences(
            of: #"^Document\s+[A-Z0-9:/()._-]+\s*"#,
            with: "",
            options: .regularExpression
        )
        cleaned = collapseRepeatedSentences(in: cleaned)
        cleaned = trimAfterRepeatedLead(in: cleaned)
        cleaned = trimAfterRepeatedReference(in: cleaned)
        cleaned = cleaned.replacingOccurrences(
            of: #"\b(?:ELI:|Official Journal|Language of the case:|OJ\s+[A-Z],)\b.*$"#,
            with: "",
            options: .regularExpression
        )

        let readableTitle = displayTitle(from: title, summary: summary)
        if cleaned.lowercased().hasPrefix(readableTitle.lowercased() + " ") {
            cleaned.removeFirst(readableTitle.count)
        }

        cleaned = TextSanitizer.clean(cleaned).trimmingCharacters(in: CharacterSet(charactersIn: " .:-"))
        return cleaned
    }

    private static func derivedTitle(from summary: String) -> String? {
        var cleaned = TextSanitizer.clean(summary)
        guard !cleaned.isEmpty else { return nil }

        cleaned = cleaned.replacingOccurrences(
            of: #"^This document is an excerpt from the EUR-Lex website\b[:\s-]*"#,
            with: "",
            options: .regularExpression
        )
        cleaned = cleaned.replacingOccurrences(
            of: #"^Document\s+[A-Z0-9:/()._-]+\s*"#,
            with: "",
            options: .regularExpression
        )
        cleaned = collapseRepeatedSentences(in: cleaned)
        cleaned = trimAfterRepeatedLead(in: cleaned)
        cleaned = trimAfterRepeatedReference(in: cleaned)
        cleaned = cleaned.replacingOccurrences(
            of: #"\b(?:ELI:|Official Journal|Language of the case:|OJ\s+[A-Z],)\b.*$"#,
            with: "",
            options: .regularExpression
        )

        let firstSentence = splitSentences(in: cleaned).first ?? cleaned
        let trimmed = TextSanitizer.clean(firstSentence)
        guard !trimmed.isEmpty else { return nil }
        return String(trimmed.prefix(220)).trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-"))
    }

    private static func collapseRepeatedSentences(in text: String) -> String {
        let sentences = splitSentences(in: text)
            .map(TextSanitizer.clean)
            .filter { !$0.isEmpty }

        var seen = Set<String>()
        var kept: [String] = []

        for sentence in sentences {
            let fingerprint = sentence
                .lowercased()
                .replacingOccurrences(of: #"[^a-z0-9]+"#, with: "", options: .regularExpression)

            if fingerprint.count > 24, seen.contains(fingerprint) {
                continue
            }

            kept.append(sentence)
            if fingerprint.count > 24 {
                seen.insert(fingerprint)
            }
        }

        return kept.joined(separator: " ")
    }

    private static func splitSentences(in text: String) -> [String] {
        let pieces = text.split(whereSeparator: { ".!?".contains($0) })
        if pieces.isEmpty {
            return [text]
        }
        return pieces.map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
    }

    private static func trimAfterRepeatedLead(in text: String, minLength: Int = 80) -> String {
        let compact = TextSanitizer.clean(text)
        guard compact.count >= minLength * 2 else { return compact }

        let maxLength = min(180, compact.count / 2)
        guard maxLength >= minLength else { return compact }

        for size in stride(from: maxLength, through: minLength, by: -10) {
            let lead = String(compact.prefix(size)).trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-"))
            guard lead.count >= minLength else { continue }
            let searchStart = compact.index(compact.startIndex, offsetBy: size)
            if let range = compact.range(of: lead, options: [], range: searchStart..<compact.endIndex) {
                return String(compact[..<range.lowerBound]).trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-"))
            }
        }

        return compact
    }

    private static func trimAfterRepeatedReference(in text: String) -> String {
        let compact = TextSanitizer.clean(text)
        let pattern = #"^((?:Case\s+[A-Z]-\d+/\d+|P\d+_TA\(\d{4}\)\d+|CELEX:[A-Z0-9()./_-]+|OJ:[A-Z]_[A-Z0-9]+))"#
        guard let token = firstMatch(in: compact, pattern: pattern), !token.isEmpty else {
            return compact
        }
        let searchStart = compact.index(compact.startIndex, offsetBy: token.count)
        if let range = compact.range(of: token, options: [], range: searchStart..<compact.endIndex) {
            return String(compact[..<range.lowerBound]).trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-"))
        }
        return compact
    }

    private static func firstMatch(in text: String, pattern: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return nil
        }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, options: [], range: range), let captureRange = Range(match.range(at: 1), in: text) else {
            return nil
        }
        return String(text[captureRange])
    }

    private static func captureGroup(in text: String, pattern: String, group: Int) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return nil
        }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, options: [], range: range), let captureRange = Range(match.range(at: group), in: text) else {
            return nil
        }
        return String(text[captureRange]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

struct Post: Decodable, Identifiable, Hashable {
    let id: String
    let source: String
    let url: String
    let title: String
    let originalTitle: String
    private let displayTitleValue: String?
    let tags: [String]
    let added: String?
    let summary: String
    private let displaySummaryValue: String?
    let reference: String?
    let categories: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case source
        case url
        case title
        case originalTitle = "original_title"
        case displayTitleValue = "display_title"
        case tags
        case added
        case summary
        case displaySummaryValue = "display_summary"
        case reference
        case categories
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        source = try container.decodeIfPresent(String.self, forKey: .source) ?? "Unknown Source"
        url = try container.decodeIfPresent(String.self, forKey: .url) ?? ""
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled"
        originalTitle = try container.decodeIfPresent(String.self, forKey: .originalTitle) ?? title
        displayTitleValue = try container.decodeIfPresent(String.self, forKey: .displayTitleValue)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        added = try container.decodeIfPresent(String.self, forKey: .added)
        summary = try container.decodeIfPresent(String.self, forKey: .summary) ?? ""
        displaySummaryValue = try container.decodeIfPresent(String.self, forKey: .displaySummaryValue)
        reference = try container.decodeIfPresent(String.self, forKey: .reference) ?? PostReaderFormatter.reference(from: originalTitle)
        categories = try container.decodeIfPresent([String].self, forKey: .categories) ?? []
    }

    var destinationURL: URL? { URL(string: url) }
    var addedDate: Date? { EURLexDate.parse(added) }
    var sortDate: Date { addedDate ?? .distantPast }
    var displayDateText: String { EURLexDate.short(added) }
    var relativeDateText: String { EURLexDate.relative(added) }
    var displayTitle: String {
        let cleaned = TextSanitizer.clean(displayTitleValue ?? "")
        return cleaned.isEmpty ? PostReaderFormatter.displayTitle(from: originalTitle, summary: summary) : cleaned
    }
    var originalTitleDisplay: String {
        let cleaned = TextSanitizer.clean(originalTitle)
        return cleaned.isEmpty ? title : cleaned
    }
    var displaySummary: String {
        let cleaned = TextSanitizer.clean(displaySummaryValue ?? "")
        return cleaned.isEmpty ? PostReaderFormatter.displaySummary(from: summary, title: originalTitleDisplay) : cleaned
    }
    var summaryPreview: String {
        let cleaned = TextSanitizer.clean(displaySummary)
        return cleaned.isEmpty ? "No summary is available in the published feed yet." : cleaned
    }
    var hasDistinctOriginalTitle: Bool {
        normalizedComparable(displayTitle) != normalizedComparable(originalTitleDisplay)
    }
    var primaryTags: [String] { Array((categories + tags).uniquePreservingOrder().prefix(5)) }
    var dedupeKey: String { [id, url.lowercased(), title.lowercased()].joined(separator: "|") }

    private func normalizedComparable(_ text: String) -> String {
        TextSanitizer.clean(text)
            .lowercased()
            .replacingOccurrences(of: #"[^a-z0-9]+"#, with: "", options: .regularExpression)
    }
}

struct Report: Decodable, Identifiable, Hashable {
    let id: String
    let date: String
    let title: String
    let originalTitle: String
    private let displayTitleValue: String?
    let urlHtml: String
    let urlDrive: String
    let tags: [String]
    let keyItems: [String]
    let abstract: String

    enum CodingKeys: String, CodingKey {
        case id
        case date
        case title
        case originalTitle = "original_title"
        case displayTitleValue = "display_title"
        case urlHtml
        case urlDrive
        case tags
        case keyItems
        case abstract
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        date = try container.decodeIfPresent(String.self, forKey: .date) ?? ""
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled report"
        originalTitle = try container.decodeIfPresent(String.self, forKey: .originalTitle) ?? title
        displayTitleValue = try container.decodeIfPresent(String.self, forKey: .displayTitleValue)
        urlHtml = try container.decodeIfPresent(String.self, forKey: .urlHtml) ?? ""
        urlDrive = try container.decodeIfPresent(String.self, forKey: .urlDrive) ?? ""
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        keyItems = try container.decodeIfPresent([String].self, forKey: .keyItems) ?? []
        abstract = try container.decodeIfPresent(String.self, forKey: .abstract) ?? ""
    }

    var htmlURL: URL? { URL(string: urlHtml) }
    var driveURL: URL? { URL(string: urlDrive) }
    var rawContentURL: URL? {
        guard let url = htmlURL else { return nil }

        guard
            url.host == "github.com",
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        else {
            return url
        }

        let pathComponents = components.path.split(separator: "/").map(String.init)
        guard pathComponents.count >= 5, pathComponents[2] == "blob" else {
            return url
        }

        let owner = pathComponents[0]
        let repository = pathComponents[1]
        let branch = pathComponents[3]
        let remainder = pathComponents.dropFirst(4).joined(separator: "/")
        return URL(string: "https://raw.githubusercontent.com/\(owner)/\(repository)/\(branch)/\(remainder)")
    }
    var reportDate: Date? { EURLexDate.parse(date) }
    var sortDate: Date { reportDate ?? .distantPast }
    var displayDateText: String { EURLexDate.short(date) }
    var displayTitle: String {
        let cleaned = TextSanitizer.clean(displayTitleValue ?? "")
        if !cleaned.isEmpty { return cleaned }
        return title.replacingOccurrences(of: #"^#+\s*"#, with: "", options: .regularExpression)
    }
    var abstractPreview: String {
        let cleaned = TextSanitizer.clean(abstract)
        return cleaned.isEmpty ? "No abstract was published for this report." : cleaned
    }
    var typeLabel: String {
        if tags.contains("weekly") { return "Weekly" }
        if tags.contains("daily") { return "Daily" }
        return "Report"
    }
    func preparedBody(from rawText: String) -> String {
        var lines = rawText
            .replacingOccurrences(of: "\r\n", with: "\n")
            .components(separatedBy: .newlines)

        while let first = lines.first, first.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.removeFirst()
        }

        if let first = lines.first {
            let normalizedFirst = first.replacingOccurrences(of: #"^#+\s*"#, with: "", options: .regularExpression)
            if normalizedFirst == displayTitle {
                lines.removeFirst()
            }
        }

        while let first = lines.first, first.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            lines.removeFirst()
        }

        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }
    var dedupeKey: String { [id, title.lowercased(), date].joined(separator: "|") }
}

struct EditorialDocument: Decodable, Identifiable, Hashable {
    let id: String
    let title: String
    let summary: String
    let url: String
    let kind: String
    let source: String
    let date: String
    let categories: [String]
    let tags: [String]

    var destinationURL: URL? { URL(string: url) }
    var displayDateText: String { EURLexDate.short(date) }
    var summaryPreview: String {
        let cleaned = TextSanitizer.clean(summary)
        return cleaned.isEmpty ? "No summary is available for this source yet." : cleaned
    }
    var sourceLabel: String {
        let cleaned = TextSanitizer.clean(source)
        return cleaned.isEmpty ? "Source" : cleaned
    }
}

struct EditorialSection: Decodable, Identifiable, Hashable {
    let title: String
    let body: String

    var id: String { [title, body].joined(separator: "|") }
}

struct BriefingSignalCounts: Decodable, Hashable {
    let posts: Int
    let reports: Int
    let digestItems: Int
    let timelineEvents: Int

    static let empty = BriefingSignalCounts(posts: 0, reports: 0, digestItems: 0, timelineEvents: 0)
}

struct BriefingReportLink: Decodable, Hashable {
    let id: String?
    let title: String?
    let url: String?

    var destinationURL: URL? {
        guard let url else { return nil }
        return URL(string: url)
    }
}

struct DailyBriefingEntry: Decodable, Identifiable, Hashable {
    let date: String
    let title: String
    let headline: String
    let intro: String
    let summary: String
    let keyPoints: [String]
    let sections: [EditorialSection]
    let categories: [String]
    let importantDocuments: [EditorialDocument]
    let relatedDocuments: [EditorialDocument]
    let report: BriefingReportLink?
    let signalCounts: BriefingSignalCounts

    var id: String { date }
    var briefingDate: Date? { EURLexDate.parse(date) }
    var displayDateText: String { EURLexDate.short(date) }
}

struct DailyBriefingPayload: Decodable, Hashable {
    let generatedAt: String
    let latestDate: String
    let items: [DailyBriefingEntry]

    static let empty = DailyBriefingPayload(generatedAt: "", latestDate: "", items: [])
}

struct SundayEditionEntry: Decodable, Identifiable, Hashable {
    let editionDate: String
    let weekStart: String
    let weekEnd: String
    let title: String
    let headline: String
    let intro: String
    let summary: String
    let keyPoints: [String]
    let sections: [EditorialSection]
    let categories: [String]
    let importantDocuments: [EditorialDocument]
    let relatedDocuments: [EditorialDocument]
    let report: BriefingReportLink?

    var id: String { weekEnd.isEmpty ? editionDate : weekEnd }
    var displayDateText: String { EURLexDate.short(editionDate) }
    var displayWeekRange: String {
        "\(EURLexDate.short(weekStart)) to \(EURLexDate.short(weekEnd))"
    }
}

struct SundayEditionPayload: Decodable, Hashable {
    let generatedAt: String
    let latestEndDate: String
    let items: [SundayEditionEntry]

    static let empty = SundayEditionPayload(generatedAt: "", latestEndDate: "", items: [])
}

struct AudioPayload: Decodable, Hashable {
    let googleDrive: String
    let monthly: [AudioItem]
    let requests: [AudioItem]
    let items: [AudioItem]

    static let empty = AudioPayload(googleDrive: "", monthly: [], requests: [], items: [])

    enum CodingKeys: String, CodingKey {
        case googleDrive
        case monthly
        case requests
        case items
    }

    init(googleDrive: String, monthly: [AudioItem], requests: [AudioItem], items: [AudioItem]) {
        self.googleDrive = googleDrive
        self.monthly = monthly
        self.requests = requests
        self.items = items
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        googleDrive = try container.decodeIfPresent(String.self, forKey: .googleDrive) ?? ""
        monthly = try container.decodeIfPresent([AudioItem].self, forKey: .monthly) ?? []
        requests = try container.decodeIfPresent([AudioItem].self, forKey: .requests) ?? []
        items = try container.decodeIfPresent([AudioItem].self, forKey: .items) ?? []
    }

    var driveURL: URL? { URL(string: googleDrive) }
}

struct AudioItem: Decodable, Identifiable, Hashable {
    let title: String
    let path: String
    let rawUrl: String
    let date: String
    let kind: String
    let series: String
    let requested: Bool
    let summary: String

    var id: String { dedupeKey }

    enum CodingKeys: String, CodingKey {
        case title
        case path
        case rawUrl
        case date
        case kind
        case series
        case requested
        case summary
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled audio"
        path = try container.decodeIfPresent(String.self, forKey: .path) ?? ""
        rawUrl = try container.decodeIfPresent(String.self, forKey: .rawUrl) ?? ""
        date = try container.decodeIfPresent(String.self, forKey: .date) ?? ""
        kind = try container.decodeIfPresent(String.self, forKey: .kind) ?? "audio_brief"
        series = try container.decodeIfPresent(String.self, forKey: .series) ?? "Audio brief"
        requested = try container.decodeIfPresent(Bool.self, forKey: .requested) ?? false
        summary = try container.decodeIfPresent(String.self, forKey: .summary) ?? ""
    }

    var playbackURL: URL? { URL(string: rawUrl) }
    var displayDateText: String { EURLexDate.short(date) }
    var summaryPreview: String {
        let cleaned = TextSanitizer.clean(summary)
        return cleaned.isEmpty ? "No overview text is available for this audio item yet." : cleaned
    }
    var displayTitle: String {
        title
            .replacingOccurrences(of: " roundtable", with: "", options: .caseInsensitive)
            .replacingOccurrences(of: " weekly request", with: "", options: .caseInsensitive)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
    var dedupeKey: String { [title.lowercased(), rawUrl.lowercased()].joined(separator: "|") }
}

struct TimelinePayload: Decodable, Hashable {
    let window: TimelineWindow
    let events: [TimelineEvent]

    static let empty = TimelinePayload(
        window: TimelineWindow(start: "", end: "", timezone: "Europe/Amsterdam"),
        events: []
    )

    enum CodingKeys: String, CodingKey {
        case window
        case events
    }

    init(window: TimelineWindow, events: [TimelineEvent]) {
        self.window = window
        self.events = events
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        window = try container.decodeIfPresent(TimelineWindow.self, forKey: .window) ?? TimelineWindow(start: "", end: "", timezone: "Europe/Amsterdam")
        events = try container.decodeIfPresent([TimelineEvent].self, forKey: .events) ?? []
    }
}

struct TimelineWindow: Decodable, Hashable {
    let start: String
    let end: String
    let timezone: String
}

struct TimelineEvent: Decodable, Identifiable, Hashable {
    let date: String
    let title: String
    let url: String
    let docType: String
    let programme: [String]
    let techArea: [String]
    let stage: String
    let short: String

    var id: String { dedupeKey }

    enum CodingKeys: String, CodingKey {
        case date
        case title
        case url
        case docType
        case programme
        case techArea
        case stage
        case short
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        date = try container.decodeIfPresent(String.self, forKey: .date) ?? ""
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled event"
        url = try container.decodeIfPresent(String.self, forKey: .url) ?? ""
        docType = try container.decodeIfPresent(String.self, forKey: .docType) ?? ""
        programme = try container.decodeIfPresent([String].self, forKey: .programme) ?? []
        techArea = try container.decodeIfPresent([String].self, forKey: .techArea) ?? []
        stage = try container.decodeIfPresent(String.self, forKey: .stage) ?? ""
        short = try container.decodeIfPresent(String.self, forKey: .short) ?? ""
    }

    var destinationURL: URL? { URL(string: url) }
    var displayDateText: String { EURLexDate.short(date) }
    var summaryPreview: String {
        let cleaned = TextSanitizer.clean(short)
        return cleaned.isEmpty ? "No short summary was published for this timeline event." : cleaned
    }
    var dedupeKey: String { [url.lowercased(), title.lowercased(), date].joined(separator: "|") }
}

struct DailyDigest: Decodable, Hashable {
    let generatedAt: String
    let windowHours: Int
    let count: Int
    let items: [DigestItem]

    enum CodingKeys: String, CodingKey {
        case generatedAt
        case windowHours
        case count
        case items
    }

    init(generatedAt: String, windowHours: Int, count: Int, items: [DigestItem]) {
        self.generatedAt = generatedAt
        self.windowHours = windowHours
        self.count = count
        self.items = items
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt) ?? ""
        windowHours = try container.decodeIfPresent(Int.self, forKey: .windowHours) ?? 24
        count = try container.decodeIfPresent(Int.self, forKey: .count) ?? 0
        items = try container.decodeIfPresent([DigestItem].self, forKey: .items) ?? []
    }

    var generatedDate: Date? { EURLexDate.parse(generatedAt) }

    func deduped() -> DailyDigest {
        let uniqueItems = items.reduce(into: [DigestItem]()) { partial, item in
            if !partial.contains(where: { $0.dedupeKey == item.dedupeKey }) {
                partial.append(item)
            }
        }

        return DailyDigest(
            generatedAt: generatedAt,
            windowHours: windowHours,
            count: uniqueItems.count,
            items: uniqueItems
        )
    }
}

struct DigestItem: Decodable, Identifiable, Hashable {
    let title: String
    let url: String
    let sourceId: String
    let publishedDate: String?
    let docType: String
    let programme: [String]
    let financeInstrument: [String]
    let techArea: [String]
    let summary150w: String

    var id: String { dedupeKey }

    enum CodingKeys: String, CodingKey {
        case title
        case url
        case sourceId
        case publishedDate
        case docType
        case programme
        case financeInstrument
        case techArea
        case summary150w
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        title = try container.decodeIfPresent(String.self, forKey: .title) ?? "Untitled digest item"
        url = try container.decodeIfPresent(String.self, forKey: .url) ?? ""
        sourceId = try container.decodeIfPresent(String.self, forKey: .sourceId) ?? "unknown_source"
        publishedDate = try container.decodeIfPresent(String.self, forKey: .publishedDate)
        docType = try container.decodeIfPresent(String.self, forKey: .docType) ?? "Document"
        programme = try container.decodeIfPresent([String].self, forKey: .programme) ?? []
        financeInstrument = try container.decodeIfPresent([String].self, forKey: .financeInstrument) ?? []
        techArea = try container.decodeIfPresent([String].self, forKey: .techArea) ?? []
        summary150w = try container.decodeIfPresent(String.self, forKey: .summary150w) ?? ""
    }

    var destinationURL: URL? { URL(string: url) }
    var displayDateText: String { EURLexDate.short(publishedDate) }
    var summaryPreview: String {
        let cleaned = TextSanitizer.clean(summary150w)
        return cleaned.isEmpty ? "No clean summary was published for this digest item." : cleaned
    }
    var topicTags: [String] { Array((programme + financeInstrument + techArea).uniquePreservingOrder().prefix(4)) }
    var dedupeKey: String { [url.lowercased(), title.lowercased(), sourceId.lowercased()].joined(separator: "|") }
}
