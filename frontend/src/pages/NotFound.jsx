import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <section className="sheet placeholder">
      <h2>There is no page here</h2>
      <p className="muted">The address may be mistyped, or the page was moved.</p>
      <p style={{ marginTop: 16 }}><Link className="btn" to="/">Go to Overview</Link></p>
    </section>
  );
}
