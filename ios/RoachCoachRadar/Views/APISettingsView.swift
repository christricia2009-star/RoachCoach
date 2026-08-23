import SwiftUI

struct APISettingsView: View {
    @StateObject private var keys = APIKeyStore.shared
    @StateObject private var scanner = RadarScanService.shared
    @State private var healthState = "Not checked"
    @State private var showClearConfirmation = false
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
                SecureField("OpenRouter API key", text: $keys.openRouterKey)
                SecureField("Grok / xAI API key", text: $keys.xAIKey)
                SecureField("Anthropic API key", text: $keys.anthropicKey)
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
                SecureField("Instagram access token", text: $keys.instagramToken)
                SecureField("X API bearer token", text: $keys.xBearerToken)
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

    private var healthIcon: String {
        switch healthState {
        case "Online": return "checkmark.circle.fill"
        case "Offline": return "xmark.circle.fill"
        default: return "questionmark.circle"
        }
    }
}
