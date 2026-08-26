import SwiftUI
import UIKit

/// Lightweight tester feedback. Opens a prefilled GitHub issue so notes
/// land next to the radar repo instead of disappearing in Messages.
struct FeedbackView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var category = "Bug"
    @State private var message = ""
    @State private var copied = false

    private let categories = ["Bug", "Missing truck", "Wrong pin", "Photo / social", "Region", "Other"]

    var body: some View {
        Form {
            Section("What is this about?") {
                Picker("Category", selection: $category) {
                    ForEach(categories, id: \.self) { Text($0) }
                }
            }

            Section("Details") {
                TextEditor(text: $message)
                    .frame(minHeight: 140)
                Text("Truck name, city, and what you expected vs what you saw helps most.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            Section {
                Button {
                    UIPasteboard.general.string = issueBody
                    copied = true
                } label: {
                    Label(copied ? "Copied" : "Copy notes", systemImage: copied ? "checkmark" : "doc.on.clipboard")
                }

                if let url = githubIssueURL {
                    Link(destination: url) {
                        Label("Open GitHub issue", systemImage: "exclamationmark.bubble")
                    }
                }
            } footer: {
                Text("Rebuild the app after the latest scheduler run so Instagram thumbprints have time to land in CloudKit.")
            }
        }
        .navigationTitle("Send Feedback")
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Close") { dismiss() }
            }
        }
    }

    private var issueBody: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        return """
        ## \(category)

        \(message.isEmpty ? "(describe what you saw)" : message)

        ---
        App \(version) (\(build))
        """
    }

    private var githubIssueURL: URL? {
        var components = URLComponents(string: "https://github.com/christricia2009-star/RoachCoach/issues/new")
        components?.queryItems = [
            URLQueryItem(name: "title", value: "[\(category)] Roach Coach Radar"),
            URLQueryItem(name: "body", value: issueBody)
        ]
        return components?.url
    }
}
