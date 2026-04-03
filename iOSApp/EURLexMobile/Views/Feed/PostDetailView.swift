import SwiftUI

struct PostDetailView: View {
    let post: Post

    @State private var selectedURL: IdentifiedURL?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 10) {
                    Text(post.source.uppercased())
                        .font(.caption.weight(.bold))
                        .foregroundStyle(AppTheme.accent(for: post.source))

                    if let reference = post.reference {
                        Text(reference)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(AppTheme.plumSoft)
                    }

                    Text(post.displayTitle)
                        .font(.largeTitle.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.plum)

                    Text(post.relativeDateText)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.plumSoft)
                }

                if post.hasDistinctOriginalTitle {
                    originalTitleCard
                }

                metadataCard

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Summary", subtitle: "Reader-shaped for quicker scanning, with the original document still one tap away.")
                    Text(post.summaryPreview)
                        .font(.body)
                        .foregroundStyle(AppTheme.ink)
                        .lineSpacing(5)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .dossierCard()

                if !post.primaryTags.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        SectionTitle(title: "Tags", subtitle: nil)
                        TagStrip(tags: post.primaryTags)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .dossierCard()
                }

                actionsCard
            }
            .padding(20)
            .padding(.bottom, 120)
        }
        .navigationTitle("Document")
        .navigationBarTitleDisplayMode(.inline)
        .textSelection(.enabled)
        .sheet(item: $selectedURL) { destination in
            SafariSheet(url: destination.url)
        }
    }

    private var originalTitleCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Original title", subtitle: "The untouched source title is preserved here for easy reference.")

            Text(post.originalTitleDisplay)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
                .lineSpacing(4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dossierCard()
    }

    private var metadataCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Metadata", subtitle: nil)

            detailRow(label: "Published", value: post.displayDateText)
            detailRow(label: "Source", value: post.source)
            if let reference = post.reference {
                detailRow(label: "Reference", value: reference)
            }
            detailRow(label: "Categories", value: post.categories.joined(separator: ", ").isEmpty ? "None" : post.categories.joined(separator: ", "))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dossierCard()
    }

    private var actionsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Actions", subtitle: nil)

            HStack(spacing: 12) {
                if let url = post.destinationURL {
                    Button {
                        selectedURL = IdentifiedURL(url: url)
                    } label: {
                        Label("Open original document", systemImage: "safari")
                    }
                    .buttonStyle(PrimaryCapsuleButtonStyle())

                    ShareLink(item: url) {
                        Label("Share", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(SecondaryCapsuleButtonStyle())
                } else {
                    Text("No valid source URL was published for this item.")
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.slate)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dossierCard()
    }

    private func detailRow(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.caption.weight(.bold))
                .foregroundStyle(AppTheme.accent(for: post.source))
            Text(value)
                .font(.body)
                .foregroundStyle(AppTheme.ink)
        }
    }
}
