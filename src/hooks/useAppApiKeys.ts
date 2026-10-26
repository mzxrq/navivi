import { useCallback, useEffect, useRef, useState } from "react";
import { loadMapKeys, saveMapKeys } from "../services/mapKeys";
import { adoptLegacyKeys, AppApiKeys, hasApiKeys, sameApiKeys } from "../utils/apiKeys";

/**
 * The map service keys (Mapbox, OpenRouteService, Mapillary), kept in the OS credential store like the AI keys.
 * A change made before the saved keys have been read is held back from the store and wins once they arrive,
 * and a key found in an opened project fills only what is still empty.
 */
export function useAppApiKeys() {
  const [keys, setKeys] = useState<AppApiKeys>({});
  const keysRef = useRef(keys);
  const loadedRef = useRef(false);
  const earlyRef = useRef<AppApiKeys>({});
  const adoptRef = useRef<AppApiKeys>({});

  const commit = useCallback((next: AppApiKeys) => {
    keysRef.current = next;
    setKeys(next);
  }, []);
  const persist = useCallback((next: AppApiKeys) => {
    saveMapKeys(next).catch((err) => console.error("Could not save the map keys:", err));
  }, []);

  useEffect(() => {
    let attempts = 0;
    const load = () =>
      loadMapKeys()
        .then((stored) => {
          const early = earlyRef.current;
          const merged = adoptLegacyKeys({ ...keysRef.current, ...stored, ...early }, adoptRef.current);
          loadedRef.current = true;
          commit(merged);
          if (!sameApiKeys(merged, stored)) persist(merged);
        })
        .catch((err) => {
          console.error("Could not load the map keys:", err);
          if (++attempts < 3) setTimeout(load, 1000 * attempts);
        });
    load();
  }, [commit, persist]);

  const update = useCallback(
    (patch: AppApiKeys) => {
      const next = { ...keysRef.current, ...patch };
      commit(next);
      if (loadedRef.current) persist(next);
      else earlyRef.current = { ...earlyRef.current, ...patch };
    },
    [commit, persist],
  );

  const adoptLegacy = useCallback(
    (legacy: AppApiKeys) => {
      if (!hasApiKeys(legacy)) return;
      if (!loadedRef.current) {
        adoptRef.current = adoptLegacyKeys(adoptRef.current, legacy);
        return;
      }
      const next = adoptLegacyKeys(keysRef.current, legacy);
      if (sameApiKeys(next, keysRef.current)) return;
      commit(next);
      persist(next);
    },
    [commit, persist],
  );

  return { keys, update, adoptLegacy };
}
