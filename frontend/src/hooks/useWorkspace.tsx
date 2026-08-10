import { createContext, useContext, useState } from 'react';

export type Waypoint = {
    id: string;
    lat: number;
    lng: number;
    name: string;
    image: string | null;
    narration: string;
};

type WorkspaceContextType = {
    routeFile: string | null;
    setRouteFile: (path: string | null) => void;
    waypoints: Waypoint[];
    setWaypoints: React.Dispatch<React.SetStateAction<Waypoint[]>>;
    updateWaypoint: (id: string, updates: Partial<Waypoint>) => void;
};

const WorkspaceContext = createContext<WorkspaceContextType | undefined>(undefined);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
    const [routeFile, setRouteFile] = useState<string | null>(null);
    const [waypoints, setWaypoints] = useState<Waypoint[]>([]);
    const updateWaypoint = (id: string, updates: Partial<Waypoint>) => {
        setWaypoints((prev) =>
            prev.map((wp) => (wp.id === id ? { ...wp, ...updates } : wp))
        );
    };

    return (
      <WorkspaceContext.Provider value={{ routeFile, setRouteFile, waypoints, setWaypoints, updateWaypoint }}>
        {children}
      </WorkspaceContext.Provider>
    );
}

export const useWorkspace = () => {
    const context = useContext(WorkspaceContext);
    if (!context) throw new Error('useWorkspace must be used within a WorkspaceProvider');
    return context;
}