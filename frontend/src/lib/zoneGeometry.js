// Where the camera picture really sits inside an <img> with object-fit: contain
// (letterbox bars), and converting clicks to 0..1 frame coordinates and back.

export function pictureRect(box, natural) {
  const nw = natural.width || 16, nh = natural.height || 9;
  const scale = Math.min(box.width / nw, box.height / nh);
  const w = nw * scale, h = nh * scale;
  return { left: (box.width - w) / 2, top: (box.height - h) / 2, w, h };
}

/** A click at (px, py) inside the box -> [x, y] in 0..1 of the frame, or null on the bars. */
export function toFrame(px, py, rect) {
  const x = (px - rect.left) / rect.w, y = (py - rect.top) / rect.h;
  if (!(x >= 0 && x <= 1 && y >= 0 && y <= 1)) return null;
  return [+x.toFixed(4), +y.toFixed(4)];
}

export const toBox = ([x, y], rect) => [rect.left + x * rect.w, rect.top + y * rect.h];
