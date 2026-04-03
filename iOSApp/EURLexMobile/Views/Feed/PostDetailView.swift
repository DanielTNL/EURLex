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

                    Text(post.title)
                        .font(.largeTitle.weight(.bold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.plum)

                    Text(post.relativeDateText)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.plumSoft)
                }

                metadataCard

                VStack(alignment: .leading, spacing: 12) {
                    SectionTitle(title: "Summary", subtitle: nil)
                    Text(post.summaryPreview)
                        .font(.body)
                        .foregroundStyle(AppTheme.ink)
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

    private var metadataCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(title: "Metadata", subtitle: nil)

            detailRow(label: "Published", value: post.displayDateText)
            detailRow(label: "Source", value: post.source)
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
                        Label("Open source", systemImage: "safari")
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
