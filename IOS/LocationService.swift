import Foundation
import CoreLocation
import Combine
import MapKit

enum MapsLauncher {
    static func directions(to coordinate: CLLocationCoordinate2D, name: String) {
        let item = MKMapItem(placemark: MKPlacemark(coordinate: coordinate))
        item.name = name
        item.openInMaps(launchOptions: [
            MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving
        ])
    }
}

/// Wraps CLLocationManager so views can get the user's real device location
/// (works in the Simulator too — Debug menu → Features → Location → choose
/// a simulated location, or "Apple" for a default). Used for map centering
/// and live distance-to-truck calculations.
final class LocationService: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = LocationService()

    @Published var currentLocation: CLLocation?
    @Published var authorizationStatus: CLAuthorizationStatus = .notDetermined

    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func requestPermission() {
        manager.requestWhenInUseAuthorization()
    }

    func startUpdating() {
        manager.startUpdatingLocation()
    }

    func distance(to coordinate: CLLocationCoordinate2D) -> CLLocationDistance? {
        guard let current = currentLocation else { return nil }
        let target = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        return current.distance(from: target)
    }

    /// Human-readable distance, e.g. "0.4 mi away" or "350 m away"
    func formattedDistance(to coordinate: CLLocationCoordinate2D, useMetric: Bool = false) -> String? {
        guard let meters = distance(to: coordinate) else { return nil }
        if useMetric {
            if meters >= 1000 {
                return String(format: "%.1f km away", meters / 1000)
            }
            return String(format: "%.0f m away", meters)
        } else {
            let miles = meters / 1609.34
            if miles < 0.1 {
                return "Very close"
            }
            return String(format: "%.1f mi away", miles)
        }
    }

    /// Rough walking ETA assuming ~3 mph average pace — a real implementation
    /// should use MKDirections for an actual route-based estimate.
    func estimatedWalkingMinutes(to coordinate: CLLocationCoordinate2D) -> Int? {
        guard let meters = distance(to: coordinate) else { return nil }
        let milesPerHourWalking = 3.0
        let miles = meters / 1609.34
        let hours = miles / milesPerHourWalking
        return max(1, Int((hours * 60).rounded()))
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        currentLocation = locations.last
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        authorizationStatus = status
        if status == .authorizedWhenInUse || status == .authorizedAlways {
            startUpdating()
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        authorizationStatus = manager.authorizationStatus
        if manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways {
            startUpdating()
        }
    }
}
