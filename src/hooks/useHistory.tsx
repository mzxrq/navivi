import { useState, useCallback, useRef } from "react";

export function useHistory<T>(initialPresent: T) {
  const [past, setPast] = useState<T[]>([]);
  const [present, setPresent] = useState<T>(initialPresent);
  const [future, setFuture] = useState<T[]>([]);

  const presentRef = useRef<T>(present);
  presentRef.current = present;

  const canUndo = past.length > 0;
  const canRedo = future.length > 0;

  const set = useCallback((newPresent: T | ((prev: T) => T)) => {
    const current = presentRef.current;
    const resolved =
      typeof newPresent === "function"
        ? (newPresent as (prev: T) => T)(current)
        : newPresent;

    if (JSON.stringify(resolved) === JSON.stringify(current)) return;

    setPast((prev) => [...prev, current]);
    setPresent(resolved);
    presentRef.current = resolved;
    setFuture([]); 
  }, []);

  const undo = useCallback(() => {
    setPast((prevPast) => {
      if (prevPast.length === 0) return prevPast;

      const previous = prevPast[prevPast.length - 1];
      const newPast = prevPast.slice(0, prevPast.length - 1);

      setFuture((prevFuture) => [presentRef.current, ...prevFuture]);
      setPresent(previous);
      presentRef.current = previous;

      return newPast;
    });
  }, []);

  const redo = useCallback(() => {
    setFuture((prevFuture) => {
      if (prevFuture.length === 0) return prevFuture;

      const next = prevFuture[0];
      const newFuture = prevFuture.slice(1);

      setPast((prevPast) => [...prevPast, presentRef.current]);
      setPresent(next);
      presentRef.current = next;

      return newFuture;
    });
  }, []);

  const resetHistory = useCallback((newInitialState: T) => {
    setPast([]);
    setPresent(newInitialState);
    presentRef.current = newInitialState;
    setFuture([]);
  }, []);

  return {
    state: present,
    set,
    undo,
    redo,
    canUndo,
    canRedo,
    resetHistory,
  };
}