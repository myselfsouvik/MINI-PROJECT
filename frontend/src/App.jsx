import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Alerts from "./pages/Alerts.jsx";
import Cameras from "./pages/Cameras.jsx";
import DogProfile from "./pages/DogProfile.jsx";
import Dogs from "./pages/Dogs.jsx";
import Live from "./pages/Live.jsx";
import Overview from "./pages/Overview.jsx";
import Placeholder, { NotFound } from "./pages/Placeholder.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="live" element={<Live />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="dogs" element={<Dogs />} />
        <Route path="dogs/:id" element={<DogProfile />} />
        <Route path="activity" element={<Placeholder what="Activity" consoleTab="activity" />} />
        <Route path="bites" element={<Placeholder what="Bites data" consoleTab="bites" />} />
        <Route path="cameras" element={<Cameras />} />
        <Route path="settings" element={<Placeholder what="Settings" consoleTab="settings" />} />
        <Route path="welcome" element={<Placeholder what="Guided setup" consoleTab="cameras" />} />
        <Route path="present" element={<Placeholder what="Presentation view" consoleTab="live" />} />
        <Route path="help" element={<Placeholder what="Help" consoleTab="live" />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
