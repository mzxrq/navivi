// src/services/weatherService.ts
// Historical Weather Sync service integrating with Open-Meteo Archive API and Mapbox atmosphere

export type WeatherCondition = "clear" | "rain" | "fog";

export interface MapboxAtmosphereParams {
  fog: {
    color: string;
    "high-color": string;
    "horizon-blend": number;
    "space-color": string;
    "star-intensity": number;
  } | null;
  rainOverlay: boolean;
}

/**
 * Builds the Open-Meteo historical archive query URL for a given coordinate and timestamp.
 */
export function buildOpenMeteoArchiveUrl(
  lat: number,
  lng: number,
  isoTimestamp: string
): string {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    throw new Error("Invalid coordinates for weather query");
  }
  if (!isoTimestamp) {
    throw new Error("Missing timestamp for historical weather query");
  }

  const dateObj = new Date(isoTimestamp);
  if (Number.isNaN(dateObj.getTime())) {
    throw new Error("Invalid ISO timestamp format");
  }

  const dateStr = dateObj.toISOString().split("T")[0];
  return `https://archive-api.open-meteo.com/v1/archive?latitude=${lat.toFixed(4)}&longitude=${lng.toFixed(4)}&start_date=${dateStr}&end_date=${dateStr}&hourly=weather_code,precipitation,cloud_cover`;
}

/**
 * Maps standard WMO Weather interpretation codes (WW) to visual conditions.
 */
export function mapWmoCodeToWeatherCondition(
  wmoCode: number | null | undefined
): WeatherCondition {
  if (wmoCode === null || wmoCode === undefined || !Number.isFinite(wmoCode)) {
    return "clear";
  }

  // WMO Weather interpretation codes (WW)
  // 0: Clear sky; 1, 2, 3: Mainly clear, partly cloudy, and overcast
  if (wmoCode >= 0 && wmoCode <= 3) return "clear";

  // 45, 48: Fog and depositing rime fog
  if (wmoCode === 45 || wmoCode === 48) return "fog";

  // 51-67: Drizzle and Rain; 80-82: Rain showers; 95-99: Thunderstorms
  if (
    (wmoCode >= 51 && wmoCode <= 67) ||
    (wmoCode >= 80 && wmoCode <= 82) ||
    (wmoCode >= 95 && wmoCode <= 99)
  ) {
    return "rain";
  }

  // 71-77, 85-86: Snowfall and snow showers
  if ((wmoCode >= 71 && wmoCode <= 77) || (wmoCode >= 85 && wmoCode <= 86)) {
    return "fog"; // Atmospheric precipitation effect
  }

  return "clear";
}

/**
 * Generates Mapbox atmosphere (setFog) parameters and canvas overlay flags.
 */
export function generateMapboxAtmosphereParams(
  condition: WeatherCondition
): MapboxAtmosphereParams {
  switch (condition) {
    case "fog":
      return {
        fog: {
          color: "rgb(200, 205, 215)",
          "high-color": "rgb(150, 160, 175)",
          "horizon-blend": 0.1,
          "space-color": "rgb(180, 190, 200)",
          "star-intensity": 0.0,
        },
        rainOverlay: false,
      };
    case "rain":
      return {
        fog: {
          color: "rgb(170, 180, 190)",
          "high-color": "rgb(120, 130, 140)",
          "horizon-blend": 0.08,
          "space-color": "rgb(140, 150, 160)",
          "star-intensity": 0.0,
        },
        rainOverlay: true,
      };
    case "clear":
    default:
      return {
        fog: null, // Clear sky / default Mapbox atmosphere
        rainOverlay: false,
      };
  }
}

/**
 * Queries Open-Meteo historical archive API with a 4-second timeout guarantee.
 * Gracefully catches all network errors, timeouts, or invalid payloads and falls back to "clear".
 */
export async function getHistoricalWeather(
  lat: number,
  lng: number,
  timestamp: string
): Promise<WeatherCondition> {
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || !timestamp) {
    return "clear";
  }

  const dateObj = new Date(timestamp);
  if (Number.isNaN(dateObj.getTime())) {
    return "clear";
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 4000);

  try {
    const url = buildOpenMeteoArchiveUrl(lat, lng, timestamp);
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!response.ok) {
      return "clear";
    }

    const data = await response.json();
    if (!data || !data.hourly || !Array.isArray(data.hourly.weather_code)) {
      return "clear";
    }

    const targetHour = dateObj.getUTCHours();
    let index = targetHour;

    if (Array.isArray(data.hourly.time) && data.hourly.time.length > 0) {
      const isoHourStr = dateObj.toISOString().slice(0, 13);
      const foundIdx = data.hourly.time.findIndex((t: string) =>
        t.startsWith(isoHourStr)
      );
      if (foundIdx !== -1) {
        index = foundIdx;
      } else if (index >= data.hourly.weather_code.length) {
        index = 0;
      }
    } else if (index >= data.hourly.weather_code.length) {
      index = 0;
    }

    const precip = data.hourly.precipitation?.[index];
    if (typeof precip === "number" && precip > 1.0) {
      return "rain";
    }

    const code = data.hourly.weather_code[index];
    return mapWmoCodeToWeatherCondition(code);
  } catch (_err) {
    clearTimeout(timeoutId);
    return "clear";
  }
}
