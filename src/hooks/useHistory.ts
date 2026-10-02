import { useState, useCallback, SetStateAction } from "react";

interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

// One state object, updated only through pure updaters: React may run an updater twice (StrictMode), and a
// setState call inside another updater would then record every edit twice.
export function useHistory<T>(initialState: T, maxHistory: number = 50) {
  const [history, setHistory] = useState<History<T>>({ past: [], present: initialState, future: [] });

  const set = useCallback((action: SetStateAction<T>) => {
    setHistory((prev) => {
      // Resolve the functional update if the user passed a function
      const next = typeof action === "function" ? (action as (prevState: T) => T)(prev.present) : action;
      if (Object.is(next, prev.present)) return prev;
      const past = [...prev.past, prev.present];
      // Cap the history array to prevent memory leaks!
      return { past: past.length > maxHistory ? past.slice(past.length - maxHistory) : past, present: next, future: [] };
    });
  }, [maxHistory]);

  const undo = useCallback(() => {
    setHistory((prev) => {
      if (prev.past.length === 0) return prev;
      return { past: prev.past.slice(0, -1), present: prev.past[prev.past.length - 1], future: [prev.present, ...prev.future] };
    });
  }, []);

  const redo = useCallback(() => {
    setHistory((prev) => {
      if (prev.future.length === 0) return prev;
      return { past: [...prev.past, prev.present], present: prev.future[0], future: prev.future.slice(1) };
    });
  }, []);

  const reset = useCallback((newState: T) => {
    setHistory({ past: [], present: newState, future: [] });
  }, []);

  return {
    state: history.present,
    set,
    undo,
    redo,
    reset,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  };
}
