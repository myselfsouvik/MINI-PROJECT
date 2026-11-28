// Chart.js set up once for the whole app: quiet axes, thin rounded bars with a 2px gap,
// hover tooltips, and colours read from the CSS tokens so light and dark mode both work.
import {
  BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip,
} from "chart.js";
import { useEffect, useState } from "react";

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip, Legend);

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Current theme colours; re-read when the system switches light/dark. */
export function useChartTheme() {
  const read = () => ({
    ink: css("--ink"), muted: css("--muted"), line: css("--line"), sheet: css("--sheet"),
    rest: css("--rest"), walk: css("--walk"), run: css("--run"), series: css("--rest"),
    font: css("--body") || "sans-serif",
  });
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setTheme(read());
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return theme;
}

/** Options for a bar chart. `stacked` for the activity timeline; `horizontal` for ranked lists. */
export function barOptions(t, { stacked = false, horizontal = false, yTitle, xTitle, tooltipLabel, legend = false } = {}) {
  const valueAxis = horizontal ? "x" : "y";
  const catAxis = horizontal ? "y" : "x";
  const tick = { color: t.muted, font: { family: t.font, size: 12 } };
  return {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: horizontal ? "y" : "x",
    animation: false,
    interaction: { mode: "index", intersect: false },           // hover anywhere in the column
    plugins: {
      legend: legend ? {
        display: true, position: "top", align: "start",
        labels: { color: t.ink, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3, font: { family: t.font, size: 13 } },
      } : { display: false },
      tooltip: {
        backgroundColor: t.ink, titleColor: t.sheet, bodyColor: t.sheet, padding: 10, cornerRadius: 8,
        boxPadding: 4, usePointStyle: true, titleFont: { family: t.font }, bodyFont: { family: t.font },
        callbacks: tooltipLabel ? { label: tooltipLabel } : {},
      },
    },
    scales: {
      [catAxis]: {
        stacked, grid: { display: false }, border: { color: t.line },
        ticks: { ...tick, autoSkip: true, maxRotation: 0, autoSkipPadding: 12 },
        title: xTitle && !horizontal ? { display: true, text: xTitle, color: t.muted, font: { family: t.font, size: 12 } } : undefined,
      },
      [valueAxis]: {
        stacked, beginAtZero: true, border: { display: false },
        grid: { color: t.line, drawTicks: false }, ticks: { ...tick, padding: 6, precision: 0 },
        title: yTitle ? { display: true, text: yTitle, color: t.muted, font: { family: t.font, size: 12 } } : undefined,
      },
    },
  };
}

/** Bar look from the mark specs: thin, 4px rounded data end, 2px surface gap between fills. */
export function barStyle(t, color, { stacked = false } = {}) {
  return {
    backgroundColor: color,
    borderColor: t.sheet,
    borderWidth: stacked ? { top: 2 } : 0,                     // the gap between stacked segments
    borderSkipped: stacked ? "bottom" : "start",
    borderRadius: stacked ? 0 : 4,
    categoryPercentage: 0.86,
    barPercentage: 0.94,
    maxBarThickness: 36,
  };
}
