import { Link } from "react-router-dom";
import { withToken } from "../lib/api.js";

// Pages that are still being moved over from the classic console point to its matching tab.
export default function Placeholder({ what, consoleTab }) {
  return (
    <section className="sheet placeholder">
      <h2>{what} is moving here soon</h2>
      <p className="muted">This page is being rebuilt for the new dashboard. Everything it does already works in the classic console.</p>
      <p style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <a className="btn" href={withToken(`/console#${consoleTab}`)}>Open {what.toLowerCase()} in the classic console</a>
        <Link className="btn quiet" to="/">Back to Overview</Link>
      </p>
    </section>
  );
}

export function NotFound() {
  return (
    <section className="sheet placeholder">
      <h2>There is no page here</h2>
      <p className="muted">The address may be mistyped, or the page was moved.</p>
      <p style={{ marginTop: 16 }}><Link className="btn" to="/">Go to Overview</Link></p>
    </section>
  );
}
