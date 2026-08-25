import SwiftUI

struct OnboardingView: View {
    @AppStorage("hasCompletedOnboarding") private var hasCompletedOnboarding = false
    @State private var currentPage = 0

    private let pages: [(icon: String, title: String, subtitle: String)] = [
        ("antenna.radiowaves.left.and.right", "Welcome to Roach Coach Radar", "Find real food trucks near you — spotted by real people, in real time."),
        ("bolt.fill", "No Check-Ins Required", "Trucks don't have to do anything — the community and social scraping do the work."),
        ("bell.badge.fill", "Never Miss Your Favorite", "Follow a truck and get notified the moment someone spots it on the radar.")
    ]

    var body: some View {
        VStack {
            TabView(selection: $currentPage) {
                ForEach(Array(pages.enumerated()), id: \.offset) { index, page in
                    VStack(spacing: 24) {
                        Spacer()
                        Image(systemName: page.icon)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 90, height: 90)
                            .foregroundStyle(.orange)
                            .symbolEffect(.bounce, value: currentPage == index)

                        Text(page.title)
                            .font(.title2)
                            .fontWeight(.bold)
                            .multilineTextAlignment(.center)

                        Text(page.subtitle)
                            .font(.body)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)

                        Spacer()
                        Spacer()
                    }
                    .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))

            Button {
                if currentPage < pages.count - 1 {
                    withAnimation {
                        currentPage += 1
                    }
                } else {
                    NotificationService.shared.requestPermission()
                    hasCompletedOnboarding = true
                }
            } label: {
                Text(currentPage < pages.count - 1 ? "Next" : "Get Started")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.orange)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
            }
            .padding(.horizontal, 32)
            .padding(.bottom, 24)
        }
    }
}

#Preview {
    OnboardingView()
}
