import { useState, useCallback, SetStateAction } from "react";

export function useHistory<T>(initialState: T, maxHistory: number = 50) {
  const [past, setPast] = useState<T[]>([]);
  const [present, setPresent] = useState<T>(initialState);
  const [future, setFuture] = useState<T[]>([]);

  const set = useCallback((action: SetStateAction<T>) => {
    setPresent((prevPresent) => {
      // Resolve the functional update if the user passed a function
      const newState = typeof action === 'function' 
        ? (action as (prevState: T) => T)(prevPresent) 
        : action;
      
      setPast((prevPast) => {
        const newPast = [...prevPast, prevPresent];
        // Cap the history array to prevent memory leaks!
        if (newPast.length > maxHistory) {
          return newPast.slice(newPast.length - maxHistory);
        }
        return newPast;
      });
      setFuture([]); // Editing clears the redo future
      
      return newState;
    });
  }, [maxHistory]);

  const undo = useCallback(() => {
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    const newPast = past.slice(0, past.length - 1);
    
    setPast(newPast);
    setFuture([present, ...future]);
    setPresent(previous);
  }, [past, present, future]);

  const redo = useCallback(() => {
    if (future.length === 0) return;
    const next = future[0];
    const newFuture = future.slice(1);
    
    setPast((prev) => [...prev, present]);
    setPresent(next);
    setFuture(newFuture);
  }, [future, present]);

  const reset = useCallback((newState: T) => {
    setPast([]);
    setPresent(newState);
    setFuture([]);
  }, []);

  return {
    state: present,
    set,
    undo,
    redo,
    reset,
    canUndo: past.length > 0,
    canRedo: future.length > 0,
  };
}