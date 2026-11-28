import { useState } from "react";
import { Bar } from "react-chartjs-2";
import { ActivitySplit } from "../components/bits.jsx";
import { useLive, usePoll } from "../hooks/live.jsx";
import { withToken } from "../lib/api.js";
import { barOptions, barStyle, useChartTheme } from "../lib/charts.js";
import { ACT_NAME, ACTS, duration } from "../lib/format.js";
import { RANGES, bucketLabel, fillTimeline } from "../lib/timeline.js";

// Charts about the dogs over a time range: when they were around and what they did,
// where in the picture they spend time, and how fast they move.

const ACT_TOKEN = { RESTING: "rest", WALKING: "walk", RUNNING: "run" };
const minutesText = (m) => (m >= 10 ? Math.round(m) : m.toFixed(1));

/** The numbers behind a chart, for reading exact values without hovering. */
function NumbersTable({ head, rows }) {
  return (
    <details className="numbers">
      <summary>Show the numbers</summary>
      <div className="table-wrap">
        <table>
          <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => (j ? <td key={j}>{c}</td> : <th key={j} scope="row">{c}</th>))}</tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}

function Timeline({ data, rangeKey, t }) {
  const r = RANGES[rangeKey];
  // The server starts the buckets on a round local time (14:00, not 14:07) and says where.
  const since = data.since ?? Date.now() / 1000 - r.minutes * 60;
  const rows = fillTimeline(data.buckets, since, r.bucket, ((data.count ?? r.minutes * 60 / r.bucket) * r.bucket) / 60);
  const total = rows.reduce((s, b) => s + b.RESTING + b.WALKING + b.RUNNING, 0);
  if (!total) return <p className="muted chart-empty">No dogs were seen in this period.</p>;
  const chart = {
    labels: rows.map((b) => bucketLabel(b.start, rangeKey)),
    datasets: ACTS.map((a) => ({ label: ACT_NAME[a], data: rows.map((b) => +b[a].toFixed(2)), ...barStyle(t, t[ACT_TOKEN[a]], { stacked: true }) })),
  };
  const opts = barOptions(t, {
    stacked: true, legend: true, yTitle: "dog-minutes",
    tooltipLabel: (c) => (c.raw ? ` ${c.dataset.label}: ${minutesText(c.raw)} dog-min` : null),
  });
  const busy = rows.filter((b) => b.RESTING + b.WALKING + b.RUNNING > 0);
  return (
    <>
      <div className="chart-box tall"><Bar data={chart} options={opts} aria-label="Dog-minutes per time slot, split into resting, walking and running" role="img" /></div>
      <NumbersTable head={["From", ...ACTS.map((a) => ACT_NAME[a])]}
        rows={busy.map((b) => [bucketLabel(b.start, rangeKey), ...ACTS.map((a) => minutesText(b[a]))])} />
    </>
  );
}

function Heatmap({ data, sourceId }) {
  const [hover, setHover] = useState(null);
  if (!data.max) return <p className="muted chart-empty">No positions in this period.</p>;
  const { cols, rows, grid, max } = data;
  const w = 160, h = 90, cw = w / cols, ch = h / rows;
  let best = [0, 0];
  grid.forEach((row, y) => row.forEach((v, x) => { if (v > grid[best[1]][best[0]]) best = [x, y]; }));
  const where = `${["top", "middle", "bottom"][Math.min(2, Math.floor((3 * best[1]) / rows))]} ${["left", "centre", "right"][Math.min(2, Math.floor((3 * best[0]) / cols))]}`;
  return (
    <>
      <div className="heat" onMouseLeave={() => setHover(null)}>
        {sourceId ? <img src={withToken(`/api/sources/${sourceId}/snapshot.jpg?raw=1`)} alt="" onError={(e) => { e.currentTarget.hidden = true; }} /> : null}
        <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`Where dogs spent time in the picture. Busiest: ${where}.`}>
          {grid.flatMap((row, y) => row.map((v, x) => (v ? (
            <rect key={`${x}-${y}`} x={x * cw + 0.25} y={y * ch + 0.25} width={cw - 0.5} height={ch - 0.5} rx="0.8"
              style={{ opacity: 0.15 + 0.85 * Math.sqrt(v / max) }} onMouseEnter={() => setHover({ x, y, v })} />
          ) : null)))}
          {hover ? <rect className="hover" x={hover.x * cw} y={hover.y * ch} width={cw} height={ch} rx="0.8" /> : null}
        </svg>
        {hover ? <div className="heat-tip">{duration(hover.v)} of dog time here</div> : null}
      </div>
      <div className="heat-legend small muted">
        <span>Less</span><i /><span>More time</span>
        <span className="heat-note">Busiest part of the picture: <b>{where}</b></span>
      </div>
    </>
  );
}

