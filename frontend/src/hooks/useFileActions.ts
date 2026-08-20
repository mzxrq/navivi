import { useWorkspace } from "./useWorkspace";
import { useUI } from "./useUI";
import { open } from "@tauri-apps/plugin-dialog";
import { readTextFile } from "@tauri-apps/plugin-fs";

export function useFileActions() {
    const { setRoutePoints } = useWorkspace();
    const { showToast } = useUI();

    const importRouteFile = async (filePath?: string) => {
        try {
          const selectedPath = filePath || await open({
            multiple: false,
            filters: [{ name: "Navivi & GPS", extensions: ["json", "gpx", "fit", "tcx", "kml"]}],
          });
    
          if (typeof selectedPath !== "string") return;
    
          if (selectedPath.toLowerCase().endsWith(".gpx")) {
            const fileContent = await readTextFile(selectedPath);
            const parser = new DOMParser();
            const xmlDoc = parser.parseFromString(fileContent, "text/xml");
            const trackPoints = xmlDoc.getElementsByTagName("trkpt");
            const points: [number, number][] = [];
    
            for (let i = 0; i < trackPoints.length; i++) {
              const lat = parseFloat(trackPoints[i].getAttribute("lat") || "0");
              const lon = parseFloat(trackPoints[i].getAttribute("lon") || "0");
              if (lat && lon) points.push([lat, lon]);
            }
    
            setRoutePoints(points);
            showToast("Route imported successfully", "success");
          } else {
            // todo: call gpsbabel conversion logic for non-gpx files
            // setRoutePoints([]);
          }
        } catch (error) {
            console.error("Failed to import route:", error);
            showToast("Failed to parse file", "error");
        }
      };
      return { importRouteFile };
}