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
    gpxFile: "raw_track.gpx",
    extensions: {
        project: "nvv",
    },
};

export const mapDefaults = {
    startCoords: [34.6937, 135.5023] as [number, number],
    zoomLevel: 10,
    maxImagesPerWaypoint: 3,
    maxWaypoints: 30,
    maxRouteDistanceKm: 50,
};

export const apiEndpoints = {
    orsBase: "https://api.openrouteservice.org/v2/directions",
    nominatimReverse: "https://nominatim.openstreetmap.org/reverse",
};

export const defaultProjectSettings = {
    fps: 30,
    duration_seconds: 8.0,
    line_color: [0, 200, 255] as [number, number, number],
    line_thickness: 6,
    route_line_border_color: [255, 255, 255] as [number, number, number],
    route_line_border_thickness: 0,
    marker_color: [0, 0, 255] as [number, number, number],
    marker_radius: 10,
    routeMarker: "",
    res_duration: 12.0,
    pause: 2.0,
    summary_hold: 4.0,
    summary_fade: 0.5,
    mapbox_api_key: "",
    auto_save_interval: 3,
    show_route_heatmap: false,
    weather_sync_enabled: false,
    quick_export: false,
    hardware_spec_override: "auto" as "auto" | "high" | "low",
};

export const mapStyles = [
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
                },
            },
            layers: [
                { id: "gsi", type: "raster", source: "gsi", minzoom: 0, maxzoom: 18 },
            ],
        } as any,
    },
];
