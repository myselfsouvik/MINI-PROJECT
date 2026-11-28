import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Overview from "./pages/Overview.jsx";
import Placeholder, { NotFound } from "./pages/Placeholder.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="live" element={<Placeholder what="Live" consoleTab="live" />} />
        <Route path="alerts" element={<Placeholder what="Alerts" consoleTab="live" />} />
        <Route path="dogs" element={<Placeholder what="Dogs" consoleTab="dogs" />} />
        <Route path="dogs/:id" element={<Placeholder what="Dog profiles" consoleTab="dogs" />} />
        <Route path="activity" element={<Placeholder what="Activity" consoleTab="activity" />} />
        <Route path="bites" element={<Placeholder what="Bites data" consoleTab="bites" />} />
        <Route path="cameras" element={<Placeholder what="Cameras" consoleTab="cameras" />} />
        <Route path="settings" element={<Placeholder what="Settings" consoleTab="settings" />} />
        <Route path="welcome" element={<Placeholder what="Guided setup" consoleTab="cameras" />} />
        <Route path="present" element={<Placeholder what="Presentation view" consoleTab="live" />} />
        <Route path="help" element={<Placeholder what="Help" consoleTab="live" />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
