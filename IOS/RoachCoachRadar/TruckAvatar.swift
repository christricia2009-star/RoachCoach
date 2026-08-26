import SwiftUI

/// Instagram (or CloudKit) profile photo when we have one; truck glyph otherwise.
struct TruckAvatar: View {
    let truck: Truck
    var size: CGFloat = 48

    var body: some View {
        Group {
            if let url = truck.socialImageURL {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                    default:
                        placeholder
                    }
                }
            } else {
                placeholder
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: max(8, size * 0.22), style: .continuous))
    }

    private var placeholder: some View {
        ZStack {
            RoundedRectangle(cornerRadius: max(8, size * 0.22), style: .continuous)
                .fill(Color.orange.opacity(0.15))
            Image(systemName: "truck.box.fill")
                .font(size >= 64 ? .title : .title3)
                .foregroundStyle(.orange)
        }
    }
}
