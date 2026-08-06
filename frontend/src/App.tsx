import { Sidebar } from './components/Sidebar';
import { MapArea } from './components/MapArea';
import { VideoArea } from './components/VideoArea';
import {} from './App.css';

export default function App() {
  return (
    <div className="flex h-screen w-screen bg-slate-950 overflow-hidden font-sans">
      <Sidebar />
      <div className="flex flex-col flex-1 h-full">
        <MapArea />
        <VideoArea />
      </div>
    </div>
  );
}