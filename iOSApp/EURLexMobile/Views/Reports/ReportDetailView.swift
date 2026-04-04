import SwiftUI

struct ReportDetailView: View {
    let report: Report

    @State private var selectedURL: IdentifiedURL?
    @State private var fullTextState: ReportTextState = .idle

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(report.typeLabel.uppercased())
                        .font(.caption.weight(.bold))
                        .foregroundStyle(report.tags.contains("weekly") ? AppTheme.coral : AppTheme.cobalt)

                    Text(report.displayTitle)
                        .font(.largeTitle.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.pageTitle)

                    Text(report.displayDateText)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageBody)
                }

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Abstract", subtitle: nil)
                    Text(report.abstractPreview)
                        .font(.body)
                        .foregroundStyle(AppTheme.ink)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .dossierCard()

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Key items", subtitle: report.keyItems.isEmpty ? "No key items were published with this report." : nil)

                    if report.keyItems.isEmpty {
                        Text("The markdown report exists, but the structured payload did not include specific highlights.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(Array(report.keyItems.enumerated()), id: \.offset) { index, item in
                            HStack(alignment: .top, spacing: 12) {
                                Text("\(index + 1)")
                                    .font(.caption.weight(.bold))
                                    .foregroundStyle(.white)
                                    .frame(width: 26, height: 26)
                                    .background(Circle().fill(report.tags.contains("weekly") ? AppTheme.coral : AppTheme.cobalt))
                                Text(item)
                                    .font(.body)
                                    .foregroundStyle(AppTheme.ink)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .dossierCard()

                fullTextCard
            }
            .padding(20)
            .padding(.bottom, 130)
        }
        .navigationTitle("Report")
        .navigationBarTitleDisplayMode(.inline)
        .textSelection(.enabled)
        .task(id: report.id) {
            await loadFullText()
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if report.htmlURL != nil || report.driveURL != nil {
                    Menu {
                        if let url = report.htmlURL {
                            Button {
                                selectedURL = IdentifiedURL(url: url)
                            } label: {
                                Label("Open source file", systemImage: "doc.plaintext")
                            }
                        }

                        if let driveURL = report.driveURL {
                            Button {
                                selectedURL = IdentifiedURL(url: driveURL)
                            } label: {
                                Label("Open Drive copy", systemImage: "externaldrive")
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .tint(AppTheme.cobalt)
                }
            }
        }
        .sheet(item: $selectedURL) { destination in
            SafariSheet(url: destination.url)
        }
    }

    @ViewBuilder
    private var fullTextCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Full report",
                subtitle: "The full source text is opened here so you do not need an extra tap.",
                accent: report.tags.contains("weekly") ? AppTheme.coral : AppTheme.cobalt
            )

            switch fullTextState {
            case .idle, .loading:
                HStack(spacing: 12) {
                    ProgressView()
                        .tint(AppTheme.cobalt)
                    Text("Loading the full report text…")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                }

            case .loaded(let body):
                ReportBodyText(text: body)

            case .failed(let message):
                VStack(alignment: .leading, spacing: 12) {
                    Text(message)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)

                    if let url = report.htmlURL {
                        Button {
                            selectedURL = IdentifiedURL(url: url)
                        } label: {
                            Label("Open source file instead", systemImage: "safari")
                        }
                        .buttonStyle(PrimaryCapsuleButtonStyle())
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dossierCard()
    }

    private func loadFullText() async {
        guard case .idle = fullTextState else { return }
        guard let url = report.rawContentURL else {
            fullTextState = .failed("No inline report source is available for this item yet.")
            return
        }

        fullTextState = .loading

        do {
            var request = URLRequest(url: url)
            request.timeoutInterval = 20
            request.cachePolicy = .useProtocolCachePolicy

            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse, (200 ..< 300).contains(httpResponse.statusCode) else {
                fullTextState = .failed("The full report text could not be loaded right now.")
                return
            }

            let rawText = String(decoding: data, as: UTF8.self)
            let prepared = report.preparedBody(from: rawText)
            fullTextState = .loaded(prepared.isEmpty ? "The source file is available, but it did not contain readable text." : prepared)
        } catch {
            fullTextState = .failed("The full report text could not be loaded right now. You can still open the source file from the menu in the top right.")
        }
    }
}

private enum ReportTextState {
    case idle
    case loading
    case loaded(String)
    case failed(String)
}

private struct ReportBodyText: View {
    let text: String

    var body: some View {
        if let attributed = try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .full)
        ) {
            Text(attributed)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            Text(text)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
                .lineSpacing(5)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
