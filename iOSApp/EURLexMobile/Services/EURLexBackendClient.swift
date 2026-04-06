import Foundation

struct BackendChatMessage: Encodable {
    let role: String
    let content: String
}

struct BackendSearchResult: Decodable, Hashable {
    let title: String?
    let displayTitle: String?
    let source: String?
    let url: String?
    let date: String?

    var preferredTitle: String {
        let cleanedDisplay = TextSanitizer.clean(displayTitle ?? "")
        if !cleanedDisplay.isEmpty { return cleanedDisplay }

        let cleanedTitle = TextSanitizer.clean(title ?? "")
        return cleanedTitle.isEmpty ? "Untitled source" : cleanedTitle
    }
}

struct BackendChatResponse: Decodable {
    let answer: String?
    let results: [BackendSearchResult]
}

struct WeeklyAudioRequestResponse: Decodable {
    let ok: Bool?
    let message: String?
    let workflow: String?
}

struct ManagedSource: Decodable, Hashable, Identifiable {
    let id: String
    let sourceId: String?
    let name: String
    let url: String
    let tags: [String]
    let kind: String?
    let origin: String?
    let enabled: Bool?
    let addedAt: String?
    let updatedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case sourceId = "source_id"
        case name
        case url
        case tags
        case kind
        case origin
        case enabled
        case addedAt = "added_at"
        case updatedAt = "updated_at"
    }

    var isCustom: Bool { (origin ?? "").lowercased() == "custom" }
    var isEnabled: Bool { enabled ?? true }
    var displayOrigin: String { isCustom ? "Custom" : "Built-in" }
    var displayKind: String {
        switch (kind ?? "").lowercased() {
        case "rss", "feed", "atom":
            return "RSS"
        case "html", "html_list":
            return "HTML"
        default:
            return (kind?.isEmpty == false ? kind! : "Source").uppercased()
        }
    }
}

struct CustomFeedsResponse: Decodable {
    let updatedAt: String?
    let feeds: [ManagedSource]
    let sources: [ManagedSource]?
    let queuedProcessing: Bool?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case updatedAt = "updated_at"
        case feeds
        case sources
        case queuedProcessing = "queued_processing"
        case message
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
        feeds = try container.decodeIfPresent([ManagedSource].self, forKey: .feeds) ?? []
        sources = try container.decodeIfPresent([ManagedSource].self, forKey: .sources)
        queuedProcessing = try container.decodeIfPresent(Bool.self, forKey: .queuedProcessing)
        message = try container.decodeIfPresent(String.self, forKey: .message)
    }
}

enum EURLexBackendError: LocalizedError {
    case notConfigured
    case invalidURL(String)
    case badStatusCode(Int)
    case missingAnswer
    case uploadTooLarge(Int)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "The interactive backend is not configured yet."
        case .invalidURL(let path):
            return "Could not create a backend request URL for \(path)."
        case .badStatusCode(let code):
            return "The backend returned HTTP \(code)."
        case .missingAnswer:
            return "The backend responded, but did not include an answer."
        case .uploadTooLarge(let bytes):
            let mb = Double(bytes) / 1_000_000
            return String(format: "This file is too large for the current GitHub-backed upload route. Please keep uploads under %.1f MB for now.", mb)
        }
    }
}

struct EURLexBackendClient {
    static let safeUploadLimitBytes = 2_750_000

    let baseURL: URL?
    let session: URLSession

    static let live = EURLexBackendClient(
        baseURL: AppConfiguration.backendBaseURL,
        session: configuredSession
    )

