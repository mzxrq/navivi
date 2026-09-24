import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./App.css";
import { ThemeProvider } from "./hooks/useTheme";
import { WorkspaceProvider } from "./hooks/useWorkspace";
import { UIProvider } from "./hooks/useUI";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";

import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { dynamicActivate } from "./i18n";

// Initialize with a default language
dynamicActivate("ja").then(() => {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <ErrorBoundary>
        <ThemeProvider defaultTheme="system">
          <I18nProvider i18n={i18n}>
            <UIProvider>
              <WorkspaceProvider>
                <App />
              </WorkspaceProvider>
            </UIProvider>
          </I18nProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </React.StrictMode>,
  );
});
