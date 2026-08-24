import Foundation
import Combine
import NetworkExtension

/// Wi-Fi-based truck detection — consent-gated per your note that this is
/// fine "as long as notice is made and accepted."
///
/// IMPORTANT TECHNICAL LIMIT — read before building on this further:
/// Consent solves the PRIVACY/policy side of this idea, but there's a
/// separate OS-level restriction that consent doesn't remove: iOS does NOT
/// give ordinary apps an API to scan for or list NEARBY Wi-Fi networks the
/// device hasn't joined (unlike Android's WifiManager.getScanResults()).
/// The only thing this code CAN legitimately do is check the SSID of the
/// network the device is CURRENTLY CONNECTED TO, via
/// NEHotspotNetwork.fetchCurrent() — which requires:
///   1. The "Access WiFi Information" capability (Xcode → Signing &
///      Capabilities → + Capability)
///   2. Location permission granted (iOS ties Wi-Fi info to location
///      privacy, since SSIDs can reveal location)
///   3. The user's device to have ALREADY manually joined that specific
///      truck's Wi-Fi network — this code cannot detect a truck's hotspot
///      "nearby" without the phone being connected to it.
///
/// There IS an Apple API for broader passive network detection
/// (NEHotspotHelper), but it requires a special entitlement Apple grants
/// only in narrow, typically enterprise/carrier use cases — not something
/// to plan around for a family app. If you want real "nearby truck Wi-Fi"
/// detection, the realistic path is: trucks broadcast a specific SSID
/// pattern (e.g. "RoachCoach-BaoBaoBus"), and app users who want this
/// feature manually join it once (like joining any public Wi-Fi) — at
/// which point this code can recognize it and treat it as a sighting.
/// That's a meaningfully different (and much smaller) feature than
/// automatic proximity detection — size expectations accordingly.
final class WiFiDetectionService: NSObject, ObservableObject {
    static let shared = WiFiDetectionService()

    @Published var hasUserConsented: Bool {
        didSet { UserDefaults.standard.set(hasUserConsented, forKey: consentKey) }
    }

    private let consentKey = "wifiDetectionConsentGiven"

    // Known truck hotspot SSIDs — populate as trucks in your family/friends
    // pilot actually set up recognizable network names (e.g. for menu QR
    // codes). This is illustrative; there's no way to discover these
    // automatically without the truck owner telling you their SSID.
    var knownTruckSSIDs: [String: UUID] = [:]  // SSID -> Truck ID

    override init() {
        self.hasUserConsented = UserDefaults.standard.bool(forKey: consentKey)
        super.init()
    }

    func grantConsent() {
        hasUserConsented = true
    }

    func revokeConsent() {
        hasUserConsented = false
    }

    /// Checks the CURRENTLY CONNECTED network only — see class docs for why
    /// this can't do broader nearby-network scanning on iOS.
    func checkCurrentNetworkForKnownTruck(completion: @escaping (UUID?) -> Void) {
        guard hasUserConsented else {
            completion(nil)
            return
        }

        NEHotspotNetwork.fetchCurrent { network in
            guard let ssid = network?.ssid else {
                completion(nil)
                return
            }
            completion(self.knownTruckSSIDs[ssid])
        }
    }
}
