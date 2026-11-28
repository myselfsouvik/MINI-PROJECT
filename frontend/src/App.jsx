import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Alerts from "./pages/Alerts.jsx";
import Cameras from "./pages/Cameras.jsx";
import DogProfile from "./pages/DogProfile.jsx";
import Dogs from "./pages/Dogs.jsx";
import Live from "./pages/Live.jsx";
import Overview from "./pages/Overview.jsx";
import Help from "./pages/Help.jsx";
import NotFound from "./pages/NotFound.jsx";
import Present from "./pages/Present.jsx";
import Settings from "./pages/Settings.jsx";
import Welcome from "./pages/Welcome.jsx";

// The chart pages bring Chart.js, so they load only when opened.
const Activity = lazy(() => import("./pages/Activity.jsx"));
const Bites = lazy(() => import("./pages/Bites.jsx"));
const later = (el) => <Suspense fallback={<p className="muted">Loading…</p>}>{el}</Suspense>;

export default function App() {
  return (
    <Routes>
      <Route path="welcome" element={<Welcome />} />
      <Route path="present" element={<Present />} />
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="live" element={<Live />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="dogs" element={<Dogs />} />
        <Route path="dogs/:id" element={<DogProfile />} />
        <Route path="activity" element={later(<Activity />)} />
        <Route path="bites" element={later(<Bites />)} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="settings" element={<Settings />} />
        <Route path="help" element={<Help />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
