import Foundation
import Vision
import UIKit

struct PhotoIntelResult: Hashable {
    let score: Int
    let labels: [String]
    let summary: String
}

/// Local photo triage. It deliberately never uploads a photo. The app can later
/// swap the classifier implementation for a Core ML insect model without changing the report UI.
final class PhotoIntelligenceService {
    static let shared = PhotoIntelligenceService()

    func analyze(_ image: UIImage) async -> PhotoIntelResult {
        guard let cgImage = image.cgImage else { return PhotoIntelResult(score: 0, labels: [], summary: "Photo unavailable") }
        let request = VNClassifyImageRequest()
        let handler = VNImageRequestHandler(cgImage: cgImage)
        do {
            try handler.perform([request])
            let labels = (request.results ?? []).prefix(8).map { $0.identifier }
            let insectTerms = labels.filter { $0.localizedCaseInsensitiveContains("insect") || $0.localizedCaseInsensitiveContains("bug") || $0.localizedCaseInsensitiveContains("cockroach") || $0.localizedCaseInsensitiveContains("roach") }
            let score = min(99, 25 + insectTerms.count * 20 + (labels.isEmpty ? 0 : 10))
            return PhotoIntelResult(score: score, labels: Array(labels), summary: insectTerms.isEmpty ? "Photo triaged — no confident roach label from the built-in classifier." : "Photo contains a likely insect-related visual cue.")
        } catch {
            return PhotoIntelResult(score: 0, labels: [], summary: "Photo analysis unavailable")
        }
    }
}
