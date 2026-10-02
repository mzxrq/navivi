// Smallest to largest, so a nameless spot is called after its neighbourhood before its city.
const AREAS = ["neighbourhood", "quarter", "suburb", "hamlet", "village", "town", "city_district", "city", "municipality", "county"];

// A name for a Nominatim reverse-geocoding reply: the place's own name, then its street, then the smallest area it sits in.
export function placeNameOf(reply: any, fallback: string): string {
  const address = reply?.address ?? {};
  const area = AREAS.map((key) => address[key]).find(Boolean);
  return reply?.name || address.road || area || fallback;
}
