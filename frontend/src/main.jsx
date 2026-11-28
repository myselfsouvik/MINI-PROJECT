import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// Fonts are bundled, so the dashboard looks the same with no internet on demo day.
import "@fontsource/atkinson-hyperlegible/400.css";
import "@fontsource/atkinson-hyperlegible/700.css";
import "@fontsource/bricolage-grotesque/500.css";
import "@fontsource/bricolage-grotesque/700.css";
import "@fontsource/bricolage-grotesque/800.css";
import "./tokens.css";
import "./app.css";
import App from "./App.jsx";
import { LiveProvider } from "./hooks/live.jsx";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <LiveProvider>
        <App />
      </LiveProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
