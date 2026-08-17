import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import './App.css';
import 'leaflet/dist/leaflet.css';
import { ThemeProvider } from './hooks/useTheme';
import { WorkspaceProvider } from "./hooks/useWorkspace";
import { UIProvider } from "./hooks/useUI";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="system">
      <WorkspaceProvider>
        <UIProvider>
          <App />
        </UIProvider>
      </WorkspaceProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
