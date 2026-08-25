import SwiftUI

struct WhatIsHotView: View {
    let observations:[RadarObservation]
    var body: some View {
        let brief=WhatIsHotEngine.shared.brief(observations:observations)
        VStack(spacing:16) {
            Image(systemName:"flame.fill").font(.system(size:60)).foregroundStyle(.orange)
            Text(brief.title).font(.largeTitle.bold())
            Text(brief.detail).multilineTextAlignment(.center).foregroundStyle(.secondary)
            Text("\(brief.score)% SIGNAL").font(.title3.monospaced().bold())
        }.padding().navigationTitle("What's Hot")
    }
}
