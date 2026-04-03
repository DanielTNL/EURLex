import SwiftUI

private struct AskAIMessage: Identifiable, Equatable {
    enum Role {
        case user
        case assistant
    }

    let id = UUID()
    let role: Role
    let text: String
}

struct AskAIView: View {
    @ObservedObject var model: AppModel

    @State private var prompt = ""
    @State private var webEnabled = false
    @State private var messages: [AskAIMessage] = []
    @FocusState private var isComposerFocused: Bool

    private let suggestedPrompts = [
        "What are the biggest EU policy signals today?",
        "Summarise the latest finance and defence updates.",
        "Which items matter most this week?",
        "Compare the newest report with the current briefing.",
        "Create a voice overview of the past week."
    ]

    private var bottomContentInset: CGFloat {
        messages.isEmpty ? 240 : 220
    }

    var body: some View {
        ScrollViewReader { proxy in
            GeometryReader { geometry in
                ScrollView {
                    VStack(spacing: 18) {
                        if messages.isEmpty {
                            emptyState
                        } else {
                            messagesView
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 20)
                    .padding(.top, 20)
                    .padding(.bottom, bottomContentInset)
                    .frame(width: geometry.size.width, alignment: .leading)
                }
            }
            .navigationTitle("Ask AI")
            .scrollDismissesKeyboard(.interactively)
            .safeAreaInset(edge: .bottom) {
                composerBar
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .padding(.bottom, 8)
                    .background(.clear)
            }
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Button {
                        webEnabled.toggle()
                    } label: {
                        Label(webEnabled ? "Web on" : "Web off", systemImage: webEnabled ? "globe" : "lock.doc")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(webEnabled ? .white : AppTheme.ink)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .background(
                                Capsule(style: .continuous)
                                    .fill(webEnabled ? AppTheme.coral : AppTheme.panelSoft)
                                    .overlay {
                                        Capsule(style: .continuous)
                                            .fill(.ultraThinMaterial)
                                            .opacity(webEnabled ? 0.12 : 0.34)
                                    }
                            )
                            .overlay {
                                Capsule(style: .continuous)
                                    .strokeBorder(AppTheme.border, lineWidth: 1)
                            }
                    }
                    .buttonStyle(.plain)

                    Spacer()
                }
            }
            .onChange(of: messages.count) { _, _ in
                if let lastID = messages.last?.id {
                    withAnimation(.easeOut(duration: 0.22)) {
                        proxy.scrollTo(lastID, anchor: .bottom)
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Ask anything")
                    .font(.system(size: 38, weight: .bold, design: .serif))
                    .foregroundStyle(AppTheme.plum)

                Text("Suggested prompts")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(AppTheme.plumSoft)
            }

            VStack(spacing: 10) {
                ForEach(promptOptions, id: \.self) { suggestion in
                    Button {
                        prompt = suggestion
                        isComposerFocused = true
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "arrow.up.left.and.arrow.down.right")
                                .foregroundStyle(AppTheme.cobalt)

                            Text(suggestion)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(AppTheme.ink)
                                .multilineTextAlignment(.leading)

                            Spacer(minLength: 0)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .glassCard(cornerRadius: 24, tint: AppTheme.cobalt, padding: 16)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var messagesView: some View {
        LazyVStack(alignment: .leading, spacing: 14) {
            ForEach(messages) { message in
                chatBubble(message)
                    .id(message.id)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var composerBar: some View {
        VStack(spacing: 10) {
            if !messages.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(promptOptions.prefix(4), id: \.self) { suggestion in
                            Button {
                                prompt = suggestion
                                isComposerFocused = true
                            } label: {
                                Text(suggestion)
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(AppTheme.ink)
                                    .lineLimit(1)
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 10)
                                    .background(
                                        Capsule(style: .continuous)
                                            .fill(AppTheme.panelSoft)
                                            .overlay {
                                                Capsule(style: .continuous)
                                                    .fill(.ultraThinMaterial)
                                                    .opacity(0.34)
                                            }
                                    )
                                    .overlay {
                                        Capsule(style: .continuous)
                                            .strokeBorder(AppTheme.border, lineWidth: 1)
                                    }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 2)
                }
            }

            HStack(alignment: .bottom, spacing: 12) {
                TextField("Message EURLex", text: $prompt, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.body)
                    .foregroundStyle(AppTheme.ink)
                    .focused($isComposerFocused)
                    .lineLimit(1 ... 6)

                Button {
                    sendPrompt()
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.headline.weight(.bold))
                        .foregroundStyle(.white)
                        .frame(width: 42, height: 42)
                        .background(
                            Circle()
                                .fill(
                                    LinearGradient(
                                        colors: [AppTheme.cobalt, AppTheme.lavender],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                        )
                }
                .buttonStyle(.plain)
                .opacity(trimmedPrompt.isEmpty ? 0.45 : 1)
                .disabled(trimmedPrompt.isEmpty)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .fill(AppTheme.panelStrong)
                    .overlay {
                        RoundedRectangle(cornerRadius: 28, style: .continuous)
                            .fill(.ultraThinMaterial)
                            .opacity(0.62)
                    }
            )
            .overlay {
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .strokeBorder(AppTheme.border, lineWidth: 1)
            }
            .shadow(color: AppTheme.shadow, radius: 18, x: 0, y: 10)
        }
    }

    private func chatBubble(_ message: AskAIMessage) -> some View {
        let isUser = message.role == .user

        return HStack {
            if isUser { Spacer(minLength: 50) }

            Text(message.text)
                .font(.body)
                .foregroundStyle(isUser ? .white : AppTheme.ink)
                .padding(.horizontal, 16)
                .padding(.vertical, 14)
                .background(
                    RoundedRectangle(cornerRadius: 26, style: .continuous)
                        .fill(
                            isUser
                                ? LinearGradient(
                                    colors: [AppTheme.cobalt, AppTheme.lavender],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                                : LinearGradient(
                                    colors: [AppTheme.panelStrong, AppTheme.panelSoft],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                        )
                        .overlay {
                            RoundedRectangle(cornerRadius: 26, style: .continuous)
                                .fill(.ultraThinMaterial)
                                .opacity(isUser ? 0.08 : 0.38)
                        }
                )
                .overlay {
                    RoundedRectangle(cornerRadius: 26, style: .continuous)
                        .strokeBorder(isUser ? Color.white.opacity(0.12) : AppTheme.border, lineWidth: 1)
                }
                .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)

            if !isUser { Spacer(minLength: 50) }
        }
    }

    private var trimmedPrompt: String {
        prompt.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var promptOptions: [String] {
        if webEnabled {
            return suggestedPrompts + ["Search the web for the latest update and compare it with the platform."]
        }

        return suggestedPrompts
    }

    private func sendPrompt() {
        let userPrompt = trimmedPrompt
        guard !userPrompt.isEmpty else { return }

        messages.append(AskAIMessage(role: .user, text: userPrompt))
        prompt = ""

        let response = webEnabled
            ? "Web search is enabled. Once the backend is connected, this will answer from the platform first and then add live web findings."
            : "I’ll answer from the platform corpus once the backend is connected. For now, this is the final chat layout and input flow."

        let lower = userPrompt.lowercased()
        if lower.contains("voice overview") || (lower.contains("audio") && lower.contains("week")) {
            messages.append(
                AskAIMessage(
                    role: .assistant,
                    text: "This will map to a weekly audio request. The GitHub side is being prepared to publish requested weekly briefings into the Voice tab, and the app UI is already shaped for those uploads."
                )
            )
            return
        }

        messages.append(AskAIMessage(role: .assistant, text: response))
    }
}
