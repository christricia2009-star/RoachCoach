import Foundation
import CoreLocation
import UserNotifications

final class GeofenceRadarService: NSObject, CLLocationManagerDelegate {
    static let shared = GeofenceRadarService()
    private let manager = CLLocationManager()
    private let radius: CLLocationDistance = 804.672 // 0.5 mile

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    func requestPermission() {
        manager.requestAlwaysAuthorization()
    }

    func watch(id: UUID, coordinate: CLLocationCoordinate2D, name: String) {
        guard CLLocationManager.isMonitoringAvailable(for: CLCircularRegion.self) else { return }
        let region = CLCircularRegion(center: coordinate, radius: min(radius, manager.maximumRegionMonitoringDistance), identifier: "truck-\(id.uuidString)")
        region.notifyOnEntry = true
        region.notifyOnExit = false
        manager.startMonitoring(for: region)
        UserDefaults.standard.set(name, forKey: "radar.region.\(region.identifier)")
    }

    func stopWatching(id: UUID) {
        for region in manager.monitoredRegions where region.identifier == "truck-\(id.uuidString)" { manager.stopMonitoring(for: region) }
    }

    func locationManager(_ manager: CLLocationManager, didEnterRegion region: CLRegion) {
        let name = UserDefaults.standard.string(forKey: "radar.region.\(region.identifier)") ?? "watched truck"
        let content = UNMutableNotificationContent()
        content.title = "🚨 RADAR CONTACT"
        content.body = "\(name) entered your ½-mile watch zone."
        content.sound = .default
        let request = UNNotificationRequest(identifier: "entry-\(region.identifier)-\(Date().timeIntervalSince1970)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
