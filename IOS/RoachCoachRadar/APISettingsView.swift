import SwiftUI

struct APISettingsView: View {
    @StateObject private var keys = APIKeyStore.shared
    @StateObject private var scanner = RadarScanService.shared
    @State private var healthState = "Not checked"
    @State private var showClearConfirmation = false
    @State private var openRouterCheck: APIKeyCheckResult = .unchecked
    @State private var xAICheck: APIKeyCheckResult = .unchecked
    @State private var anthropicCheck: APIKeyCheckResult = .unchecked
    @State private var instagramCheck: APIKeyCheckResult = .unchecked
    @State private var facebookCheck: APIKeyCheckResult = .unchecked
    @State private var xBearerCheck: APIKeyCheckResult = .unchecked
    @AppStorage("radar.scanRadius") private var scanRadius = 10.0
    @AppStorage("radar.autoScan") private var autoScan = false
    @AppStorage("radar.visionEnabled") private var visionEnabled = false
    @AppStorage("radar.aiBudget") private var aiBudget = 0.15

    var body: some View {
        Form {
            Section {
                TextField("https://your-radar-backend.example", text: $keys.backendURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)

                HStack {
                    Label(healthState, systemImage: healthIcon)
                        .foregroundStyle(healthState == "Online" ? .green : .secondary)
                    Spacer()
                    Button("Test") {
                        Task {
                            healthState = await scanner.healthCheck() ? "Online" : "Offline"
                        }
                    }
                    .disabled(keys.backendURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            } header: {
                Text("Radar Backend")
            } footer: {
                Text("Credentials entered here are stored in the iPhone Keychain. When you tap SCAN NOW, the configured backend receives only the credentials needed for that scan.")
            }

            Section("Radar Controls") {
                HStack { Text("Scan radius"); Spacer(); Text("\(Int(scanRadius)) mi").foregroundStyle(.secondary) }
                Slider(value: $scanRadius, in: 1...50, step: 1)
                Toggle("Automatic radar refresh", isOn: $autoScan)
                Toggle("Camera vision escalation", isOn: $visionEnabled)
                HStack { Text("AI budget / scan"); Spacer(); Text(String(format: "$%.2f", aiBudget)).foregroundStyle(.secondary) }
                Slider(value: $aiBudget, in: 0...1, step: 0.01)
            }

            Section("AI Providers") {
                keyRow(label: "OpenRouter API key", text: $keys.openRouterKey, result: openRouterCheck) {
                    Task { await checkKey(provider: "openrouter", key: keys.openRouterKey, result: $openRouterCheck) }
                }
                keyRow(label: "Grok / xAI API key", text: $keys.xAIKey, result: xAICheck) {
                    Task { await checkKey(provider: "grok", key: keys.xAIKey, result: $xAICheck) }
                }
                keyRow(label: "Anthropic API key", text: $keys.anthropicKey, result: anthropicCheck) {
                    Task { await checkKey(provider: "anthropic", key: keys.anthropicKey, result: $anthropicCheck) }
                }
                Picker("Strategy", selection: $keys.llmStrategy) {
                    Text("Fallback").tag("fallback")
                    Text("Round Robin").tag("round_robin")
                    Text("Single").tag("single")
                }
                if keys.llmStrategy == "single" {
                    Picker("Provider", selection: $keys.llmProvider) {
                        Text("Anthropic").tag("anthropic")
                        Text("Grok").tag("grok")
                        Text("OpenRouter").tag("openrouter")
                    }
                }
                TextField("Optional model override", text: $keys.llmModel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            Section("Social & Partnership") {
                keyRow(label: "Instagram access token", text: $keys.instagramToken, result: instagramCheck) {
                    Task { await checkKey(provider: "instagram", key: keys.instagramToken, result: $instagramCheck) }
                }
                keyRow(label: "Facebook user/page token", text: $keys.facebookToken, result: facebookCheck) {
                    Task { await checkKey(provider: "facebook", key: keys.facebookToken, result: $facebookCheck) }
                }
                keyRow(label: "X API bearer token", text: $keys.xBearerToken, result: xBearerCheck) {
                    Task { await checkKey(provider: "x_bearer", key: keys.xBearerToken, result: $xBearerCheck) }
                }
                SecureField("Partnership API key", text: $keys.partnershipKey)
                TextField("Partnership API URL", text: $keys.partnershipURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
            }

            Section("Municipal / Signal / Delivery") {
                SecureField("Municipal open-data app token", text: $keys.municipalAppToken)
                TextField("Municipal dataset URL", text: $keys.municipalDatasetURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("Telecom API key", text: $keys.telecomKey)
                TextField("Telecom API URL", text: $keys.telecomURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("Uber partner client ID", text: $keys.uberClientID)
                SecureField("Uber partner client secret", text: $keys.uberClientSecret)
                TextField("Uber partner API URL", text: $keys.uberURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("DoorDash partner API key", text: $keys.doorDashKey)
                TextField("DoorDash partner API URL", text: $keys.doorDashURL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
            }

            Section("Storage") {
                TextField("S3 bucket name", text: $keys.s3BucketName)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("AWS access key", text: $keys.awsAccessKey)
                SecureField("AWS secret key", text: $keys.awsSecretKey)
            }

            Section {
                Button(role: .destructive) {
                    showClearConfirmation = true
                } label: {
                    Label("Clear All Stored Credentials", systemImage: "trash")
                }
            }
        }
        .navigationTitle("API & Radar Settings")
        .confirmationDialog("Clear all API credentials?", isPresented: $showClearConfirmation, titleVisibility: .visible) {
            Button("Clear Everything", role: .destructive) { keys.clearAll() }
            Button("Cancel", role: .cancel) {}
        }
    }

    @ViewBuilder
    private func keyRow(label: String, text: Binding<String>, result: APIKeyCheckResult, onCheck: @escaping () -> Void) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            SecureField(label, text: text)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            HStack {
                checkStatusLabel(result)
                Spacer()
                Button("Check") { onCheck() }
                    .font(.caption)
                    .disabled(text.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || result == .checking)
            }
        }
    }

    @ViewBuilder
    private func checkStatusLabel(_ result: APIKeyCheckResult) -> some View {
        switch result {
        case .unchecked:
            EmptyView()
        case .checking:
            HStack(spacing: 4) {
                ProgressView().controlSize(.mini)
                Text("Checking…").font(.caption2).foregroundStyle(.secondary)
            }
        case .valid:
            Label("Valid", systemImage: "checkmark.circle.fill")
                .font(.caption2).foregroundStyle(.green)
        case .invalid(let reason):
            Label(reason, systemImage: "xmark.circle.fill")
                .font(.caption2).foregroundStyle(.red)
        }
    }

    private func checkKey(provider: String, key: String, result: Binding<APIKeyCheckResult>) async {
        result.wrappedValue = .checking
        result.wrappedValue = await APIKeyValidator.check(provider: provider, key: key)
    }

    private var healthIcon: String {
        switch healthState {
        case "Online": return "checkmark.circle.fill"
        case "Offline": return "xmark.circle.fill"
        default: return "questionmark.circle"
        }
    }
}
