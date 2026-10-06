import { useWorkspace } from "./useWorkspace";
import { t } from "@lingui/core/macro";
import { placeNameOf } from "../utils/placeName";

export function useWaypointActions() {
  const { updateWaypoint, waypoints, setWaypoints, setIsDirty } = useWorkspace();

  const addWaypoint = async (lat: number, lng: number) => {
    const newId = crypto.randomUUID();

    setWaypoints((prev) => [
      ...prev,
      {
        id: newId,
        lat,
        lng,
        name: t`Locating...`,
        images: [],
        imagePans: [],
        narration: "",
        arrivingNarration: "",
        attractionNarration: "",
        routeMode: "walking",
        isStopBy: false,
        connectToRoute: undefined,
      },
    ]);

    if (setIsDirty) setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`
      );
      const data = await res.json();
      const placeName = placeNameOf(data, t`Waypoint ${newId.substring(0, 4).toUpperCase()}`);

      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp))
      );
    } catch (error) {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: t`Unknown Location` } : wp
        )
      );
    }
  };

  const updateWaypointLocation = async (id: string, lat: number, lng: number) => {
    updateWaypoint(id, { lat, lng, name: t`Locating...` });

    if (setIsDirty) setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`
      );
      const data = await res.json();
      const placeName = placeNameOf(data, t`Unknown Location`);

      updateWaypoint(id, { name: placeName });
    } catch (error) {
      updateWaypoint(id, { name: t`Unknown Location` });
    }
  };

  const addReturnStop = (targetId: string) => {
    const wpToClone = waypoints.find(w => w.id === targetId);
    if (!wpToClone) return;

    const returnWaypoint = {
      ...wpToClone,
      id: crypto.randomUUID(),
      name: t`${wpToClone.name} (Return)`,
      narration: "",
      arrivingNarration: "",
      attractionNarration: "",
      images: [],
      imagePans: [],
      videos: [],
      videoSound: [],
      isStopBy: false,
      connectToRoute: undefined,
      // Belongs to the original stop's outgoing leg or generated clips, not to a new final stop.
      customRoute: undefined,
      viaPoints: undefined,
      curveOffset: undefined,
      lineColor: undefined,
      audioUrl: undefined,
      videoUrl: undefined,
      videoPrompt: undefined,
      isGeneratingAudio: false,
      isGeneratingVideo: false,
      generatingScriptType: null,
      skipAssetGeneration: undefined,
      isStub: undefined,
      timestamp: undefined,
      timelineOffset: undefined,
      videoOffset: undefined,
      audioOffset: undefined,
    };

    setWaypoints((prev) => [...prev, returnWaypoint]);

    if (setIsDirty) setIsDirty(true);
  };

  return { addWaypoint, updateWaypointLocation, addReturnStop };
}