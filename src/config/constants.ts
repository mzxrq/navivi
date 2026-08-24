export const appConfig = {
    name: "Navivi",
    version: "0.1.0", // await syncing with package.json
    defaultProjectName: "Untitled Project",
    defaultUserId: "local",
};

export const fileSystem = {
    rootFolder: "Navivi",
    projectsFolder: "Projects",
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
};

export const apiEndpoints = {
    orsBase: "https://api.openrouteservice.org/v2/directions",
    nominatimReverse: "https://nominatim.openstreetmap.org/reverse",
};

export const defaultProjectSettings = {
    fps: 30,
    duration_seconds: 8.0,
    line_color: [0, 200, 255] as [number, number, number],
    line_thickness: 10,
    marker_color: [0, 0, 255] as [number, number, number],
    marker_radius: 10,
    res_duration: 12.0,
    pause: 2.0,
    summary_hold: 4.0,
    summary_fade: 0.5,
    resolution: "1080p",
    ors_api_key: "",
};

