import Foundation
import Combine

final class FavoritesStore: ObservableObject {
    static let shared = FavoritesStore()

    @Published private(set) var ids: Set<UUID>
    private let key = "favoriteTruckIDs"

    private init() {
        let strings = UserDefaults.standard.stringArray(forKey: key) ?? []
        self.ids = Set(strings.compactMap { UUID(uuidString: $0) })
    }

    func contains(_ id: UUID) -> Bool { ids.contains(id) }

    func toggle(_ id: UUID) {
        if ids.contains(id) {
            ids.remove(id)
        } else {
            ids.insert(id)
        }
        UserDefaults.standard.set(ids.map(\.uuidString), forKey: key)
    }
}
