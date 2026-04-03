import SwiftUI

private enum ReportScope: String, CaseIterable, Identifiable {
    case all = "All"
    case daily = "Daily"
    case weekly = "Weekly"

    var id: String { rawValue }

    func matches(_ report: Report) -> Bool {
        switch self {
        case .all:
            return true
        case .daily:
            return report.tags.contains("daily")
        case .weekly:
            return report.tags.contains("weekly")
        }
    }
}

struct ReportsView: View {
    @ObservedObject var model: AppModel

    @State private var scope: ReportScope = .all

    private var filteredReports: [Report] {
        model.reports.filter(scope.matches)
    }

    var body: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    SectionTitle(
                        title: "Reports archive",
                        subtitle: "\(filteredReports.count) reports available",
                        tone: .page
                    )

                    Picker("Report type", selection: $scope) {
                        ForEach(ReportScope.allCases) { scope in
                            Text(scope.rawValue).tag(scope)
                        }
                    }
                    .pickerStyle(.segmented)

                    if filteredReports.isEmpty {
                        ContentUnavailableView(
                            "No reports yet",
                            systemImage: "text.book.closed",
                            description: Text("This scope does not currently have any published reports.")
                        )
                        .frame(maxWidth: .infinity)
                        .padding(.top, 28)
                    } else {
                        LazyVStack(spacing: 16) {
                            ForEach(filteredReports) { report in
                                NavigationLink(destination: ReportDetailView(report: report)) {
                                    ReportCardView(report: report)
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
        .navigationTitle("Reports")
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
