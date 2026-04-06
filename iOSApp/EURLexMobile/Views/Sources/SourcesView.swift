import SwiftUI
import UniformTypeIdentifiers

struct SourcesView: View {
    @ObservedObject var model: AppModel

    @State private var selectedIntakeMode: IntakeMode?
    @State private var selectedExternalURL: IdentifiedURL?
    @State private var isDocumentViewerPresented = false
    @State private var backendSources: [ManagedSource] = []
    @State private var backendDocuments: [LibraryDocument] = []
    @State private var editingSource: ManagedSource?

    @State private var draftName = ""
    @State private var draftURL = ""
    @State private var draftTags = ""

    @State private var linkTitle = ""
    @State private var linkURL = ""
    @State private var linkTags = ""

    @State private var noteTitle = ""
    @State private var noteText = ""
    @State private var noteTags = ""

    @State private var uploadTitle = ""
    @State private var uploadTags = ""
    @State private var importedDocumentURL: URL?
    @State private var isImportingDocument = false

    @State private var isLoading = false
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var intakeMessage: String?
    @State private var hasLoaded = false
    @FocusState private var focusedField: Field?

    private let backend = EURLexBackendClient.live

    private enum Field {
        case name
        case url
        case tags
    }

    private enum IntakeMode: String, Identifiable {
        case feedURL
        case webLink
        case pdf
        case tags

        var id: String { rawValue }

        var title: String {
            switch self {
            case .feedURL: return "Feed URL"
            case .webLink: return "Web link"
            case .pdf: return "PDF or doc"
            case .tags: return "Tags & settings"
            }
        }

        var bodyText: String {
            switch self {
            case .feedURL:
                return "Add an RSS or Atom source that GitHub will fold into the scheduled discovery pipeline."
            case .webLink:
                return "Paste a single page URL to capture it into the platform library and make it available to Ask AI."
            case .pdf:
                return "Upload a public PDF, DOCX, Markdown file, or note-sized text document into the GitHub-backed library."
            case .tags:
                return "Add a quick manual note with tags so it becomes part of the searchable knowledge base."
            }
        }
    }

    private enum SourceScrollTarget: String {
        case addSource
        case customFeeds
        case documents
        case githubSources
    }

    private var activeDocuments: [LibraryDocument] {
        backendDocuments.isEmpty ? model.libraryDocuments : backendDocuments
    }

    private var customSourceCount: Int {
        backendSources.filter(\.isCustom).count
    }

    private var supportedImportTypes: [UTType] {
        [
            UTType.pdf,
            UTType.plainText,
            UTType.text,
            UTType(filenameExtension: "md"),
            UTType(filenameExtension: "markdown"),
            UTType(filenameExtension: "docx")
        ].compactMap { $0 }
    }

