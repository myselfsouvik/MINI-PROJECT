// Small stroke icons, drawn for this app (no icon library, works offline).
const P = {
  overview: <><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>,
  live: <><rect x="2.5" y="6" width="13" height="12" rx="2" /><path d="M15.5 10.5 21 7v10l-5.5-3.5" /></>,
  alerts: <><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15Z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>,
  dogs: <><circle cx="7" cy="9" r="1.8" /><circle cx="11" cy="6" r="1.8" /><circle cx="15.5" cy="6.5" r="1.8" /><circle cx="18.5" cy="10.5" r="1.8" /><path d="M8.5 16.5c0-3 2-5 4.5-5s4 2.2 4 4.6c0 2-1.5 3.4-3.3 3.4-1 0-1.5-.5-2.4-.5s-1.4.5-2.3.5c-.9 0-.5-1.4-.5-3Z" /></>,
  activity: <><path d="M3 20h18" /><path d="M6 16v-5" /><path d="M11 16V6" /><path d="M16 16v-8" /><path d="M21 16v-3" /></>,
  bites: <><rect x="5" y="3.5" width="14" height="17" rx="2" /><path d="M9 3.5h6v3H9z" /><path d="M9 11h6M9 15h4" /></>,
  cameras: <><path d="M4 8h3l1.5-2h7L17 8h3v11H4Z" /><circle cx="12" cy="13" r="3.2" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" /></>,
  present: <><rect x="3" y="4" width="18" height="12" rx="1.5" /><path d="M12 16v4M8 20h8" /></>,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.6 9.3a2.5 2.5 0 1 1 3.3 2.4c-.6.3-.9.8-.9 1.5v.6" /><path d="M12 17h.01" /></>,
  console: <><rect x="3" y="4.5" width="18" height="15" rx="2" /><path d="m7 10 3 2.5L7 15M12.5 15H17" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
};

export default function Icon({ name, title }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title ? <title>{title}</title> : null}
      {P[name]}
    </svg>
  );
}

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="15" fill="#F0A202" />
      <g fill="#232B27">
        <ellipse cx="16" cy="20" rx="6" ry="5" /><ellipse cx="9.5" cy="13" rx="2.3" ry="3" />
        <ellipse cx="22.5" cy="13" rx="2.3" ry="3" /><ellipse cx="13.2" cy="9" rx="2.1" ry="2.8" />
        <ellipse cx="18.8" cy="9" rx="2.1" ry="2.8" />
      </g>
    </svg>
  );
}
