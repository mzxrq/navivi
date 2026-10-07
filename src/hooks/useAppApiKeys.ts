import { useCallback, useEffect, useRef, useState } from "react";
import { db } from "../services/db";
import { adoptLegacyKeys, API_KEYS_SETTING, AppApiKeys, cleanApiKeys, hasApiKeys, sameApiKeys } from "../utils/apiKeys";

/**
 * The Mapbox and OpenRouteService keys, kept in the app settings (same pattern as the AI choices in useWorkspace).
 * A change made before the saved record has been read is held back from the database and wins once it arrives,
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
    db.appSettings.set(API_KEYS_SETTING, next).catch((err) => console.error("Could not save the map keys:", err));
  }, []);

  useEffect(() => {
    let attempts = 0;
    const load = () =>
      db.appSettings
        .get<unknown>(API_KEYS_SETTING)
        .then((saved) => {
          const early = earlyRef.current;
          const stored = cleanApiKeys(saved);
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
