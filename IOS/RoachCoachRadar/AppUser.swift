import Foundation

struct AppUser: Identifiable, Codable {
    let id: UUID
    var displayName: String
    var homeCity: String
    var favoriteTruckIds: [UUID]
    var reputationScore: Int
    var notificationsEnabled: Bool

    init(
        id: UUID = UUID(),
        displayName: String,
        homeCity: String = "",
        favoriteTruckIds: [UUID] = [],
        reputationScore: Int = 0,
        notificationsEnabled: Bool = true
    ) {
        self.id = id
        self.displayName = displayName
        self.homeCity = homeCity
        self.favoriteTruckIds = favoriteTruckIds
        self.reputationScore = reputationScore
        self.notificationsEnabled = notificationsEnabled
    }
}
