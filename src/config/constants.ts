export const appConfig = {
    name: "Navivi",
    version: "1.0.0", // await syncing with package.json
    defaultProjectName: "Untitled Project",
    defaultUserId: "local",
};

export const fileSystem = {
    rootFolder: "Navivi",
    projectsFolder: "Projects",
    workspacesFolder: "Workspaces",
    assetsFolder: "assets",
    configFile: "job_config.json",
    // Everything generated for bookkeeping (route cache, narration cues, asset manifest, gps data).
    metaFolder: ".navivi",
    cacheFolder: "Cache",
    gpxFile: "raw_track.gpx",
    extensions: {
        project: "nvv",
    },
};

// App-wide pronunciation words (app settings database); saved into every project as settings.global_pronunciation_dictionary.
export const GLOBAL_DICTIONARY_KEY = "pronunciation_dictionary";

export const mapDefaults = {
    startCoords: [34.6937, 135.5023] as [number, number],
    zoomLevel: 10,
    maxImagesPerWaypoint: 3,
};

export const apiEndpoints = {
    orsBase: "https://api.openrouteservice.org/v2/directions",
    nominatimReverse: "https://nominatim.openstreetmap.org/reverse",
};

export const defaultProjectSettings = {
    fps: 30,
    line_color: [0, 200, 255] as [number, number, number],
    line_thickness: 6,
    route_line_border_color: [255, 255, 255] as [number, number, number],
    route_line_border_thickness: 0,
    marker_color: [0, 0, 255] as [number, number, number],
    routeMarker: "",
    pause: 2.0,
    summary_hold: 4.0,
    summary_fade: 0.5,
    auto_save_interval: 3,
    show_route_heatmap: false,
    quick_export: false,
    video_text_language: "auto" as "auto" | "en" | "ja",
    hardware_spec_override: "auto" as "auto" | "high" | "low",
    ai_features_enabled: true,
};

type Rgb = [number, number, number];

// What the Python renderer does when a "Look of the video" key is missing (tuning.py and the readers' own fallbacks, colors
// as RGB). The Project settings dialog shows these for unset keys and never writes one until the user changes it, so a
// project saved before the controls existed renders exactly as before. src-python/tests/test_look_options.py keeps the
// forwarded keys honest; change both sides together.
export const videoLookDefaults = {
    summary_card_style: "columns" as "glass" | "taskbar" | "stacked" | "columns",
    theme: "dark" as "light" | "dark",
    card_border_color: [230, 230, 230] as Rgb,
    card_border_thickness: 1,
    map_font_size: 24,
    show_compass: true,
    waypoint_map_border: true,
    waypoint_intro_freeze: 2.0,
    show_leg_wide_intro: false,
    res_follow_pitch: 0,
    overview_title: "",
    overview_max_leg_seconds: 10,
    overview_intro_card_scale: 1.3,
    overview_intro_clean_hold_seconds: 1.5,
    enable_ending_highlight: true,
    enable_outro: true,
    outro_style: "scroll" as "scroll" | "grid",
    outro_route_info: true,
    start_pin_color: [19, 136, 3] as Rgb,
    end_pin_color: [217, 15, 81] as Rgb,
    stopby_pin_color: [51, 38, 28] as Rgb,
    drawn_pin_color: [255, 121, 12] as Rgb,
    // arrived_marker_color has no fixed default: it is the project's marker color, darkened (see utils/videoLook.ts).
    overview_speed_multiplier: 4,
    res_target_avg_seconds: 14,
    res_max_segment_seconds: 16,
    camera_follow_distance_m: 14,
    bearing_smoothing: 0.15,
    enable_fullscreen_popups: true,
    hide_route_on_popup: false,
    upscale_popup_images: true,
};

export interface MapStyleOption {
    id: string;
    label: string;
    url: any;
    // Past the finest zoom a tile set has, the map only stretches pixels.
    maxZoom?: number;
}

export const mapStyles: MapStyleOption[] = [
    {
        id: "outdoors",
        label: "Outdoors (3D Terrain)",
        url: "mapbox://styles/mapbox/outdoors-v12",
    },
    {
        id: "satellite",
        label: "Satellite Streets",
        url: "mapbox://styles/mapbox/satellite-streets-v12",
    },
    {
        id: "dark",
        label: "Cinematic Dark",
        url: "mapbox://styles/mapbox/dark-v11",
    },
    {
        id: "standard",
        label: "Standard (Dynamic)",
        url: "mapbox://styles/mapbox/standard",
    },
    {
        id: "light",
        label: "Light Streets",
        url: "mapbox://styles/mapbox/streets-v12",
    },
    {
        id: "osm",
        label: "Classic OpenStreetMap",
        url: {
            version: 8,
            sources: {
                osm: {
                    type: "raster",
                    tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"],
                    tileSize: 256,
                },
            },
            layers: [
                { id: "osm", type: "raster", source: "osm", minzoom: 0, maxzoom: 22 },
            ],
        } as any,
    },
    {
        id: "gsi-japan",
        label: "Japan GSI Topo (Hiking)",
        url: {
            version: 8,
            sources: {
                gsi: {
                    type: "raster",
                    tiles: ["https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png"],
                    tileSize: 256,
                    maxzoom: 18,
                },
            },
            layers: [{ id: "gsi", type: "raster", source: "gsi" }],
        } as any,
        maxZoom: 17,
    },
];

// Mapbox styles the video can be drawn on, as "owner/id" (the render's pydeck maps load mapbox-gl 1.x, which cannot draw Standard).
export const videoMapStyles = [
    { id: "mapbox/outdoors-v12", label: "Outdoors" },
    { id: "mapbox/streets-v12", label: "Streets" },
    { id: "mapbox/satellite-streets-v12", label: "Satellite Streets" },
    { id: "mapbox/dark-v11", label: "Dark" },
    { id: "mapbox/light-v11", label: "Light" },
];

/** The editor's current map style as a video style id, or null when the video cannot use it (OSM, GSI, Standard). */
export function editorStyleForVideo(): string | null {
    let saved: string | null = null;
    try {
        saved = localStorage.getItem("map-style");
    } catch {}
    const style = mapStyles.find((s) => s.id === saved) ?? mapStyles[0];
    const id = typeof style.url === "string" ? style.url.replace("mapbox://styles/", "") : "";
    return videoMapStyles.some((s) => s.id === id) ? id : null;
}

export function editorStyleLabel(): string {
    let saved: string | null = null;
    try {
        saved = localStorage.getItem("map-style");
    } catch {}
    return (mapStyles.find((s) => s.id === saved) ?? mapStyles[0]).label;
}
