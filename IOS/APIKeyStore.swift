import Foundation
import Combine
import Security

/// User-entered provider credentials are stored in the iOS Keychain.
/// They are never included in source control or the application bundle.
final class APIKeyStore: ObservableObject {
    static let shared = APIKeyStore()

    @Published var backendURL: String { didSet { save(backendURL, key: Keys.backendURL) } }
    @Published var openRouterKey: String { didSet { save(openRouterKey, key: Keys.openRouter) } }
    @Published var xAIKey: String { didSet { save(xAIKey, key: Keys.xAI) } }
    @Published var anthropicKey: String { didSet { save(anthropicKey, key: Keys.anthropic) } }
    @Published var instagramToken: String { didSet { save(instagramToken, key: Keys.instagram) } }
    @Published var xBearerToken: String { didSet { save(xBearerToken, key: Keys.xBearer) } }
    @Published var partnershipKey: String { didSet { save(partnershipKey, key: Keys.partnership) } }
    @Published var partnershipURL: String { didSet { save(partnershipURL, key: Keys.partnershipURL) } }
    @Published var municipalAppToken: String { didSet { save(municipalAppToken, key: Keys.municipalToken) } }
    @Published var municipalDatasetURL: String { didSet { save(municipalDatasetURL, key: Keys.municipalURL) } }
    @Published var telecomKey: String { didSet { save(telecomKey, key: Keys.telecom) } }
    @Published var telecomURL: String { didSet { save(telecomURL, key: Keys.telecomURL) } }
    @Published var uberClientID: String { didSet { save(uberClientID, key: Keys.uberID) } }
    @Published var uberClientSecret: String { didSet { save(uberClientSecret, key: Keys.uberSecret) } }
    @Published var uberURL: String { didSet { save(uberURL, key: Keys.uberURL) } }
    @Published var doorDashKey: String { didSet { save(doorDashKey, key: Keys.doorDash) } }
    @Published var doorDashURL: String { didSet { save(doorDashURL, key: Keys.doorDashURL) } }
    @Published var s3BucketName: String { didSet { save(s3BucketName, key: Keys.s3Bucket) } }
    @Published var awsAccessKey: String { didSet { save(awsAccessKey, key: Keys.awsAccess) } }
    @Published var awsSecretKey: String { didSet { save(awsSecretKey, key: Keys.awsSecret) } }
    @Published var llmStrategy: String { didSet { save(llmStrategy, key: Keys.llmStrategy) } }
    @Published var llmProvider: String { didSet { save(llmProvider, key: Keys.llmProvider) } }
    @Published var llmModel: String { didSet { save(llmModel, key: Keys.llmModel) } }

    private enum Keys {
        static let backendURL = "backendURL", openRouter = "openRouterKey", xAI = "xAIKey", anthropic = "anthropicKey"
        static let instagram = "instagramToken", xBearer = "xBearerToken", partnership = "partnershipKey", partnershipURL = "partnershipURL"
        static let municipalToken = "municipalAppToken", municipalURL = "municipalDatasetURL", telecom = "telecomKey", telecomURL = "telecomURL"
        static let uberID = "uberClientID", uberSecret = "uberClientSecret", uberURL = "uberURL"
        static let doorDash = "doorDashKey", doorDashURL = "doorDashURL", s3Bucket = "s3BucketName"
        static let awsAccess = "awsAccessKey", awsSecret = "awsSecretKey", llmStrategy = "llmStrategy", llmProvider = "llmProvider", llmModel = "llmModel"
    }

    private let service = "com.roachcoachradar.credentials"

