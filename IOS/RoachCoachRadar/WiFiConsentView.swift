import SwiftUI

/// Explicit consent screen for Wi-Fi-based truck detection, per your note
/// that this is fine "as long as notice is made and accepted." Present this
/// BEFORE enabling WiFiDetectionService — never enable it silently.
struct WiFiConsentView: View {
    @ObservedObject private var service = WiFiDetectionService.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Image(systemName: "wifi.circle.fill")
                        .resizable()
                        .frame(width: 60, height: 60)
                        .foregroundStyle(.orange)
                        .frame(maxWidth: .infinity)

                    Text("Wi-Fi Truck Detection")
                        .font(.title2)
                        .fontWeight(.bold)
                        .frame(maxWidth: .infinity, alignment: .center)

                    Text("Some trucks broadcast a Wi-Fi network for menu QR codes (for example, \"RoachCoach-BaoBaoBus\"). If you turn this on and later join one of those networks yourself, we'll recognize it and log a sighting.")
                        .font(.body)

                    Text("What this does NOT do:")
                        .font(.headline)
                        .padding(.top, 8)

                    VStack(alignment: .leading, spacing: 8) {
                        Label("It does not scan for nearby networks you haven't joined — iOS doesn't allow that for regular apps.", systemImage: "xmark.circle")
                        Label("It only recognizes a network after you've manually connected to it, the same as joining any public Wi-Fi.", systemImage: "xmark.circle")
                        Label("It does not track your location history or other networks you join.", systemImage: "xmark.circle")
                    }
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                    Text("Requires Location permission (iOS ties Wi-Fi network info to location privacy) and the network name of whatever you're currently connected to.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .padding(.top, 8)

                    VStack(spacing: 12) {
                        Button {
                            service.grantConsent()
                            dismiss()
                        } label: {
                            Text("Turn On")
                                .font(.headline)
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.orange)
                                .clipShape(RoundedRectangle(cornerRadius: 12))
                        }

                        Button {
                            service.revokeConsent()
                            dismiss()
                        } label: {
                            Text("Not Now")
                                .frame(maxWidth: .infinity)
                                .padding()
                        }
                    }
                    .padding(.top, 16)
                }
                .padding()
            }
            .navigationTitle("Notice & Consent")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

#Preview {
    WiFiConsentView()
}
