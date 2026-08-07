import { useState, useEffect, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { MapArea } from "./components/MapArea";
import { VideoArea } from "./components/VideoArea";
import { TitleBar } from "./components/TitleBar";
import { RefreshCw, Trash2, Settings2 } from "lucide-react";
import "./App.css";

export default function App() {
  const [contextMenu, setContextMenu] = useState({ show: false, x: 0, y: 0 });
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = () =>
      setContextMenu((prev) => ({ ...prev, show: false }));
    window.addEventListener("click", handleClick);
    return () => window.removeEventListener("click", handleClick);
  }, []);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();

    const menuWidth = 192;
    const menuHeight = 130;
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;

    // Calculate positions
    const xPos =
      e.pageX + menuWidth > windowWidth ? e.pageX - menuWidth : e.pageX;
    const yPos =
      e.pageY + menuHeight > windowHeight ? e.pageY - menuHeight : e.pageY;

    setContextMenu({ show: true, x: xPos, y: yPos });
  };

  return (
    <div
      className="flex h-screen w-screen bg-[#09090b] overflow-hidden text-zinc-100 selection:bg-violet-500/30 relative"
      onContextMenu={handleContextMenu}
      tabIndex={0}
    >
      <Sidebar />
      <div className="flex flex-col flex-1 h-full relative">
        <TitleBar />
        <MapArea />
        <VideoArea />
      </div>

      {contextMenu.show && (
        <div
          key={`${contextMenu.x}-${contextMenu.y}`}
          ref={menuRef}
          className="absolute z-[100] w-48 bg-zinc-900/95 backdrop-blur-xl border border-white/10 rounded-xl shadow-2xl p-1 overflow-hidden animate-in fade-in zoom-in-95 duration-100"
          style={{ top: contextMenu.y, left: contextMenu.x }}
        >
          <div className="flex flex-col text-sm text-zinc-300 font-medium">
            <button
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-violet-500/20 hover:text-violet-300 transition-colors text-left"
              onClick={() => window.location.reload()}
            >
              <RefreshCw className="w-4 h-4" /> Reload
            </button>
            <button
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-zinc-800 transition-colors text-left"
              onClick={() => window.location.reload()}
            >
              <Settings2 className="w-4 h-4" /> Settings
            </button>
            <div className="h-px bg-white/5 my-1" />

            <button
              className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-red-500/20 hover:text-red-400 transition-colors text-left"
              onClick={() => window.location.reload()}
            >
              <Trash2 className="w-4 h-4" /> Clear Workspace
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
