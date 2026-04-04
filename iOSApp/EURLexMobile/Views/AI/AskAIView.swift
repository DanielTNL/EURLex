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
    @State private var isSending = false
    @FocusState private var isComposerFocused: Bool

    private let backend = EURLexBackendClient.live

    private let suggestedPrompts = [
        "What are the biggest EU policy signals today?",
        "Summarise the latest finance and defence updates.",
        "Which items matter most this week?",
        "Compare the newest report with the current briefing.",
        "Create a voice overview of the past week."
    ]

    private var bottomContentInset: CGFloat {
        messages.isEmpty ? 300 : 268
    }

    var body: some View {
        ScrollViewReader { proxy in
            GeometryReader { geometry in
                ScrollView {
                    VStack(spacing: 18) {
                        PageHeroHeader(
                            title: "Ask AI",
                            subtitle: "Chat across the platform, with optional web search when you turn it on.",
                            accent: AppTheme.mint
                        )

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
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .scrollDismissesKeyboard(.interactively)
            .safeAreaInset(edge: .bottom) {
                composerBar
                    .padding(.horizontal, 16)
                    .padding(.top, 10)
                    .padding(.bottom, AppTheme.composerBottomLift)
                    .background(.clear)
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
                    .foregroundStyle(AppTheme.pageTitle)

                Text("Suggested prompts")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(AppTheme.pageBody)

                Text(backend.isConfigured ? "Ready to answer from the platform now." : "Backend deployment is the last step before live answers appear here.")
                    .font(.caption)
                    .foregroundStyle(AppTheme.pageSubtext)
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

            if isSending {
                HStack {
                    ProgressView()
                        .tint(AppTheme.cobalt)

                    Text("Thinking…")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(AppTheme.pageBody)
                }
                .padding(.horizontal, 4)
                .id("typing-indicator")
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

            HStack(alignment: .center, spacing: 12) {
                Button {
                    webEnabled.toggle()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: webEnabled ? "globe" : "internaldrive")
                            .font(.subheadline.weight(.bold))

                        Text(webEnabled ? "Web on" : "Corpus")
                            .font(.caption.weight(.semibold))
                    }
                    .foregroundStyle(webEnabled ? .white : AppTheme.ink)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 11)
                    .background(
                        Capsule(style: .continuous)
                            .fill(webEnabled ? AppTheme.coral.opacity(0.92) : AppTheme.panelSoft)
                            .overlay {
                                Capsule(style: .continuous)
                                    .fill(.ultraThinMaterial)
                                    .opacity(webEnabled ? 0.10 : 0.38)
                            }
                    )
                    .overlay {
                        Capsule(style: .continuous)
                            .strokeBorder(AppTheme.border, lineWidth: 1)
                    }
                }
                .buttonStyle(.plain)

                TextField(
                    "",
                    text: $prompt,
                    prompt: Text("Type your prompt")
                        .foregroundStyle(AppTheme.heroSubtext.opacity(0.92)),
                    axis: .vertical
                )
                    .textFieldStyle(.plain)
                    .font(.body)
                    .foregroundStyle(AppTheme.ink)
                    .focused($isComposerFocused)
                    .submitLabel(.send)
                    .lineLimit(1 ... 5)
                    .onSubmit {
                        sendPrompt()
                    }

                Button {
                    sendPrompt()
                } label: {
                    Group {
                        if isSending {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.headline.weight(.bold))
                                .foregroundStyle(.white)
                        }
                    }
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
                .opacity(trimmedPrompt.isEmpty || isSending ? 0.45 : 1)
                .disabled(trimmedPrompt.isEmpty || isSending)
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
            .contentShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
            .onTapGesture {
                isComposerFocused = true
            }
        }
    }

    private func chatBubble(_ message: AskAIMessage) -> some View {
        let isUser = message.role == .user

        return HStack {
            if isUser { Spacer(minLength: 50) }

            Group {
                if isUser {
                    Text(message.text)
                        .font(.body)
                        .foregroundStyle(.white)
                } else {
                    AssistantAnswerView(text: message.text)
                }
            }
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
        guard !userPrompt.isEmpty, !isSending else { return }

        messages.append(AskAIMessage(role: .user, text: userPrompt))
        prompt = ""
        isSending = true

        Task {
            let lower = userPrompt.lowercased()

            do {
                if lower.contains("voice overview") || (lower.contains("audio") && lower.contains("week")) {
                    let result = try await backend.requestWeeklyAudio(promptHint: userPrompt)
                    let response = result.message ?? "I queued a weekly voice overview. Once GitHub finishes the workflow and publishes the audio, it will appear in the Voice tab after refresh."

                    await MainActor.run {
                        messages.append(AskAIMessage(role: .assistant, text: response))
                        isSending = false
                    }
                    return
                }

                let payload = messages.map {
                    BackendChatMessage(
                        role: $0.role == .assistant ? "assistant" : "user",
                        content: $0.text
                    )
                }

                let response = try await backend.chat(messages: payload, remote: webEnabled)
                let answer = AIAnswerFormatter.normalized(response.answer ?? "")

                await MainActor.run {
                    messages.append(
                        AskAIMessage(
                            role: .assistant,
                            text: answer.isEmpty
                                ? "The backend responded, but it did not return an answer yet."
                                : answer
                        )
                    )
                    isSending = false
                }
            } catch {
                let message: String
                if let localized = error as? LocalizedError, let description = localized.errorDescription {
                    message = description
                } else {
                    message = "The backend could not be reached right now."
                }

                await MainActor.run {
                    messages.append(
                        AskAIMessage(
                            role: .assistant,
                            text: "I couldn’t complete that request yet. \(message) If the backend has not been deployed yet, that is the next setup step."
                        )
                    )
                    isSending = false
                }
            }
        }
    }
}

private enum AIAnswerBlock: Hashable {
    case heading(String)
    case paragraph(String)
    case bullets([String])
}

private enum AIAnswerFormatter {
    static func normalized(_ text: String) -> String {
        let linePreserving = text
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: #"(?m)^#{1,6}\s*"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\*\*(.*?)\*\*"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"__(.*?)__"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"`([^`]+)`"#, with: "$1", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)

        return linePreserving
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map {
                String($0)
                    .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func blocks(from text: String) -> [AIAnswerBlock] {
        let normalizedText = normalized(text)
        guard !normalizedText.isEmpty else { return [] }

        let lines = normalizedText
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map(String.init)

        var blocks: [AIAnswerBlock] = []
        var paragraphLines: [String] = []
        var index = 0

        func flushParagraph() {
            guard !paragraphLines.isEmpty else { return }
            blocks.append(.paragraph(paragraphLines.joined(separator: " ")))
            paragraphLines.removeAll()
        }

        while index < lines.count {
            let line = lines[index].trimmingCharacters(in: .whitespacesAndNewlines)

            if line.isEmpty {
                flushParagraph()
                index += 1
                continue
            }

            if isBullet(line) {
                flushParagraph()
                var bullets: [String] = []
                while index < lines.count {
                    let current = lines[index].trimmingCharacters(in: .whitespacesAndNewlines)
                    guard isBullet(current) else { break }
                    let cleaned = stripBullet(current)
                    if !cleaned.isEmpty {
                        bullets.append(cleaned)
                    }
                    index += 1
                }
                if !bullets.isEmpty {
                    blocks.append(.bullets(bullets))
                }
                continue
            }

            let nextNonEmpty = lines[(index + 1)...].first {
                !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            if looksLikeHeading(line, nextNonEmpty: nextNonEmpty, isFirstBlock: blocks.isEmpty && paragraphLines.isEmpty) {
                flushParagraph()
                blocks.append(.heading(line))
                index += 1
                continue
            }

            paragraphLines.append(line)
            index += 1
        }

        flushParagraph()
        return blocks.isEmpty ? [.paragraph(normalizedText)] : blocks
    }

    private static func isBullet(_ line: String) -> Bool {
        line.range(of: #"^(?:[-*•]|\d+[.)])\s+"#, options: .regularExpression) != nil
    }

    private static func stripBullet(_ line: String) -> String {
        line
            .replacingOccurrences(of: #"^(?:[-*•]|\d+[.)])\s+"#, with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func looksLikeHeading(_ line: String, nextNonEmpty: String?, isFirstBlock: Bool) -> Bool {
        guard nextNonEmpty != nil else { return false }
        guard !line.contains("http"), !line.hasSuffix("."), !line.hasSuffix(":"), !isBullet(line) else { return false }

        if isFirstBlock, line.count <= 110 {
            return true
        }

        let wordCount = line.split(separator: " ").count
        return line.count <= 72 && wordCount <= 8
    }
}

private struct AssistantAnswerView: View {
    let text: String

    private var blocks: [AIAnswerBlock] {
        AIAnswerFormatter.blocks(from: text)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                switch block {
                case .heading(let title):
                    Text(title)
                        .font(index == 0 ? .title3.weight(.bold) : .headline.weight(.semibold))
                        .fontDesign(.serif)
                        .foregroundStyle(AppTheme.ink)
                        .frame(maxWidth: .infinity, alignment: .leading)

                case .paragraph(let paragraph):
                    Text(paragraph)
                        .font(.body)
                        .foregroundStyle(AppTheme.ink)
                        .lineSpacing(5)
                        .frame(maxWidth: .infinity, alignment: .leading)

                case .bullets(let items):
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(AppTheme.cobalt)
                                    .frame(width: 7, height: 7)
                                    .padding(.top, 6)

                                Text(item)
                                    .font(.body)
                                    .foregroundStyle(AppTheme.ink)
                                    .lineSpacing(4)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
