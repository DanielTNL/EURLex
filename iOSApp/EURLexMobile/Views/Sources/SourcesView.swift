import SwiftUI

struct SourcesView: View {
    @ObservedObject var model: AppModel

    @State private var backendFeeds: [CustomFeed] = []
    @State private var draftName = ""
    @State private var draftURL = ""
    @State private var draftTags = ""
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var hasLoaded = false
    @FocusState private var focusedField: Field?

    private let backend = EURLexBackendClient.live

    private enum Field {
        case name
        case url
        case tags
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    PageHeroHeader(
                        title: "Sources",
                        subtitle: "Add RSS and Atom feeds that should join the platform's daily refresh.",
                        accent: AppTheme.coral
                    )

                    heroCard
                    addSourceCard
                    customSourcesSection
                    currentSources
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 20)
                .padding(.top, 12)
                .padding(.bottom, 30)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .scrollDismissesKeyboard(.interactively)
        .task {
            guard !hasLoaded else { return }
            hasLoaded = true
            await loadSources()
        }
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Grow the intake")
                .font(.system(size: 34, weight: .bold, design: .serif))
                .foregroundStyle(AppTheme.ink)

            Text(backend.isConfigured ? "Custom feeds you add here are stored back into GitHub and can be pulled into the next scheduled refresh." : "The screen is wired and ready. Once the backend URL is configured, this becomes your live source control room.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            HStack(spacing: 12) {
                sourceStat(title: "GitHub-fed", value: "\(model.availableSources.count)", tint: AppTheme.coral)
                sourceStat(title: "Custom feeds", value: "\(backendFeeds.count)", tint: AppTheme.cobalt)
            }
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.coral, padding: 22)
    }

    private var addSourceCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Add a source",
                subtitle: "Paste a valid RSS or Atom feed URL. Tags are optional.",
                accent: AppTheme.coral,
                tone: .page
            )

            if !backend.isConfigured {
                Text("Set `EURLexBackendBaseURL` in the app first, then this form becomes live.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.coral, padding: 16)
            } else {
                VStack(spacing: 12) {
                    sourceField("Source name", text: $draftName, field: .name, keyboard: .default)
                    sourceField("RSS or Atom URL", text: $draftURL, field: .url, keyboard: .URL)
                    sourceField("Tags, comma separated", text: $draftTags, field: .tags, keyboard: .default)

                    HStack(spacing: 12) {
                        Button {
                            Task { await submitSource() }
                        } label: {
                            HStack(spacing: 8) {
                                if isSaving {
                                    ProgressView()
                                        .tint(.white)
                                } else {
                                    Image(systemName: "plus")
                                }

                                Text(isSaving ? "Saving..." : "Add source")
                                    .font(.headline.weight(.semibold))
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(PrimaryCapsuleButtonStyle())
                        .disabled(isSaving || trimmedURL.isEmpty)
                        .opacity(isSaving || trimmedURL.isEmpty ? 0.55 : 1)

                        Button("Refresh") {
                            Task { await loadSources() }
                        }
                        .buttonStyle(SecondaryCapsuleButtonStyle())
                        .disabled(isLoading || isSaving)
                    }
                }
                .glassCard(cornerRadius: 28, tint: AppTheme.coral, padding: 18)
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.pageTitle)
                    .glassCard(cornerRadius: 22, tint: AppTheme.lavender, padding: 14)
            }
        }
    }

    private var customSourcesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Custom feeds",
                subtitle: backend.isConfigured ? "These are the app-managed feeds saved back into GitHub." : "These appear once the backend is deployed and configured.",
                accent: AppTheme.cobalt,
                tone: .page
            )

            if isLoading {
                HStack(spacing: 10) {
                    ProgressView()
                        .tint(AppTheme.cobalt)
                    Text("Loading feeds...")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.slate)
                }
                .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
            } else if backendFeeds.isEmpty {
                Text(backend.isConfigured ? "No custom feeds yet. Add your first source above." : "Backend not configured in the app yet.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
            } else {
                ForEach(backendFeeds) { feed in
                    customFeedCard(feed)
                }
            }
        }
    }

    private var currentSources: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Current GitHub-fed sources",
                subtitle: "These already flow through the published corpus today.",
                accent: AppTheme.mint,
                tone: .page
            )

            if model.availableSources.isEmpty {
                Text("No sources are visible yet. Once the feed loads, current source labels will appear here.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.mint, padding: 16)
            } else {
                TagStrip(tags: model.availableSources)
                    .glassCard(cornerRadius: 26, tint: AppTheme.mint, padding: 16)
            }
        }
    }

    private func customFeedCard(_ feed: CustomFeed) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(feed.name)
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)

                    Text(feed.url)
                        .font(.caption)
                        .foregroundStyle(AppTheme.slate)
                        .textSelection(.enabled)
                }

                Spacer(minLength: 0)

                if backend.isConfigured {
                    Button(role: .destructive) {
                        Task { await removeSource(feed) }
                    } label: {
                        Image(systemName: "trash")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(AppTheme.pageTitle)
                            .frame(width: 34, height: 34)
                            .background(Color.white.opacity(0.58), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(isSaving)
                }
            }

            if !feed.tags.isEmpty {
                TagStrip(tags: feed.tags)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
    }

    private func sourceStat(title: String, value: String, tint: Color) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.title2.weight(.bold))
                .foregroundStyle(AppTheme.ink)
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(tint)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(Color.white.opacity(0.58), in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .strokeBorder(Color.white.opacity(0.76), lineWidth: 1)
        )
    }

    private func sourceField(_ title: String, text: Binding<String>, field: Field, keyboard: UIKeyboardType) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.pageBody)

            TextField(title, text: text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(keyboard)
                .textFieldStyle(.plain)
                .focused($focusedField, equals: field)
                .padding(.horizontal, 14)
                .padding(.vertical, 14)
                .background(
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .fill(Color.white.opacity(0.58))
                )
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.76), lineWidth: 1)
                }
        }
    }

    private var trimmedURL: String {
        draftURL.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var parsedTags: [String] {
        draftTags
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    @MainActor
    private func clearDraft() {
        draftName = ""
        draftURL = ""
        draftTags = ""
        focusedField = nil
    }

    @MainActor
    private func setError(_ message: String?) {
        errorMessage = message
    }

    private func loadSources() async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isLoading = true
            errorMessage = nil
        }

        do {
            let feeds = try await backend.fetchSources()
            await MainActor.run {
                backendFeeds = feeds
                isLoading = false
            }
        } catch {
            await MainActor.run {
                isLoading = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func submitSource() async {
        guard backend.isConfigured else { return }

        let name = draftName.trimmingCharacters(in: .whitespacesAndNewlines)
        let url = trimmedURL
        guard !url.isEmpty else {
            await MainActor.run {
                errorMessage = "Please paste a valid RSS or Atom URL."
            }
            return
        }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
        }

        do {
            let feeds = try await backend.addSource(name: name, url: url, tags: parsedTags)
            await MainActor.run {
                backendFeeds = feeds
                isSaving = false
                clearDraft()
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func removeSource(_ feed: CustomFeed) async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
        }

        do {
            let feeds = try await backend.deleteSource(id: feed.id)
            await MainActor.run {
                backendFeeds = feeds
                isSaving = false
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }
}
