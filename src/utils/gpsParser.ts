export interface GpsPoint {
    lat: number;
    lng: number;
    ele?: number;
    time?: number;
}

export interface ParsedGpsData {
    projectName: string;
    points: [number, number][]; // This is [lat, lng] array for Map Rendering
    waypoints: {
        id: string;
        name: string;
        lat: number;
        lng: number;
        routeMode: "driving" | "walking" | "direct" | "curve" | "ferry" | "calculating";
        images: string[];
        imagePans: string[];
        narration: string;
    }[];
    summary: {
        totalDistanceKm: number;
        pointCount: number; // lat, lng array count
    }
}

/**
 * Calculate Haversine distance between 2 coords in ㌔
 */

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const R = 6371; // Earth radius in km
    const dLat = (lat2 - lat1) * (Math.PI / 180);
    const dLon = (lon2 - lon1) * (Math.PI / 180);
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

/**
 * Parses raw GPX XML string into structured GPS data and waypoints.
 */

export function parseGpxString(xmlContent: string): ParsedGpsData {
    const parser = new DOMParser();
    const xmlDoc = parser.parseFromString(xmlContent, "text/xml");

    const nameNode = xmlDoc.querySelector("trk > name") || xmlDoc.querySelector("name");
    const projectName = nameNode?.textContent?.trim() || "GPXルートをアップロードされました。"

    //　Extract Track Points <trkpt>
    const trkptNodes = xmlDoc.querySelectorAll("trkpt");
    const rawPoints: [number, number][] = [];

    trkptNodes.forEach((pt) => {
        const lat = parseFloat(pt.getAttribute("lat") || "0");
        const lon = parseFloat(pt.getAttribute("lon") || "0");
        if (!isNaN(lat) && !isNaN(lon)) {
            rawPoints.push([lat, lon]);
        }
    });

    // Extract Named Waypoints 
    const wptNodes = xmlDoc.querySelectorAll("wpt");
    const waypoints: ParsedGpsData["waypoints"] = [];

    wptNodes.forEach((wpt, index) => {
        const lat = parseFloat(wpt.getAttribute("lat") || "0");
        const lng = parseFloat(wpt.getAttribute("lon") || "0");
        const name = wpt.querySelector("name")?.textContent?.trim() || `Stop ${index + 1}`;

        if (!isNaN(lat) && !isNaN(lng)) {
            waypoints.push({
                id: `wp_${Date.now()}_${index}`,
                name, lat, lng, routeMode: "walking", images: [], imagePans: [], narration: "",
            });
        }
    });

    // if no <wpt> tags were detected in GPX, auto generate start and end waypoints from the track
    if (waypoints.length === 0 && rawPoints.length > 0) {
        waypoints.push({
            id: `wp_${Date.now()}_start`,
            name: "Start Point", lat: rawPoints[0][0], lng: rawPoints[0][1],
            routeMode: "walking", images: [], imagePans: [], narration: "",
        });

        waypoints.push({
            id: `wp_${Date.now()}_end`,
            name: "End Point", lat: rawPoints[rawPoints.length - 1][0], lng: rawPoints[rawPoints.length - 1][1],
            routeMode: "driving", images: [], imagePans: [], narration: "",
        });
    }

    // calculate total distance
    let totalDistanceKm = 0;
    for (let i = 0; i < rawPoints.length - 1; i++) {
        totalDistanceKm += haversineKm(
            rawPoints[i][0],
            rawPoints[i][1],
            rawPoints[i + 1][0],
            rawPoints[i + 1][1]
        );
    }

    return {
        projectName, points: rawPoints, waypoints, summary: {
            totalDistanceKm: parseFloat(totalDistanceKm.toFixed(2)), pointCount: rawPoints.length,
        },
    };
}

