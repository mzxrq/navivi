import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import './App.css';
import { ThemeProvider } from './hooks/useTheme';

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="system">
      <App />
    </ThemeProvider>
  </React.StrictMode>,
);