function Speeds({ data, t }) {
  const total = data.counts.reduce((s, n) => s + n, 0);
  if (!total) return <p className="muted chart-empty">No movement in this period.</p>;
  const last = data.counts.length - 1;
  const labels = data.counts.map((_, i) => (i === last ? `${data.edges[i]}+` : `${data.edges[i]}`));
  const chart = { labels, datasets: [{ label: "Seconds", data: data.counts, ...barStyle(t, t.series) }] };
  const opts = barOptions(t, {
    xTitle: "speed (body heights a second)", yTitle: "dog-seconds",
    tooltipLabel: (c) => ` ${duration(c.raw)} at ${c.label}${c.dataIndex === last ? "" : `–${data.edges[c.dataIndex + 1]}`}`,
  });
  const slow = data.counts.slice(0, 2).reduce((s, n) => s + n, 0);
  return (
    <>
      <div className="chart-box"><Bar data={chart} options={opts} role="img" aria-label="How much time dogs spent at each speed" /></div>
      <p className="small muted chart-note">{Math.round((100 * slow) / total)}% of the time dogs moved slower than {data.edges[2]} body heights a second.</p>
      <NumbersTable head={["Speed", "Time"]} rows={data.counts.map((n, i) => [labels[i], duration(n)])} />
    </>
  );
}

export default function Activity() {
  const t = useChartTheme();
  const { sources } = useLive();
  const [rangeKey, setRangeKey] = useState("24h");
  const [cam, setCam] = useState("");
  const r = RANGES[rangeKey];
  const src = cam ? `&source_id=${encodeURIComponent(cam)}` : "";
  const every = { every: 30000 };
  const summary = usePoll(`/api/stats/summary?minutes=${r.minutes}`, every);
  const timeline = usePoll(`/api/stats/timeline?minutes=${r.minutes}&bucket=${r.bucket}&align=true&utc_offset=${-new Date().getTimezoneOffset()}${src}`, every);
  const heat = usePoll(`/api/stats/heatmap?minutes=${r.minutes}&cols=24&rows=14${src}`, every);
  const speeds = usePoll(`/api/stats/speeds?minutes=${r.minutes}&bin_width=0.25&max_speed=4${src}`, every);
  const s = summary.data;
  const watched = s ? ACTS.reduce((n, a) => n + (s.activity_seconds[a] || 0), 0) : 0;
  const report = `/api/report?minutes=${r.minutes}`;
  const errors = [summary, timeline, heat, speeds].map((p) => p.error).filter(Boolean);

  return (
    <div className="activity">
      <div className="filters" role="group" aria-label="Filters">
        <div className="segmented" role="radiogroup" aria-label="Time range">
          {Object.entries(RANGES).map(([k, v]) => (
            <button key={k} role="radio" aria-checked={k === rangeKey} onClick={() => setRangeKey(k)}>{v.label}</button>
          ))}
        </div>
        {sources?.length > 1 ? (
          <label className="row small">Camera
            <select value={cam} onChange={(e) => setCam(e.target.value)}>
              <option value="">All cameras</option>
              {sources.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        ) : null}
        <div className="row report-links">
          <a className="btn quiet small" href={withToken(report)} target="_blank" rel="noreferrer">Open the report</a>
          <a className="btn quiet small" href={withToken(`${report}&download=1`)}>Download it</a>
        </div>
      </div>
      {errors.length ? <p className="error">{errors[0]}</p> : null}

      <section className="figures" aria-label={r.label}>
        <div><b>{s ? s.dogs_seen : "–"}</b>dogs seen</div>
        <div><b>{s ? duration(watched) : "–"}</b>of dog time watched</div>
        <div><b>{s ? s.alerts : "–"}</b>alerts</div>
        <div><b>{s ? (s.busiest_hour != null ? `${String(s.busiest_hour).padStart(2, "0")}:00` : "None yet") : "–"}</b>busiest hour</div>
      </section>

      <section className="sheet">
        <div className="sheet-head"><h2>When dogs were around</h2><span className="muted small">{r.label}{cam ? "" : ", all cameras"}</span></div>
        <p className="small muted chart-note">One dog in view for one minute is one dog-minute. Each bar is split by what the dogs were doing.</p>
        {timeline.data ? <Timeline data={timeline.data} rangeKey={rangeKey} t={t} /> : <p className="muted chart-empty">Loading…</p>}
      </section>

      <div className="two-charts">
        <section className="sheet">
          <div className="sheet-head"><h2>Where in the picture</h2></div>
          {heat.data ? <Heatmap data={heat.data} sourceId={cam || (sources?.length === 1 ? sources[0].id : null)} /> : <p className="muted chart-empty">Loading…</p>}
        </section>
        <section className="sheet">
          <div className="sheet-head"><h2>How fast they move</h2></div>
          {speeds.data ? <Speeds data={speeds.data} t={t} /> : <p className="muted chart-empty">Loading…</p>}
        </section>
      </div>

      <section className="sheet">
        <div className="sheet-head"><h2>How dogs spent their time</h2><span className="muted small">All cameras</span></div>
        {s ? <ActivitySplit seconds={s.activity_seconds} /> : <p className="muted">Loading…</p>}
      </section>
    </div>
  );
}