    private init() {
        backendURL = Self.read(Keys.backendURL) ?? ""
        openRouterKey = Self.read(Keys.openRouter) ?? ""
        xAIKey = Self.read(Keys.xAI) ?? ""
        anthropicKey = Self.read(Keys.anthropic) ?? ""
        instagramToken = Self.read(Keys.instagram) ?? ""
        xBearerToken = Self.read(Keys.xBearer) ?? ""
        partnershipKey = Self.read(Keys.partnership) ?? ""
        partnershipURL = Self.read(Keys.partnershipURL) ?? ""
        municipalAppToken = Self.read(Keys.municipalToken) ?? ""
        municipalDatasetURL = Self.read(Keys.municipalURL) ?? ""
        telecomKey = Self.read(Keys.telecom) ?? ""
        telecomURL = Self.read(Keys.telecomURL) ?? ""
        uberClientID = Self.read(Keys.uberID) ?? ""
        uberClientSecret = Self.read(Keys.uberSecret) ?? ""
        uberURL = Self.read(Keys.uberURL) ?? ""
        doorDashKey = Self.read(Keys.doorDash) ?? ""
        doorDashURL = Self.read(Keys.doorDashURL) ?? ""
        s3BucketName = Self.read(Keys.s3Bucket) ?? ""
        awsAccessKey = Self.read(Keys.awsAccess) ?? ""
        awsSecretKey = Self.read(Keys.awsSecret) ?? ""
        llmStrategy = Self.read(Keys.llmStrategy) ?? "fallback"
        llmProvider = Self.read(Keys.llmProvider) ?? "anthropic"
        llmModel = Self.read(Keys.llmModel) ?? ""
    }

    func clearAll() {
        let all = [
            Keys.backendURL,
            Keys.openRouter,
            Keys.xAI,
            Keys.anthropic,
            Keys.instagram,
            Keys.xBearer,
            Keys.partnership,
            Keys.partnershipURL,
            Keys.municipalToken,
            Keys.municipalURL,
            Keys.telecom,
            Keys.telecomURL,
            Keys.uberID,
            Keys.uberSecret,
            Keys.uberURL,
            Keys.doorDash,
            Keys.doorDashURL,
            Keys.s3Bucket,
            Keys.awsAccess,
            Keys.awsSecret,
            Keys.llmStrategy,
            Keys.llmProvider,
            Keys.llmModel
        ]

        for key in all {
            Self.delete(key)
        }

        backendURL = ""
        openRouterKey = ""
        xAIKey = ""
        anthropicKey = ""
        instagramToken = ""
        xBearerToken = ""
        partnershipKey = ""
        partnershipURL = ""

        municipalAppToken = ""
        municipalDatasetURL = ""
        telecomKey = ""
        telecomURL = ""
        uberClientID = ""
        uberClientSecret = ""
        uberURL = ""

        doorDashKey = ""
        doorDashURL = ""
        s3BucketName = ""
        awsAccessKey = ""
        awsSecretKey = ""

        llmStrategy = "fallback"
        llmProvider = "anthropic"
        llmModel = ""
    }
    func headers() -> [String: String] {
        let values = [
            "X-RCR-OpenRouter-Key": openRouterKey, "X-RCR-XAI-Key": xAIKey, "X-RCR-Anthropic-Key": anthropicKey,
            "X-RCR-Instagram-Token": instagramToken, "X-RCR-X-Bearer": xBearerToken, "X-RCR-Partnership-Key": partnershipKey,
            "X-RCR-Partnership-URL": partnershipURL, "X-RCR-Municipal-Token": municipalAppToken, "X-RCR-Municipal-URL": municipalDatasetURL,
            "X-RCR-Telecom-Key": telecomKey, "X-RCR-Telecom-URL": telecomURL, "X-RCR-Uber-ID": uberClientID, "X-RCR-Uber-Secret": uberClientSecret,
            "X-RCR-Uber-URL": uberURL, "X-RCR-DoorDash-Key": doorDashKey, "X-RCR-DoorDash-URL": doorDashURL,
            "X-RCR-S3-Bucket": s3BucketName, "X-RCR-AWS-Access": awsAccessKey, "X-RCR-AWS-Secret": awsSecretKey,
            "X-RCR-LLM-Strategy": llmStrategy, "X-RCR-LLM-Provider": llmProvider, "X-RCR-LLM-Model": llmModel
        ]
        return values.filter { !$0.value.isEmpty }
    }

    private func save(_ value: String, key: String) {
        guard !value.isEmpty else { Self.delete(key); return }
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
        SecItemDelete(query as CFDictionary)
        let item = query.merging([kSecValueData as String: Data(value.utf8)]) { _, new in new }
        SecItemAdd(item as CFDictionary, nil)
    }

    private static func read(_ key: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.roachcoachradar.credentials", kSecAttrAccount as String: key, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func delete(_ key: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.roachcoachradar.credentials", kSecAttrAccount as String: key]
        SecItemDelete(query as CFDictionary)
    }
}
