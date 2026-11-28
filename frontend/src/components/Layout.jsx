import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useLive } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { plural } from "../lib/format.js";
import { setupDone, shouldOpenSetup } from "../lib/setup.js";
import Icon, { Logo } from "./Icon.jsx";

// Pages grouped by what you're doing: watching, understanding, setting up.
export const NAV = [
  { group: "Watch", items: [
    { to: "/", label: "Overview", icon: "overview", end: true },
    { to: "/live", label: "Live", icon: "live" },
    { to: "/alerts", label: "Alerts", icon: "alerts", badge: true },
  ] },
  { group: "Understand", items: [
    { to: "/dogs", label: "Dogs", icon: "dogs" },
    { to: "/activity", label: "Activity", icon: "activity" },
    { to: "/bites", label: "Bites data", icon: "bites" },
  ] },
  { group: "Set up", items: [
    { to: "/cameras", label: "Cameras", icon: "cameras" },
    { to: "/settings", label: "Settings", icon: "settings" },
  ] },
];

const TITLES = {
  "/": "Overview", "/live": "Live", "/alerts": "Alerts", "/dogs": "Dogs", "/activity": "Activity",
  "/bites": "Bites data", "/cameras": "Cameras", "/settings": "Settings", "/help": "Help",
};

export function pageTitle(pathname) {
  if (pathname.startsWith("/dogs/")) return "Dog profile";
  return TITLES[pathname] || "DogWatch";
}

function Sidebar({ unseen, onNavigate }) {
  return (
    <nav className="sidebar" aria-label="Main">
      <Link to="/" className="brand" onClick={onNavigate}><Logo /><b>DogWatch</b></Link>
      {NAV.map((g) => (
        <div className="nav-group" key={g.group}>
          <span>{g.group}</span>
          {g.items.map((it) => (
            <NavLink key={it.to} to={it.to} end={it.end} className="nav-link" onClick={onNavigate}>
              <Icon name={it.icon} />{it.label}
              {it.badge && unseen > 0 ? <span className="badge" aria-label={`${unseen} new`}>{unseen}</span> : null}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="sidebar-foot">
        <NavLink to="/present" className="nav-link" onClick={onNavigate}><Icon name="present" />Presentation view</NavLink>
        <NavLink to="/help" className="nav-link" onClick={onNavigate}><Icon name="help" />Help</NavLink>
        <a href={withToken("/console")} className="nav-link"><Icon name="console" />Classic console</a>
      </div>
    </nav>
  );
}

function TopBar({ title, onMenu }) {
  const { connected, sources, live, unseen } = useLive();
  const running = (sources || []).filter((s) => (live[s.id]?.status || s.status) === "running").length;
  const conn = connected === null ? ["wait", "Connecting…"] : connected ? ["ok", "Live"] : ["bad", "Reconnecting…"];
  return (
    <header className="topbar">
      <button className="btn quiet small menu-btn" onClick={onMenu} aria-label="Open menu"><Icon name="menu" /></button>
      <h1>{title}</h1>
      {sources ? (
        <span className="status cams">
          <span className={`dot ${running ? "ok" : ""}`} />
          {sources.length ? `${running} of ${plural(sources.length, "camera")} watching` : "No cameras yet"}
        </span>
      ) : null}
      <span className="status" role="status"><span className={`dot ${conn[0]}`} />{conn[1]}</span>
      <Link to="/alerts" className="bell" aria-label={unseen ? `Alerts, ${unseen} new` : "Alerts"}>
        <Icon name="alerts" />{unseen ? <span className="badge">{unseen > 99 ? "99+" : unseen}</span> : null}
      </Link>
    </header>
  );
}

function TabBar({ unseen, onMenu }) {
  const tabs = [NAV[0].items[0], NAV[0].items[1], NAV[0].items[2], NAV[1].items[0]];
  return (
    <nav className="tabbar" aria-label="Main pages">
      {tabs.map((it) => (
        <NavLink key={it.to} to={it.to} end={it.end}>
          <Icon name={it.icon} />{it.label}
          {it.badge && unseen > 0 ? <span className="badge">{unseen}</span> : null}
        </NavLink>
      ))}
      <button onClick={onMenu}><Icon name="menu" />More</button>
    </nav>
  );
}

export default function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { unseen, markAlertsSeen, sources, sourcesError, connected } = useLive();
  const [drawer, setDrawer] = useState(false);
  const [checked, setChecked] = useState(false);
  const title = pageTitle(pathname);

  useEffect(() => { document.title = title === "DogWatch" ? title : `${title} | DogWatch`; }, [title]);
  useEffect(() => { if (pathname === "/alerts") markAlertsSeen(); }, [pathname, markAlertsSeen]);
  // First visit with nothing connected: open the guided setup once.
  useEffect(() => {
    if (checked || !Array.isArray(sources) || sourcesError) return;
    setChecked(true);
    if (shouldOpenSetup({ sources, pathname, done: setupDone() })) navigate("/welcome", { replace: true });
  }, [checked, sources, sourcesError, pathname, navigate]);
  useEffect(() => {
    if (!drawer) return undefined;
    const esc = (e) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawer]);

  return (
    <div className={`app${drawer ? " drawer-open" : ""}`}>
      <Sidebar unseen={unseen} onNavigate={() => setDrawer(false)} />
      {drawer ? <div className="scrim" onClick={() => setDrawer(false)} /> : null}
      <div className="main">
        <TopBar title={title} onMenu={() => setDrawer(true)} />
        {sourcesError && connected === false ? (
          <p className="offline" role="alert">
            <b>Can't reach the DogWatch server.</b> Check that it is still running (start.bat or start.sh). Trying again every few seconds…
          </p>
        ) : null}
        <main className="content" id="content"><Outlet /></main>
      </div>
      <TabBar unseen={unseen} onMenu={() => setDrawer(true)} />
    </div>
  );
}
