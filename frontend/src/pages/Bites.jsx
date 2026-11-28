import { Bar } from "react-chartjs-2";
import { usePoll } from "../hooks/live.jsx";
import { barOptions, barStyle, useChartTheme } from "../lib/charts.js";
import { pct } from "../lib/format.js";

// Why the project matters: what a public record of animal bites says about dogs.
// One chart per question; a single colour each, because each chart has one series.

const TIME = ["by_year", "by_month", "by_weekday"];
const ORDER = ["by_month", "by_year", "by_weekday", "breeds", "body_part", "vaccination", "gender", "rabies_result", "outcome"];

function ChartCard({ id, c, t }) {
  const time = TIME.includes(id);
  const sum = c.values.reduce((a, b) => a + b, 0);
  const share = (v) => (time ? "" : ` (${pct(v / sum)})`);
  const n = c.labels.length;
  const data = {
    labels: c.labels,
    datasets: [{ label: c.title, data: c.values, ...barStyle(t, t.series), maxBarThickness: time ? 40 : 22 }],
  };
  const opts = barOptions(t, {
    horizontal: !time,
    tooltipLabel: (x) => ` ${x.raw.toLocaleString()}${id === "by_month" ? " a month on average" : ""}${share(x.raw)}`,
  });
  const height = time ? 220 : Math.max(120, n * 30 + 30);
  return (
    <section className="sheet bite-card">
      <h2>{c.title}</h2>
      <div className="chart-box" style={{ height }}><Bar data={data} options={opts} role="img" aria-label={c.title} /></div>
      {c.note ? <p className="small muted chart-note">{c.note}</p> : null}
      <details className="numbers">
        <summary>Show the numbers</summary>
        <div className="table-wrap">
          <table>
            <tbody>{c.labels.map((l, i) => <tr key={l}><th scope="row">{l}</th><td>{c.values[i].toLocaleString()}{share(c.values[i])}</td></tr>)}</tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

export default function Bites() {
  const t = useChartTheme();
  const { data, error, loading } = usePoll("/api/insights");
  if (!data) {
    return (
      <div className="sheet empty">
        <h2>{loading ? "Loading…" : "The bites data isn't here"}</h2>
        {!loading ? <p>{error} Put <code>Health_AnimalBites.csv</code> in <code>data/tabular/</code> (see the data README).</p> : null}
      </div>
    );
  }
  const s = data.summary;
  const species = data.charts.species;
  return (
    <div className="bites">
      <section className="bites-intro">
        <p className="kicker">{s.source}, {s.years[0]} to {s.years[1]}</p>
        <h2 className="bites-hero">{pct(s.dog_share)} of reported animal bites were by dogs.</h2>
        <p className="muted">{s.dog_records.toLocaleString()} of {s.records.toLocaleString()} bite reports. These records are why
          DogWatch looks at where dogs gather and when they run towards people.</p>
      </section>

      <section className="figures" aria-label="Summary">
        <div><b>{s.dog_records.toLocaleString()}</b>dog bites reported</div>
        <div><b>{s.busiest_month}</b>busiest month for dog bites</div>
        <div><b>{pct(s.head_bite_share)}</b>of dog bites were to the head</div>
        <div><b>{s.rabies_positive} of {s.rabies_tested}</b>tested dogs had rabies</div>
      </section>

      <div className="bite-grid">
        <ChartCard id="species" c={species} t={t} />
        {ORDER.filter((k) => data.charts[k]).map((k) => <ChartCard key={k} id={k} c={data.charts[k]} t={t} />)}
      </div>
      <p className="small muted">Breed is recorded for {pct(s.breed_known_share)} of dog bites and vaccination for {pct(s.vaccination_recorded_share)}.
        Missing values are shown as "Not recorded" or "Unknown" rather than guessed.</p>
    </div>
  );
}
