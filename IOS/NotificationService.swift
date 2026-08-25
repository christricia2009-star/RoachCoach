import Foundation
import UserNotifications

/// Schedules REAL local notifications — these actually fire on-device with
/// zero backend, zero APNs setup, zero Apple Developer account needed.
/// This is what "your favorite truck just got spotted" feels like today;
/// swap to remote push (see Docs/SETUP_INSTRUCTIONS.md Part 4) once you
/// have a live backend and want notifications to fire even when a truck is
/// spotted by someone else's device, not just this simulator/session.
final class NotificationService {
    static let shared = NotificationService()

    func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, error in
            if let error = error {
                print("Notification permission error: \(error)")
            }
        }
    }

    /// Fires a notification a few seconds from now to simulate "a favorited
    /// truck was just spotted" — call this right after a user favorites a
    /// truck (demo) or, in the live-backend version, from a background
    /// fetch / silent push handler that detects a new confirmed sighting.
    func scheduleTruckSpottedNotification(truckName: String, note: String?, delaySeconds: TimeInterval = 3) {
        let content = UNMutableNotificationContent()
        content.title = "\(truckName) was just spotted!"
        content.body = note ?? "A new sighting was just reported nearby."
        content.sound = .default

        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: delaySeconds, repeats: false)
        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: trigger
        )

        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                print("Failed to schedule notification: \(error)")
            }
        }
    }
}
