import Foundation

enum APIKeyCheckResult: Equatable {
    case unchecked
    case checking
    case valid
    case invalid(String)   // short reason, e.g. "401 Unauthorized"

    var isValid: Bool { self == .valid }
}

/// Lightweight, read-only calls against each AI provider's own API to
/// confirm a key actually authenticates — no completion tokens spent.
/// Runs directly from the app, same posture as the rest of Settings
/// ("the backend only gets the credentials a scan needs" — this never
/// touches our backend at all, it talks to the provider directly).
enum APIKeyValidator {

    static func check(provider: String, key: String) async -> APIKeyCheckResult {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return .invalid("No key entered") }

        switch provider {
        case "anthropic": return await checkAnthropic(trimmed)
        case "grok":       return await checkXAI(trimmed)
        case "openrouter": return await checkOpenRouter(trimmed)
        case "instagram":  return await checkInstagram(trimmed)
        case "facebook":   return await checkFacebook(trimmed)
        default:           return .invalid("Unknown provider")
        }
    }

    private static func checkAnthropic(_ key: String) async -> APIKeyCheckResult {
        guard var request = makeRequest("https://api.anthropic.com/v1/models") else {
            return .invalid("Bad URL")
        }
        request.setValue(key, forHTTPHeaderField: "x-api-key")
        request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        return await run(request)
    }

    private static func checkXAI(_ key: String) async -> APIKeyCheckResult {
        guard var request = makeRequest("https://api.x.ai/v1/models") else {
            return .invalid("Bad URL")
        }
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        return await run(request)
    }

    private static func checkFacebook(_ key: String) async -> APIKeyCheckResult {
        var comps = URLComponents(string: "https://graph.facebook.com/v25.0/me")
        comps?.queryItems = [
            URLQueryItem(name: "fields", value: "id,name"),
            URLQueryItem(name: "access_token", value: key),
        ]
        guard let url = comps?.url else { return .invalid("Bad URL") }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 10
        return await run(request)
    }

    private static func checkInstagram(_ key: String) async -> APIKeyCheckResult {
        // IGA… = Instagram Login (graph.instagram.com).
        // EAA… = Facebook Login / Page token (graph.facebook.com).
        let host = key.uppercased().hasPrefix("EAA")
            ? "https://graph.facebook.com/v25.0/me"
            : "https://graph.instagram.com/v25.0/me"
        var comps = URLComponents(string: host)
        comps?.queryItems = [
            URLQueryItem(name: "fields", value: "id,username"),
            URLQueryItem(name: "access_token", value: key),
        ]
        guard let url = comps?.url else { return .invalid("Bad URL") }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 10
        return await run(request)
    }

    private static func checkOpenRouter(_ key: String) async -> APIKeyCheckResult {
        // OpenRouter's own key-introspection endpoint — purpose-built for
        // exactly this ("is this key valid, and what's left on it").
        guard var request = makeRequest("https://openrouter.ai/api/v1/auth/key") else {
            return .invalid("Bad URL")
        }
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        return await run(request)
    }

    private static func makeRequest(_ url: String) -> URLRequest? {
        guard let u = URL(string: url) else { return nil }
        var request = URLRequest(url: u)
        request.httpMethod = "GET"
        request.timeoutInterval = 10
        return request
    }

    private static func run(_ request: URLRequest) async -> APIKeyCheckResult {
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return .invalid("No response")
            }
            switch http.statusCode {
            case 200..<300:
                return .valid
            case 401, 403:
                return .invalid("Rejected (\(http.statusCode))")
            case 429:
                // Rate-limited implies the key itself authenticated fine.
                return .valid
            default:
                return .invalid("HTTP \(http.statusCode)")
            }
        } catch {
            return .invalid(error.localizedDescription)
        }
    }
}

