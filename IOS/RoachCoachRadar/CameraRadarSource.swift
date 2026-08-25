import Foundation

struct CameraRadarSource: RadarSource {
    let id="caltrans-cameras"; let displayName="California traffic cameras"
    let endpoint:String
    func collect(latitude:Double,longitude:Double,radiusMiles:Double) async throws -> [RadarObservation] {
        guard var c = URLComponents(string:endpoint) else{throw URLError(.badURL)}
        c.queryItems = [URLQueryItem(name:"latitude",value:"\(latitude)"),URLQueryItem(name:"longitude",value:"\(longitude)"),URLQueryItem(name:"radius_miles",value:"\(radiusMiles)")]
        let (data,response)=try await URLSession.shared.data(from:c.url!)
        guard let h = response as? HTTPURLResponse,(200..<300).contains(h.statusCode) else{throw URLError(.badServerResponse)}
        let cams = try JSONDecoder().decode([CameraDTO].self,from:data)
        return cams.map{RadarObservation(source:.camera,sourceID:$0.id ?? "camera",latitude:$0.latitude,longitude:$0.longitude,text:$0.locationName,sourceURL:$0.currentImageURL,rawConfidence:0.7,metadata:["route":$0.route ?? ""])}
    }
    struct CameraDTO:Decodable { let id:String?; let locationName:String; let latitude:Double; let longitude:Double; let currentImageURL:String?; let route:String?; enum CodingKeys:String,CodingKey{case id,locationName="location_name",latitude,longitude,currentImageURL="current_image_url",route} }
}
