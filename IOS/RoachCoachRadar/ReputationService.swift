import Foundation

struct RadarReputation: Codable, Hashable {
    var xp: Int
    var confirmedReports: Int
    var totalReports: Int
    var badges: [String]

    var level: Int { max(1, xp / 250 + 1) }
    var accuracy: Int { totalReports == 0 ? 0 : Int((Double(confirmedReports) / Double(totalReports) * 100).rounded()) }
    var title: String {
        switch level {
        case 1: return "Rookie Scout"
        case 2...4: return "Radar Scout"
        case 5...9: return "Hotspot Hunter"
        default: return "Roach Coach Legend"
        }
    }
}

final class ReputationService {
    static let shared = ReputationService()
    private let key = "radar.reputation.v1"

    var reputation: RadarReputation {
        get {
            guard let data = UserDefaults.standard.data(forKey: key), let value = try? JSONDecoder().decode(RadarReputation.self, from: data) else {
                return RadarReputation(xp: 0, confirmedReports: 0, totalReports: 0, badges: [])
            }
            return value
        }
        set { UserDefaults.standard.set(try? JSONEncoder().encode(newValue), forKey: key) }
    }

    func recordReport(confirmed: Bool) {
        var r = reputation
        r.totalReports += 1
        if confirmed { r.confirmedReports += 1; r.xp += 125 } else { r.xp += 50 }
        if r.totalReports >= 1 && !r.badges.contains("First Contact") { r.badges.append("First Contact") }
        if r.confirmedReports >= 5 && !r.badges.contains("Five Confirmed") { r.badges.append("Five Confirmed") }
        if r.accuracy >= 90 && r.totalReports >= 10 && !r.badges.contains("Dead Accurate") { r.badges.append("Dead Accurate") }
        reputation = r
    }
}
