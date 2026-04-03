import SwiftUI

struct FilterPill: View {
    let title: String
    let isSelected: Bool
    var tint: Color = AppTheme.cobalt

    var body: some View {
        Text(title)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(AppTheme.ink)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background {
                Capsule(style: .continuous)
                    .fill(isSelected ? tint.opacity(0.84) : AppTheme.panelSoft)
                    .overlay {
                        Capsule(style: .continuous)
                            .fill(.ultraThinMaterial)
                            .opacity(isSelected ? 0.18 : 0.30)
                    }
            }
            .overlay {
                Capsule(style: .continuous)
                    .strokeBorder(isSelected ? Color.white.opacity(0.22) : AppTheme.border, lineWidth: 1)
            }
            .shadow(color: isSelected ? tint.opacity(0.18) : AppTheme.softShadow, radius: 8, x: 0, y: 5)
    }
}

struct PillScroller: View {
    let title: String
    let options: [String]
    let selected: String?
    let onSelect: (String?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.headline.weight(.semibold))
                .foregroundStyle(AppTheme.plum)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    Button {
                        onSelect(nil)
                    } label: {
                        FilterPill(title: "All", isSelected: selected == nil, tint: AppTheme.cobalt)
                    }
                    .buttonStyle(.plain)

                    ForEach(options, id: \.self) { option in
                        Button {
                            onSelect(selected == option ? nil : option)
                        } label: {
                            FilterPill(
                                title: option,
                                isSelected: selected == option,
                                tint: AppTheme.accent(for: option)
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
            }
            .mask {
                HorizontalEdgeFadeMask()
            }
        }
    }
}

struct TagStrip: View {
    let tags: [String]

    var body: some View {
        if !tags.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(tags, id: \.self) { tag in
                        Text(tag)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(AppTheme.ink)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 7)
                            .background {
                                Capsule(style: .continuous)
                                    .fill(AppTheme.panelSoft)
                                    .overlay {
                                        Capsule(style: .continuous)
                                            .fill(.ultraThinMaterial)
                                            .opacity(0.30)
                                    }
                            }
                            .overlay {
                                Capsule(style: .continuous)
                                    .strokeBorder(AppTheme.border, lineWidth: 1)
                            }
                    }
                }
                .padding(.horizontal, 6)
            }
            .mask {
                HorizontalEdgeFadeMask()
            }
        }
    }
}

struct HorizontalEdgeFadeMask: View {
    var fadeWidth: CGFloat = 20

    var body: some View {
        HStack(spacing: 0) {
            LinearGradient(
                colors: [.clear, .black],
                startPoint: .leading,
                endPoint: .trailing
            )
            .frame(width: fadeWidth)

            Rectangle()
                .fill(.black)

            LinearGradient(
                colors: [.black, .clear],
                startPoint: .leading,
                endPoint: .trailing
            )
            .frame(width: fadeWidth)
        }
    }
}
