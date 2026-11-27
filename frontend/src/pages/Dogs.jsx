import { useState } from "react";
import { Link } from "react-router-dom";
import { usePoll } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { ACT_NAME, ago, duration, plural } from "../lib/format.js";

// Every dog the cameras followed, as photo cards. A card opens the dog's own page.

const SORTS = [
  ["recent", "Most recent"], ["longest", "Longest stay"], ["active", "Most active"], ["fastest", "Fastest"],
];
const PERIODS = [["1440", "Today"], ["10080", "Last 7 days"], ["", "All time"]];
const PAGE = 48;

export function DogCard({ d }) {
  return (
    <li>
      <Link className="dog-card" to={`/dogs/${d.id}`}>
        <span className="pic">
          {d.snapshot_url
            ? <img src={withToken(`${d.snapshot_url}?t=${Math.floor(d.last_seen)}`)} alt="" loading="lazy" />
            : <span className="no-pic">No photo</span>}
        </span>
        <span className="cap">
          <b>#{d.id}</b>
          {d.main_activity ? <span className={`act ${d.main_activity}`}>{ACT_NAME[d.main_activity]}</span> : null}
        </span>
        <span className="meta">{duration(d.seconds_visible)} in view, {ago(d.last_seen)}</span>
      </Link>
    </li>
  );
}

export default function Dogs() {
  const [sort, setSort] = useState("recent");
  const [period, setPeriod] = useState("1440");
  const [limit, setLimit] = useState(PAGE);
  const q = `/api/dogs?limit=${limit}&sort=${sort}${period ? `&minutes=${period}` : ""}`;
  const { data, error, loading } = usePoll(q, { every: 15000 });
  const reset = (fn) => (e) => { fn(e.target.value); setLimit(PAGE); };

  return (
    <div className="dogs-page">
      <div className="toolbar">
        <p className="muted">{data ? `${plural(data.length, "dog")}${data.length >= limit ? "+" : ""}, staying at least a second.` : " "}</p>
        <div className="row">
          <label className="row small">When
            <select value={period} onChange={reset(setPeriod)}>
              {PERIODS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label className="row small">Sort by
            <select value={sort} onChange={reset(setSort)}>
              {SORTS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
        </div>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {data?.length ? (
        <>
          <ul className="dog-grid">{data.map((d) => <DogCard key={d.id} d={d} />)}</ul>
          {data.length >= limit ? (
            <div style={{ textAlign: "center", marginTop: 20 }}>
              <button className="btn quiet" onClick={() => setLimit((n) => n + PAGE)}>Show more dogs</button>
            </div>
          ) : null}
        </>
      ) : (
        <div className="sheet empty">
          <h2>{loading ? "Loading…" : period ? "No dogs in this period" : "No dogs yet"}</h2>
          {!loading ? (
            <p>Once a camera sees a dog for a moment, its photo shows up here.
              {period ? " Try All time to see older ones." : ""}</p>
          ) : null}
          {!loading && !period ? <Link className="btn primary" to="/cameras">Add a camera</Link> : null}
        </div>
      )}
    </div>
  );
}
