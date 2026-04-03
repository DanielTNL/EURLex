import Foundation

struct AppSnapshot {
    let posts: [Post]
    let reports: [Report]
    let audio: AudioPayload
    let timeline: TimelinePayload
    let digest: DailyDigest
}

private struct CachedPayloads {
    let posts: Data
    let reports: Data
    let audio: Data
    let timeline: Data
    let digest: Data
}

enum EURLexAPIClientError: LocalizedError {
    case invalidURL(String)
    case badStatusCode(Int)

    var errorDescription: String? {
        switch self {
        case .invalidURL(let path):
            return "Could not create a request URL for \(path)."
        case .badStatusCode(let code):
            return "The feed server returned HTTP \(code)."
        }
    }
}

struct EURLexAPIClient {
    let baseURL: URL
    let session: URLSession

    static let live = EURLexAPIClient(
        baseURL: AppConfiguration.publishedDataBaseURL,
        session: configuredSession
    )

    private static let configuredSession: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.requestCachePolicy = .useProtocolCachePolicy
        configuration.timeoutIntervalForRequest = 10
        configuration.timeoutIntervalForResource = 15
        return URLSession(configuration: configuration)
    }()

    func fetchSnapshot() async throws -> AppSnapshot {
        async let posts = fetchData(path: "data/posts.json")
        async let reports = fetchData(path: "data/reports.json")
        async let audio = fetchData(path: "data/audio.json")
        async let timeline = fetchData(path: "data/timeline-latest.json")
        async let digest = fetchData(path: "digests/latest.json")

        let payloads = try await CachedPayloads(
            posts: posts,
            reports: reports,
            audio: audio,
            timeline: timeline,
            digest: digest
        )

        try persist(payloads)
        return try decodeSnapshot(from: payloads)
    }

    func cachedSnapshot() -> AppSnapshot? {
        guard let payloads = loadCachedPayloads() else { return nil }
        return try? decodeSnapshot(from: payloads)
    }

    private func fetchData(path: String) async throws -> Data {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw EURLexAPIClientError.invalidURL(path)
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 10
        request.cachePolicy = .useProtocolCachePolicy

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }

        guard (200 ..< 300).contains(httpResponse.statusCode) else {
            throw EURLexAPIClientError.badStatusCode(httpResponse.statusCode)
        }

        return data
    }

    private func decodeSnapshot(from payloads: CachedPayloads) throws -> AppSnapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        return try AppSnapshot(
            posts: decoder.decode([Post].self, from: payloads.posts),
            reports: decoder.decode([Report].self, from: payloads.reports),
            audio: decoder.decode(AudioPayload.self, from: payloads.audio),
            timeline: decoder.decode(TimelinePayload.self, from: payloads.timeline),
            digest: decoder.decode(DailyDigest.self, from: payloads.digest)
        )
    }

    private func persist(_ payloads: CachedPayloads) throws {
        let directory = try cacheDirectory()
        try payloads.posts.write(to: directory.appendingPathComponent("posts.json"), options: .atomic)
        try payloads.reports.write(to: directory.appendingPathComponent("reports.json"), options: .atomic)
        try payloads.audio.write(to: directory.appendingPathComponent("audio.json"), options: .atomic)
        try payloads.timeline.write(to: directory.appendingPathComponent("timeline.json"), options: .atomic)
        try payloads.digest.write(to: directory.appendingPathComponent("digest.json"), options: .atomic)
    }

    private func loadCachedPayloads() -> CachedPayloads? {
        guard let directory = try? cacheDirectory() else { return nil }
        guard
            let posts = try? Data(contentsOf: directory.appendingPathComponent("posts.json")),
            let reports = try? Data(contentsOf: directory.appendingPathComponent("reports.json")),
            let audio = try? Data(contentsOf: directory.appendingPathComponent("audio.json")),
            let timeline = try? Data(contentsOf: directory.appendingPathComponent("timeline.json")),
            let digest = try? Data(contentsOf: directory.appendingPathComponent("digest.json"))
        else {
            return nil
        }

        return CachedPayloads(
            posts: posts,
            reports: reports,
            audio: audio,
            timeline: timeline,
            digest: digest
        )
    }

    private func cacheDirectory() throws -> URL {
        let baseDirectory = try FileManager.default.url(
            for: .cachesDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )

        let directory = baseDirectory.appendingPathComponent("EURLexSnapshotCache", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }
}
