import SwiftUI
import CloudKit

@main
struct RoachCoachRadarApp: App {
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false

    var body: some Scene {
        WindowGroup {
            if hasCompletedOnboarding {
                RootTabView()
            } else {
                OnboardingView()
            }
        }
        .onChange(of: hasCompletedOnboarding) { _, completed in
            guard completed else { return }
            Task { await CloudKitService.shared.installRadarSubscription() }
        }
    }
}
