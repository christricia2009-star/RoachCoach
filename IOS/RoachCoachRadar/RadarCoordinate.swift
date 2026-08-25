import Foundation
import CoreLocation

struct RadarCoordinate: Sendable, Hashable, Codable {
    let latitude: Double
    let longitude: Double
    init(latitude: Double, longitude: Double) { self.latitude = latitude; self.longitude = longitude }
    init(_ c: CLLocationCoordinate2D) { self.init(latitude:c.latitude, longitude:c.longitude) }
    var clLocation: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude:latitude, longitude:longitude) }
    var location: CLLocation { CLLocation(latitude:latitude, longitude:longitude) }
}