export function parseNmeaString(nmeaContent: string): ParsedGpsData {
    const lines = nmeaContent.split('\n');
    const rawPoints: [number, number][] = [];
  
    // Helper to convert NMEA 3427.8029,N -> 34.463381
    const convertToDecimal = (nmeaPos: string, dir: string) => {
      if (!nmeaPos) return 0;
      const dotIdx = nmeaPos.indexOf('.');
      const degrees = parseFloat(nmeaPos.substring(0, dotIdx - 2));
      const minutes = parseFloat(nmeaPos.substring(dotIdx - 2));
      let decimal = degrees + minutes / 60;
      if (dir === 'S' || dir === 'W') decimal *= -1;
      return decimal;
    };
  
    lines.forEach(line => {
      if (line.startsWith('$GNGGA') || line.startsWith('$GPGGA')) {
        const parts = line.split(',');
        // parts[2] = Lat, parts[3] = N/S, parts[4] = Lng, parts[5] = E/W
        if (parts[2] && parts[4]) {
          const lat = convertToDecimal(parts[2], parts[3]);
          const lng = convertToDecimal(parts[4], parts[5]);
          rawPoints.push([lat, lng]);
        }
      }
    });
  
    // Calculate Total Distance using the Haversine function we wrote earlier
    let totalDistanceKm = 0;
    for (let i = 0; i < rawPoints.length - 1; i++) {
      totalDistanceKm += haversineKm(rawPoints[i][0], rawPoints[i][1], rawPoints[i+1][0], rawPoints[i+1][1]);
    }
  
    return {
      projectName: "Raw Satellite Log",
      points: rawPoints,
      waypoints: [
        { id: "start", name: "Log Start", lat: rawPoints[0][0], lng: rawPoints[0][1], routeMode: "driving", images: [], imagePans: [], narration: "" },
        { id: "end", name: "Log End", lat: rawPoints[rawPoints.length-1][0], lng: rawPoints[rawPoints.length-1][1], routeMode: "driving", images: [], imagePans: [], narration: "" },
      ],
      summary: {
        totalDistanceKm: parseFloat(totalDistanceKm.toFixed(2)),
        pointCount: rawPoints.length,
      }
    };
  }

  export function parseKmlString(xmlContent: string): ParsedGpsData {
    const parser = new DOMParser();
    const xmlDoc = parser.parseFromString(xmlContent, "text/xml");
    
    const nameNode = xmlDoc.querySelector("Document > name");
    const projectName = nameNode?.textContent?.trim() || "Uploaded KML Route";
  
    const rawPoints: [number, number][] = [];
    
    // KML stores coordinates as a single giant string: "lon,lat,ele lon,lat,ele ..."
    const coordsNode = xmlDoc.querySelector("LineString coordinates");
    if (coordsNode && coordsNode.textContent) {
      const coordPairs = coordsNode.textContent.trim().split(/\s+/);
      coordPairs.forEach(pair => {
        const [lon, lat] = pair.split(',').map(parseFloat);
        if (!isNaN(lat) && !isNaN(lon)) rawPoints.push([lat, lon]);
      });
    }
  
    // Calculate distance...
    let totalDistanceKm = 0;
    for (let i = 0; i < rawPoints.length - 1; i++) {
      totalDistanceKm += haversineKm(rawPoints[i][0], rawPoints[i][1], rawPoints[i+1][0], rawPoints[i+1][1]);
    }
  
    return {
      projectName,
      points: rawPoints,
      waypoints: [
        { id: "start", name: "Start", lat: rawPoints[0][0], lng: rawPoints[0][1], routeMode: "driving", images: [], imagePans: [], narration: "" },
        { id: "end", name: "End", lat: rawPoints[rawPoints.length-1][0], lng: rawPoints[rawPoints.length-1][1], routeMode: "driving", images: [], imagePans: [], narration: "" }
      ],
      summary: { totalDistanceKm: parseFloat(totalDistanceKm.toFixed(2)), pointCount: rawPoints.length }
    };
  }