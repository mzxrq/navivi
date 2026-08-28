import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import './App.css';
import 'leaflet/dist/leaflet.css';
import { ThemeProvider } from './hooks/useTheme';
import { WorkspaceProvider } from "./hooks/useWorkspace";
import { UIProvider } from "./hooks/useUI";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ThemeProvider defaultTheme="system">
        <UIProvider>
          <WorkspaceProvider>
            <App />
          </WorkspaceProvider>
        </UIProvider>
      </ThemeProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
