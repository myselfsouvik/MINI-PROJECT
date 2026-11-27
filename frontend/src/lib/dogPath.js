// A dog's path (points with x, y in 0..1 and an activity) split into lines of one
// activity each, so every stretch can be drawn in its activity colour.

/** Consecutive points with the same activity become one run; each run starts at the previous point. */
export function pathRuns(path) {
  const runs = [];
  path.forEach((p, i) => {
    const last = runs[runs.length - 1];
    if (last && last.activity === p.activity) last.points.push(p);
    else runs.push({ activity: p.activity, points: i ? [path[i - 1], p] : [p] });
  });
  return runs.filter((r) => r.points.length > 1);
}
