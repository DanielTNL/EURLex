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

        let data = try await sendJSON(path: "api/chat", body: requestBody)
        let decoder = JSONDecoder()
        return try decoder.decode(BackendChatResponse.self, from: data)
    }

    func requestWeeklyAudio(promptHint: String, endDate: String? = nil) async throws -> WeeklyAudioRequestResponse {
        var requestBody: [String: Any] = ["prompt_hint": promptHint]
        if let endDate, !endDate.isEmpty {
            requestBody["end_date"] = endDate
        }

        let data = try await sendJSON(path: "api/audio-request", body: requestBody)
        let decoder = JSONDecoder()
        return try decoder.decode(WeeklyAudioRequestResponse.self, from: data)
    }

    private func sendJSON(path: String, body: [String: Any]) async throws -> Data {
        guard let baseURL else {
            throw EURLexBackendError.notConfigured
        }

        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw EURLexBackendError.invalidURL(path)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 25
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

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
