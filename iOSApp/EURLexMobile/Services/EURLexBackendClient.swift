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

struct CustomFeed: Decodable, Hashable, Identifiable {
    let id: String
    let name: String
    let url: String
    let tags: [String]
    let addedAt: String?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case url
        case tags
        case addedAt = "added_at"
    }
}

struct CustomFeedsResponse: Decodable {
    let updatedAt: String?
    let feeds: [CustomFeed]
    let queuedProcessing: Bool?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case updatedAt = "updated_at"
        case feeds
        case queuedProcessing = "queued_processing"
        case message
    }
}

enum EURLexBackendError: LocalizedError {
    case notConfigured
    case invalidURL(String)
    case badStatusCode(Int)
    case missingAnswer

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
        }
    }
}

struct EURLexBackendClient {
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

    func fetchSources() async throws -> [CustomFeed] {
        let data = try await sendJSON(path: "api/sources", method: "GET")
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.feeds
    }

    func addSource(name: String, url: String, tags: [String]) async throws -> [CustomFeed] {
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
        return response.feeds
    }

    func deleteSource(id: String) async throws -> [CustomFeed] {
        let data = try await sendJSON(
            path: "api/sources",
            method: "DELETE",
            body: ["id": id]
        )
        let decoder = configuredDecoder()
        let response = try decoder.decode(CustomFeedsResponse.self, from: data)
        return response.feeds
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
