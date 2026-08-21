import { useWorkspace } from "./useWorkspace";

export function useWaypointActions() {
  const { updateWaypoint, waypoints, setWaypoints, setIsDirty } = useWorkspace();

  const addWaypoint = async (lat: number, lng: number) => {
    const newId = Math.random().toString(36).substring(7);

    setWaypoints((prev) => [
      ...prev,
      {
        id: newId,
        lat,
        lng,
        name: "Locating...",
        images: [],
        narration: "",
        routeMode: "driving",
      },
    ]);

    if (setIsDirty) setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`
      );
      const data = await res.json();
      const placeName =
        data.name ||
        data.address?.road ||
        data.address?.city ||
        `Waypoint ${newId.substring(0, 4).toUpperCase()}`;

      setWaypoints((prev) =>
        prev.map((wp) => (wp.id === newId ? { ...wp, name: placeName } : wp))
      );
    } catch (error) {
      setWaypoints((prev) =>
        prev.map((wp) =>
          wp.id === newId ? { ...wp, name: `Unknown Location` } : wp
        )
      );
    }
  };

  const updateWaypointLocation = async (id: string, lat: number, lng: number) => {
    updateWaypoint(id, { lat, lng, name: "Locating..." });

    if (setIsDirty) setIsDirty(true);

    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`
      );
      const data = await res.json();
      const placeName =
        data.name || data.address?.road || data.address?.city || "Unknown Location"

      updateWaypoint(id, { name: placeName });
    } catch (error) {
      updateWaypoint(id, { name: "Unknown Location" });
    }

  };

  const addReturnStop = (targetId: string) => {
    const wpToClone = waypoints.find(w => w.id === targetId);
    if (!wpToClone) return;

    const returnWaypoint = {
      ...wpToClone,
      id: crypto.randomUUID(),
      name: `${wpToClone.name} (Return)`,
      narration: "",
      images: [],
    };

    setWaypoints((prev) => [...prev, returnWaypoint]);

    if (setIsDirty) setIsDirty(true);
  };

  return { addWaypoint, updateWaypointLocation, addReturnStop };
}