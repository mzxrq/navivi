import L from "leaflet";

export const waypointIcon = (number: number, hexColor: string) => {
    return L.divIcon({
        className: "custom-marker",
        html: `<div style="background-color: ${hexColor} !important; width: 24px; height: 24px; border: 2px solid white; border-radius: 50%; box-shadow: 0 0 10px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; color: white; font-size: 10px; font-weight: bold;">
            ${number}
           </div>`,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });
};

export const getCurve = (
    start: [number, number],
    end: [number, number],
    segments = 30,
) => {
    const [lat1, lon1] = start;
    const [lat2, lon2] = end;

    const mLat = (lat1 + lat2) / 2;
    const mLon = (lon1 + lon2) / 2;

    const dLat = lat2 - lat1;
    const dLon = lon2 - lon1;
    const ctrlLat = mLat - dLon * 0.2;
    const ctrlLon = mLon + dLat * 0.2;

    const curve: [number, number][] = [];
    for (let i = 0; i <= segments; i++) {
        const t = i / segments;
        const u = 1 - t;
        const lat = u * u * lat1 + 2 * u * t * ctrlLat + t * t * lat2;
        const lon = u * u * lon1 + 2 * u * t * ctrlLon + t * t * lon2;
        curve.push([lat, lon]);
    }
    return curve;
};