    var body: some View {
        ScrollViewReader { reader in
            GeometryReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        PageHeroHeader(
                            title: "Sources",
                            subtitle: "Grow the platform with feeds, links, and documents that the daily refresh and Ask AI can both use.",
                            accent: AppTheme.coral
                        )

                        heroCard(reader: reader)
                        intakeModesCard
                        addSourceCard
                            .id(SourceScrollTarget.addSource.rawValue)
                        customSourcesSection
                            .id(SourceScrollTarget.customFeeds.rawValue)
                        recentDocumentsSection
                            .id(SourceScrollTarget.documents.rawValue)
                        currentSources
                            .id(SourceScrollTarget.githubSources.rawValue)
                        bottomSpacer
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.top, 12)
                    .padding(.bottom, AppTheme.screenBottomClearance)
                    .frame(width: proxy.size.width, alignment: .leading)
                }
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .scrollDismissesKeyboard(.interactively)
        .sheet(item: $selectedIntakeMode) { mode in
            intakeModeSheet(mode)
        }
        .fileImporter(
            isPresented: $isImportingDocument,
            allowedContentTypes: supportedImportTypes,
            allowsMultipleSelection: false,
            onCompletion: handleImportedDocument
        )
        .sheet(item: $selectedExternalURL) { destination in
            SafariSheet(url: destination.url)
        }
        .sheet(isPresented: $isDocumentViewerPresented) {
            SourceDocumentsViewerSheet(
                documents: activeDocuments,
                backendConfigured: backend.isConfigured,
                onDelete: { document in
                    Task { await deleteDocument(document) }
                }
            )
        }
        .sheet(item: $editingSource) { source in
            editSourceSheet(source)
        }
        .task {
            guard !hasLoaded else { return }
            hasLoaded = true
            await loadControlRoom()
        }
    }

    private func heroCard(reader: ScrollViewProxy) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Grow the intake")
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(AppTheme.ink)

            Text(backend.isConfigured ? "Feeds and documents added here are written back into GitHub, then turned into app-ready data by Actions." : "The screen is ready. Once the backend URL is configured, this becomes your live source and document control room.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.slate)

            HStack(spacing: 12) {
                sourceStat(title: "GitHub-fed", value: "\(model.availableSources.count)", tint: AppTheme.coral) {
                    if let url = URL(string: "https://github.com/DanielTNL/EURLex") {
                        selectedExternalURL = IdentifiedURL(url: url)
                    }
                }
                sourceStat(title: "Sources", value: "\(backendSources.count)", tint: AppTheme.cobalt) {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
                        reader.scrollTo(SourceScrollTarget.addSource.rawValue, anchor: .top)
                    }
                    focusedField = .url
                }
                sourceStat(title: "Documents", value: "\(activeDocuments.count)", tint: AppTheme.lavender) {
                    isDocumentViewerPresented = true
                }
            }
        }
        .glassCard(cornerRadius: 34, tint: AppTheme.coral, padding: 22)
    }

    private var intakeModesCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Intake paths",
                subtitle: "The app now has real routes for feeds, links, notes, and uploads.",
                accent: AppTheme.lavender,
                tone: .page
            )

            VStack(spacing: 12) {
                HStack(spacing: 12) {
                    intakeModeTile(
                        mode: .feedURL,
                        title: "Feed URL",
                        subtitle: "RSS or Atom",
                        systemImage: "dot.radiowaves.left.and.right",
                        accent: AppTheme.cobalt
                    )
                    intakeModeTile(
                        mode: .webLink,
                        title: "Web link",
                        subtitle: "Single URL",
                        systemImage: "link",
                        accent: AppTheme.mint
                    )
                }

                HStack(spacing: 12) {
                    intakeModeTile(
                        mode: .pdf,
                        title: "PDF or doc",
                        subtitle: "Upload file",
                        systemImage: "doc.badge.plus",
                        accent: AppTheme.lavender
                    )
                    intakeModeTile(
                        mode: .tags,
                        title: "Tags & settings",
                        subtitle: "Manual note",
                        systemImage: "tag",
                        accent: AppTheme.coral
                    )
                }
            }

            Text(backend.isConfigured ? "GitHub remains the storage and processing layer, while the app handles clean intake." : "Once the backend URL is configured, these tiles become live GitHub-backed actions.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.pageBody)
        }
        .glassCard(cornerRadius: 30, tint: AppTheme.lavender, padding: 20)
    }

    private var addSourceCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Add a source",
                subtitle: "Start with feeds. GitHub will absorb them into the next discovery pass and published corpus refresh.",
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
                            Task { await loadControlRoom() }
                        }
                        .buttonStyle(SecondaryCapsuleButtonStyle())
                        .disabled(isLoading || isSaving)
                    }
                }
                .glassCard(cornerRadius: 28, tint: AppTheme.coral, padding: 18)
            }

            if let errorMessage {
                statusCard(text: errorMessage, tint: AppTheme.lavender)
            }
            if let intakeMessage {
                statusCard(text: intakeMessage, tint: AppTheme.mint)
            }
        }
    }

    private var customSourcesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Source registry",
                subtitle: backend.isConfigured ? "All managed sources are shown here and synced with GitHub." : "These appear once the backend is deployed and configured.",
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
            } else if backendSources.isEmpty {
                Text(backend.isConfigured ? "No sources are visible yet. Add your first feed above or wait for the registry to load." : "Backend not configured in the app yet.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
            } else {
                ForEach(backendSources) { source in
                    customFeedCard(source)
                }
            }
        }
    }

    private var recentDocumentsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Document intake",
                subtitle: backend.isConfigured ? "Links, uploads, and notes now route through the GitHub-backed library." : "Published library documents appear here already; live upload needs the backend URL.",
                accent: AppTheme.lavender,
                tone: .page
            )

            if activeDocuments.isEmpty {
                Text("No documents have been added yet. The first link, note, or file you add will appear here.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.lavender, padding: 16)
            } else {
                ForEach(Array(activeDocuments.prefix(5))) { document in
                    documentCard(document)
                }
            }
        }
    }

    private var currentSources: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionTitle(
                title: "Current GitHub-fed sources",
                subtitle: "These already flow through the published corpus today. The scroll area now clears the floating dock fully.",
                accent: AppTheme.mint,
                tone: .page
            )

            if model.availableSources.isEmpty {
                Text("No sources are visible yet. Once the feed loads, current source labels will appear here.")
                    .font(.subheadline)
                    .foregroundStyle(AppTheme.slate)
                    .glassCard(cornerRadius: 24, tint: AppTheme.mint, padding: 16)
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    TagStrip(tags: model.availableSources)

                    Text("What GitHub can safely carry")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.pageTitle)

                    Text("Public feeds, modest documents, app-ready JSON, and scheduled refreshes are a strong fit. Large private archives still belong in dedicated storage later on.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.pageBody)
                }
                .glassCard(cornerRadius: 26, tint: AppTheme.mint, padding: 16)
            }
        }
    }

    private var bottomSpacer: some View {
        Color.clear
            .frame(height: 12)
            .accessibilityHidden(true)
    }

    private func customFeedCard(_ feed: ManagedSource) -> some View {
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
                    Button {
                        editingSource = feed
                    } label: {
                        Image(systemName: "pencil")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(AppTheme.pageTitle)
                            .frame(width: 34, height: 34)
                            .background(Color.white.opacity(0.58), in: Circle())
                    }
                    .buttonStyle(.plain)
                    .disabled(isSaving)

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

            HStack(spacing: 8) {
                registryBadge(feed.displayOrigin, tint: feed.isCustom ? AppTheme.cobalt : AppTheme.mint)
                registryBadge(feed.displayKind, tint: AppTheme.coral)
            }

            if !feed.tags.isEmpty {
                TagStrip(tags: feed.tags)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
    }

    private func registryBadge(_ text: String, tint: Color) -> some View {
        Text(text)
            .font(.caption.weight(.bold))
            .foregroundStyle(tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.white.opacity(0.55), in: Capsule())
            .overlay(
                Capsule()
                    .strokeBorder(Color.white.opacity(0.75), lineWidth: 1)
            )
    }

    private func documentCard(_ document: LibraryDocument) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(document.title)
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)

                    Text("\(document.displayStatus) • \(document.sizeText)")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(AppTheme.cobalt)
                }

                Spacer(minLength: 0)

                if let url = document.destinationURL {
                    ShareLink(item: url) {
                        Image(systemName: "arrow.up.forward.app")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(AppTheme.pageTitle)
                            .frame(width: 34, height: 34)
                            .background(Color.white.opacity(0.58), in: Circle())
                    }
                    .buttonStyle(.plain)
                }
            }

            Text(document.summaryPreview)
                .font(.subheadline)
                .foregroundStyle(AppTheme.pageBody)
                .lineLimit(4)

            if !document.tags.isEmpty {
                TagStrip(tags: document.tags)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(cornerRadius: 24, tint: AppTheme.lavender, padding: 16)
    }

    private func intakeModeTile(mode: IntakeMode, title: String, subtitle: String, systemImage: String, accent: Color) -> some View {
        Button {
            selectedIntakeMode = mode
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: systemImage)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(accent)
                    .frame(width: 36, height: 36)
                    .background(
                        Circle()
                            .fill(Color.white.opacity(0.70))
                    )
                    .overlay(
                        Circle()
                            .strokeBorder(Color.white.opacity(0.88), lineWidth: 1)
                    )

                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)

                Text(subtitle)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(AppTheme.pageBody)

                Spacer(minLength: 0)

                HStack(spacing: 6) {
                    Text("Open")
                        .font(.caption2.weight(.bold))
                    Image(systemName: "arrow.up.right")
                        .font(.caption2.weight(.bold))
                }
                .foregroundStyle(accent)
                .padding(.top, 2)
            }
            .frame(maxWidth: .infinity, minHeight: 132, alignment: .topLeading)
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(Color.white.opacity(0.12))
                    .overlay {
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .fill(.ultraThinMaterial)
                            .opacity(0.25)
                    }
            )
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private func intakeModeSheet(_ mode: IntakeMode) -> some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(mode.title)
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                        .foregroundStyle(AppTheme.heroText)

                    Text(mode.bodyText)
                        .font(.body)
                        .foregroundStyle(AppTheme.heroSubtext)
                        .lineSpacing(4)

                    if let errorMessage {
                        statusCard(text: errorMessage, tint: AppTheme.coral)
                    }
                    if let intakeMessage {
                        statusCard(text: intakeMessage, tint: AppTheme.mint)
                    }

                    switch mode {
                    case .feedURL:
                        feedModeBody
                    case .webLink:
                        webLinkModeBody
                    case .pdf:
                        uploadModeBody
                    case .tags:
                        noteModeBody
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
                .padding(.bottom, 32)
            }
            .background(AmbientBackground())
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        selectedIntakeMode = nil
                    }
                    .tint(AppTheme.cobalt)
                }
            }
        }
    }

    private var feedModeBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("The main feed form is already live on the page.")
                .font(.headline.weight(.semibold))
                .foregroundStyle(AppTheme.ink)

            Text("Jump back into the feed fields and we’ll focus the RSS URL immediately.")
                .font(.subheadline)
                .foregroundStyle(AppTheme.heroSubtext)

            Button("Jump to feed form") {
                selectedIntakeMode = nil
                focusedField = .url
            }
            .buttonStyle(PrimaryCapsuleButtonStyle())
        }
        .glassCard(cornerRadius: 28, tint: AppTheme.cobalt, padding: 18)
    }

    private var webLinkModeBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            sheetField("Title", text: $linkTitle, placeholder: "Council note on EU finance", keyboard: .default)
            sheetField("URL", text: $linkURL, placeholder: "https://example.com/article", keyboard: .URL)
            sheetField("Tags", text: $linkTags, placeholder: "finance, defence, ai", keyboard: .default)

            Button {
                Task { await submitLinkDocument() }
            } label: {
                HStack(spacing: 8) {
                    if isSaving {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "link.badge.plus")
                    }
                    Text(isSaving ? "Saving..." : "Add web link")
                        .font(.headline.weight(.semibold))
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(PrimaryCapsuleButtonStyle())
            .disabled(!backend.isConfigured || isSaving || trimmed(linkURL).isEmpty)
            .opacity(!backend.isConfigured || isSaving || trimmed(linkURL).isEmpty ? 0.55 : 1)
        }
        .glassCard(cornerRadius: 28, tint: AppTheme.mint, padding: 18)
    }

    private var uploadModeBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            sheetField("Display title", text: $uploadTitle, placeholder: "Quarterly policy memo", keyboard: .default)
            sheetField("Tags", text: $uploadTags, placeholder: "memo, internal, markets", keyboard: .default)

            VStack(alignment: .leading, spacing: 10) {
                Text(importedDocumentURL?.lastPathComponent ?? "No file selected yet")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(importedDocumentURL == nil ? AppTheme.slate : AppTheme.ink)

                HStack(spacing: 12) {
                    Button("Choose file") {
                        isImportingDocument = true
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())

                    Button {
                        Task { await uploadSelectedDocument() }
                    } label: {
                        HStack(spacing: 8) {
                            if isSaving {
                                ProgressView().tint(.white)
                            } else {
                                Image(systemName: "arrow.up.doc")
                            }
                            Text(isSaving ? "Uploading..." : "Upload to GitHub")
                                .font(.headline.weight(.semibold))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())
                    .disabled(!backend.isConfigured || isSaving || importedDocumentURL == nil)
                    .opacity(!backend.isConfigured || isSaving || importedDocumentURL == nil ? 0.55 : 1)
                }
            }
        }
        .glassCard(cornerRadius: 28, tint: AppTheme.lavender, padding: 18)
    }

    private var noteModeBody: some View {
        VStack(alignment: .leading, spacing: 14) {
            sheetField("Title", text: $noteTitle, placeholder: "Meeting note", keyboard: .default)
            sheetField("Tags", text: $noteTags, placeholder: "meeting, council, ai", keyboard: .default)

            VStack(alignment: .leading, spacing: 8) {
                Text("Note text")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(AppTheme.heroSubtext)

                TextEditor(text: $noteText)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 180)
                    .padding(12)
                    .background(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .fill(Color.white.opacity(0.60))
                    )
                    .overlay {
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .strokeBorder(Color.white.opacity(0.78), lineWidth: 1)
                    }
            }

            Button {
                Task { await submitNoteDocument() }
            } label: {
                HStack(spacing: 8) {
                    if isSaving {
                        ProgressView().tint(.white)
                    } else {
                        Image(systemName: "square.and.pencil")
                    }
                    Text(isSaving ? "Saving..." : "Add tagged note")
                        .font(.headline.weight(.semibold))
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(PrimaryCapsuleButtonStyle())
            .disabled(!backend.isConfigured || isSaving || trimmed(noteText).isEmpty)
            .opacity(!backend.isConfigured || isSaving || trimmed(noteText).isEmpty ? 0.55 : 1)
        }
        .glassCard(cornerRadius: 28, tint: AppTheme.coral, padding: 18)
    }

    private func sourceStat(title: String, value: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
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
        .buttonStyle(.plain)
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
                .glassFieldBackground(cornerRadius: 18, tint: AppTheme.cobalt)
        }
    }

    private func sheetField(_ title: String, text: Binding<String>, placeholder: String, keyboard: UIKeyboardType) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.heroSubtext)

            TextField(placeholder, text: text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(keyboard)
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

    private func statusCard(text: String, tint: Color) -> some View {
        Text(text)
            .font(.subheadline)
            .foregroundStyle(AppTheme.pageTitle)
            .glassCard(cornerRadius: 22, tint: tint, padding: 14)
    }

    private func editSourceSheet(_ source: ManagedSource) -> some View {
        EditManagedSourceSheet(
            source: source,
            isSaving: isSaving,
            onSave: { name, url, tags in
                Task { await updateSource(source, name: name, url: url, tags: tags) }
            },
            onDelete: {
                Task { await removeSource(source) }
            }
        )
    }

    private var trimmedURL: String {
        trimmed(draftURL)
    }

    private var parsedTags: [String] {
        parseTags(draftTags)
    }

    private func trimmed(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func parseTags(_ raw: String) -> [String] {
        raw
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    @MainActor
    private func clearFeedDraft() {
        draftName = ""
        draftURL = ""
        draftTags = ""
        focusedField = nil
    }

    @MainActor
    private func clearIntakeDrafts(for mode: IntakeMode) {
        switch mode {
        case .feedURL:
            break
        case .webLink:
            linkTitle = ""
            linkURL = ""
            linkTags = ""
        case .pdf:
            uploadTitle = ""
            uploadTags = ""
            importedDocumentURL = nil
        case .tags:
            noteTitle = ""
            noteText = ""
            noteTags = ""
        }
    }

    private func loadControlRoom() async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isLoading = true
            errorMessage = nil
        }

        async let sources: [ManagedSource] = backend.fetchSources()
        async let documents: BackendDocumentsResponse = backend.fetchDocuments()

        do {
            let feeds = try await sources
            let registry = try await documents
            await MainActor.run {
                backendSources = feeds
                backendDocuments = registry.items
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

        let name = trimmed(draftName)
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
            intakeMessage = nil
        }

        do {
            let feeds = try await backend.addSource(name: name, url: url, tags: parsedTags)
            await MainActor.run {
                backendSources = feeds
                isSaving = false
                intakeMessage = "The feed has been saved to GitHub and queued for the next ingestion refresh."
                clearFeedDraft()
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func removeSource(_ feed: ManagedSource) async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        do {
            let feeds = try await backend.deleteSource(id: feed.id)
            await MainActor.run {
                backendSources = feeds
                isSaving = false
                editingSource = nil
                intakeMessage = "The source registry has been updated in GitHub and the next refresh will reflect the change."
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func updateSource(_ source: ManagedSource, name: String, url: String, tags: [String]) async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        do {
            let sources = try await backend.updateSource(source, name: name, url: url, tags: tags)
            await MainActor.run {
                backendSources = sources
                editingSource = nil
                isSaving = false
                intakeMessage = "The source has been updated in GitHub and queued for the next refresh."
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func submitLinkDocument() async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        do {
            let response = try await backend.addDocumentLink(
                title: trimmed(linkTitle),
                url: trimmed(linkURL),
                tags: parseTags(linkTags)
            )
            await MainActor.run {
                backendDocuments = response.items
                isSaving = false
                intakeMessage = response.message ?? "The link has been stored in GitHub and will be available to Ask AI once processing completes."
                clearIntakeDrafts(for: .webLink)
                selectedIntakeMode = nil
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func submitNoteDocument() async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        do {
            let response = try await backend.addDocumentNote(
                title: trimmed(noteTitle).isEmpty ? "Quick note" : trimmed(noteTitle),
                text: trimmed(noteText),
                tags: parseTags(noteTags)
            )
            await MainActor.run {
                backendDocuments = response.items
                isSaving = false
                intakeMessage = response.message ?? "The note has been stored in GitHub and folded into the library registry."
                clearIntakeDrafts(for: .tags)
                selectedIntakeMode = nil
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func uploadSelectedDocument() async {
        guard backend.isConfigured, let importedDocumentURL else { return }
        let title = trimmed(uploadTitle).isEmpty ? importedDocumentURL.deletingPathExtension().lastPathComponent : trimmed(uploadTitle)
        let accessed = importedDocumentURL.startAccessingSecurityScopedResource()

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        defer {
            if accessed {
                importedDocumentURL.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let response = try await backend.uploadDocument(
                fileURL: importedDocumentURL,
                title: title,
                tags: parseTags(uploadTags)
            )
            await MainActor.run {
                backendDocuments = response.items
                isSaving = false
                intakeMessage = response.message ?? "The document has been committed to GitHub and queued for processing."
                clearIntakeDrafts(for: .pdf)
                selectedIntakeMode = nil
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }

    private func handleImportedDocument(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            importedDocumentURL = urls.first
            errorMessage = nil
        case .failure(let error):
            errorMessage = error.localizedDescription
        }
    }

    private func deleteDocument(_ document: LibraryDocument) async {
        guard backend.isConfigured else { return }

        await MainActor.run {
            isSaving = true
            errorMessage = nil
            intakeMessage = nil
        }

        do {
            let response = try await backend.deleteDocument(id: document.id)
            await MainActor.run {
                backendDocuments = response.items
                isSaving = false
                intakeMessage = response.message ?? "The document has been removed from the GitHub-backed library."
            }
        } catch {
            await MainActor.run {
                isSaving = false
                errorMessage = error.localizedDescription
            }
        }
    }
}

private struct SourceDocumentsViewerSheet: View {
    let documents: [LibraryDocument]
    let backendConfigured: Bool
    let onDelete: (LibraryDocument) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedURL: IdentifiedURL?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Documents")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                        .foregroundStyle(AppTheme.heroText)

                    Text("Everything you’ve added through links, notes, and uploads lives here.")
                        .font(.body)
                        .foregroundStyle(AppTheme.heroSubtext)

                    if documents.isEmpty {
                        Text("No uploaded or linked documents are available yet.")
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.ink)
                            .glassCard(cornerRadius: 24, tint: AppTheme.lavender, padding: 16)
                    } else {
                        ForEach(documents) { document in
                            VStack(alignment: .leading, spacing: 10) {
                                HStack(alignment: .top, spacing: 12) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(document.title)
                                            .font(.headline.weight(.semibold))
                                            .foregroundStyle(AppTheme.ink)

                                        Text("\(document.displayStatus) • \(document.sizeText)")
                                            .font(.caption.weight(.bold))
                                            .foregroundStyle(AppTheme.lavender)
                                    }

                                    Spacer()

                                    if backendConfigured {
                                        Button(role: .destructive) {
                                            onDelete(document)
                                        } label: {
                                            Image(systemName: "trash")
                                                .font(.subheadline.weight(.bold))
                                                .foregroundStyle(AppTheme.heroText)
                                                .frame(width: 34, height: 34)
                                                .background(Color.white.opacity(0.08), in: Circle())
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }

                                Text(document.summaryPreview)
                                    .font(.subheadline)
                                    .foregroundStyle(AppTheme.heroSubtext)

                                if let url = document.destinationURL {
                                    HStack(spacing: 12) {
                                        Button {
                                            selectedURL = IdentifiedURL(url: url)
                                        } label: {
                                            Label("Open", systemImage: "arrow.up.forward.app")
                                        }
                                        .buttonStyle(PrimaryCapsuleButtonStyle())

                                        ShareLink(item: url) {
                                            Label("Share", systemImage: "square.and.arrow.up")
                                        }
                                        .buttonStyle(SecondaryCapsuleButtonStyle())
                                    }
                                }
                            }
                            .glassCard(cornerRadius: 26, tint: AppTheme.lavender, padding: 16)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
                .padding(.bottom, 32)
            }
            .background(AmbientEditorialBackground())
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .tint(AppTheme.cobalt)
                }
            }
            .sheet(item: $selectedURL) { destination in
                SafariSheet(url: destination.url)
            }
        }
    }
}

private struct EditManagedSourceSheet: View {
    let source: ManagedSource
    let isSaving: Bool
    let onSave: (String, String, [String]) -> Void
    let onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var url: String
    @State private var tags: String

    init(
        source: ManagedSource,
        isSaving: Bool,
        onSave: @escaping (String, String, [String]) -> Void,
        onDelete: @escaping () -> Void
    ) {
        self.source = source
        self.isSaving = isSaving
        self.onSave = onSave
        self.onDelete = onDelete
        _name = State(initialValue: source.name)
        _url = State(initialValue: source.url)
        _tags = State(initialValue: source.tags.joined(separator: ", "))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("Edit source")
                        .font(.system(size: 32, weight: .bold, design: .rounded))
                        .foregroundStyle(AppTheme.heroText)

                    Text("This source is synced with GitHub. Changes here will affect the next discovery and publishing refresh.")
                        .font(.body)
                        .foregroundStyle(AppTheme.heroSubtext)

                    VStack(alignment: .leading, spacing: 14) {
                        editableField("Name", text: $name, placeholder: "Source name")
                        editableField("URL", text: $url, placeholder: "https://example.com/feed.xml")
                        editableField("Tags", text: $tags, placeholder: "finance, defence, ai")

                        HStack(spacing: 12) {
                            Button {
                                onSave(trimmed(name), trimmed(url), parseTags(tags))
                            } label: {
                                HStack(spacing: 8) {
                                    if isSaving {
                                        ProgressView().tint(.white)
                                    } else {
                                        Image(systemName: "checkmark")
                                    }
                                    Text(isSaving ? "Saving..." : "Save changes")
                                        .font(.headline.weight(.semibold))
                                }
                                .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(PrimaryCapsuleButtonStyle())
                            .disabled(isSaving || trimmed(url).isEmpty)
                            .opacity(isSaving || trimmed(url).isEmpty ? 0.55 : 1)

                            Button(role: .destructive) {
                                onDelete()
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                            .buttonStyle(SecondaryCapsuleButtonStyle())
                            .disabled(isSaving)
                        }
                    }
                    .glassCard(cornerRadius: 28, tint: source.isCustom ? AppTheme.cobalt : AppTheme.mint, padding: 18)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(24)
                .padding(.bottom, 32)
            }
            .background(AmbientEditorialBackground())
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .tint(AppTheme.cobalt)
                }
            }
        }
    }

    private func editableField(_ title: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.heroSubtext)

            TextField(placeholder, text: text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .foregroundStyle(AppTheme.pageTitle)
                .tint(AppTheme.cobalt)
                .padding(.horizontal, 14)
                .padding(.vertical, 14)
                .glassFieldBackground(cornerRadius: 18, tint: AppTheme.cobalt)
        }
    }

    private func trimmed(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func parseTags(_ raw: String) -> [String] {
        raw
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}