    private static let configuredSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 25
        configuration.timeoutIntervalForResource = 40
        return URLSession(configuration: configuration)
    }()

    var isConfigured: Bool { baseURL != nil }

    func chat(messages: [BackendChatMessage], remote: Bool) async throws -> BackendChatResponse {
        let requestBody: [String: Any] = [
            "messages": messages.map { ["role": $0.role, "content": $0.content] },
            "top_k": 8,
            "remote": remote
        ]

        let data = try await sendJSON(path: "api/chat", method: "POST", body: requestBody)
        let decoder = configuredDecoder()
        return try decoder.decode(BackendChatResponse.self, from: data)
    }

    func requestWeeklyAudio(promptHint: String, endDate: String? = nil) async throws -> WeeklyAudioRequestResponse {
        var requestBody: [String: Any] = ["prompt_hint": promptHint]
        if let endDate, !endDate.isEmpty {
            requestBody["end_date"] = endDate
        }

        let data = try await sendJSON(path: "api/audio-request", method: "POST", body: requestBody)
        let decoder = configuredDecoder()
        return try decoder.decode(WeeklyAudioRequestResponse.self, from: data)
    }

    func fetchSources() async throws -> [ManagedSource] {
        let data = try await sendJSON(path: "api/sources", method: "GET")
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.sources ?? response.feeds
    }

    func addSource(name: String, url: String, tags: [String]) async throws -> [ManagedSource] {
        let data = try await sendJSON(
            path: "api/sources",
            method: "POST",
            body: [
                "name": name,
                "url": url,
                "tags": tags
            ]
        )
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.sources ?? response.feeds
    }

    func updateSource(_ source: ManagedSource, name: String, url: String, tags: [String]) async throws -> [ManagedSource] {
        let data = try await sendJSON(
            path: "api/sources",
            method: "POST",
            body: [
                "id": source.id,
                "source_id": source.sourceId ?? source.name,
                "origin": source.origin ?? "",
                "kind": source.kind ?? "",
                "name": name,
                "url": url,
                "tags": tags
            ]
        )
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.sources ?? response.feeds
    }

    func deleteSource(id: String) async throws -> [ManagedSource] {
        let data = try await sendJSON(
            path: "api/sources",
            method: "DELETE",
            body: ["id": id]
        )
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.sources ?? response.feeds
    }

    func fetchDocuments() async throws -> BackendDocumentsResponse {
        let data = try await sendJSON(path: "api/documents", method: "GET")
        return try configuredDecoder().decode(BackendDocumentsResponse.self, from: data)
    }

    func addDocumentLink(title: String, url: String, tags: [String]) async throws -> BackendDocumentsResponse {
        let data = try await sendJSON(
            path: "api/documents",
            method: "POST",
            body: [
                "title": title,
                "url": url,
                "tags": tags
            ]
        )
        return try configuredDecoder().decode(BackendDocumentsResponse.self, from: data)
    }

    func addDocumentNote(title: String, text: String, tags: [String]) async throws -> BackendDocumentsResponse {
        let data = try await sendJSON(
            path: "api/documents",
            method: "POST",
            body: [
                "title": title,
                "text": text,
                "tags": tags
            ]
        )
        return try configuredDecoder().decode(BackendDocumentsResponse.self, from: data)
    }

    func uploadDocument(fileURL: URL, title: String, tags: [String]) async throws -> BackendDocumentsResponse {
        let data = try Data(contentsOf: fileURL)
        guard data.count <= Self.safeUploadLimitBytes else {
            throw EURLexBackendError.uploadTooLarge(Self.safeUploadLimitBytes)
        }
        let payload: [String: Any] = [
            "title": title,
            "filename": fileURL.lastPathComponent,
            "mime_type": mimeType(for: fileURL),
            "content_base64": data.base64EncodedString(),
            "tags": tags
        ]

        let responseData = try await sendJSON(path: "api/documents", method: "POST", body: payload)
        return try configuredDecoder().decode(BackendDocumentsResponse.self, from: responseData)
    }

    func deleteDocument(id: String) async throws -> BackendDocumentsResponse {
        let data = try await sendJSON(
            path: "api/documents",
            method: "DELETE",
            body: ["id": id]
        )
        return try configuredDecoder().decode(BackendDocumentsResponse.self, from: data)
    }

    private func configuredDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private func mimeType(for fileURL: URL) -> String {
        switch fileURL.pathExtension.lowercased() {
        case "pdf":
            return "application/pdf"
        case "docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        case "md", "markdown":
            return "text/markdown"
        case "txt":
            return "text/plain"
        default:
            return "application/octet-stream"
        }
    }

    private func sendJSON(path: String, method: String, body: [String: Any]? = nil) async throws -> Data {
        guard let baseURL else {
            throw EURLexBackendError.notConfigured
        }

        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw EURLexBackendError.invalidURL(path)
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 25
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }

        guard (200 ..< 300).contains(httpResponse.statusCode) else {
            throw EURLexBackendError.badStatusCode(httpResponse.statusCode)
        }

        return data
    }
}
