import SwiftUI

struct FeedView: View {
    @ObservedObject var model: AppModel

    @State private var searchText = ""
    @State private var selectedSource: String?
    @State private var selectedCategory: String?

    private var filteredPosts: [Post] {
        model.posts.filter { post in
            if let selectedSource, post.source != selectedSource {
                return false
            }

            if let selectedCategory, !post.categories.contains(selectedCategory) {
                return false
            }

            let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !query.isEmpty else { return true }

            let haystack = [
                post.displayTitle,
                post.originalTitleDisplay,
                post.summaryPreview,
                post.source,
                post.reference ?? "",
                post.tags.joined(separator: " "),
                post.categories.joined(separator: " ")
            ]
            .joined(separator: " ")
            .lowercased()

            return haystack.contains(query)
        }
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    PageHeroHeader(
                        title: "Feed",
                        subtitle: "Search, filter, and open the live document stream.",
                        accent: AppTheme.cobalt
                    )

                    SectionTitle(
                        title: "Live document feed",
                        subtitle: "\(filteredPosts.count) matching documents",
                        tone: .page
                    )

                    PillScroller(
                        title: "Sources",
                        options: model.availableSources,
                        selected: selectedSource,
                        onSelect: { selectedSource = $0 }
                    )

                    PillScroller(
                        title: "Categories",
                        options: model.availableCategories,
                        selected: selectedCategory,
                        onSelect: { selectedCategory = $0 }
                    )

                    if filteredPosts.isEmpty {
                        ContentUnavailableView(
                            "No matching documents",
                            systemImage: "doc.text.magnifyingglass",
                            description: Text("Try a broader search or clear one of the filters.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 28)
                    } else {
                        LazyVStack(spacing: 16) {
                            ForEach(filteredPosts) { post in
                                NavigationLink(destination: PostDetailView(post: post)) {
                                    PostCardView(post: post)
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
                .frame(width: proxy.size.width, alignment: .leading)
            }
        }
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $searchText, prompt: "Search titles, summaries, tags")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await model.reload() }
                } label: {
                    if model.isLoading {
                        ProgressView()
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .tint(AppTheme.cobalt)
            }
        }
        .refreshable {
            await model.reload()
        }
    }
}
