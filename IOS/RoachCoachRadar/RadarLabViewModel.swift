import Foundation
import Combine

@MainActor
final class RadarLabViewModel: ObservableObject {
    @Published private(set) var observations: [RadarObservation]
    @Published private(set) var hotspots: [RadarHotspot]
    @Published private(set) var brief: RadarBrief?
    @Published private(set) var simulation: SimulationResult?
    @Published private(set) var lastUpdated: Date?

    init() {
        self.observations = []
        self.hotspots = []
        self.brief = nil
        self.simulation = nil
        self.lastUpdated = nil
    }

    func ingest(_ incoming: [RadarObservation]) {
        let combined = incoming + observations
        var uniqueByID: [UUID: RadarObservation] = [:]
        for observation in combined {
            uniqueByID[observation.id] = observation
        }

        observations = Array(uniqueByID.values)
            .sorted { $0.observedAt > $1.observedAt }
            .prefix(1000)
            .map { $0 }

        hotspots = HotspotEngine.shared.hotspots(observations: observations)
        brief = WhatIsHotEngine.shared.brief(observations: observations)
        simulation = SimulationEngine.shared.replay(observations: observations)
        lastUpdated = .now
    }

    func replay() {
        simulation = SimulationEngine.shared.replay(observations: observations)
    }
}
