// Talking to the DogWatch server.
//
// Other devices (a phone, a teammate's laptop) open the app with ?token=... (the server prints it).
// We read it once, keep it for this browser tab, and send it with every request:
// as the X-Access-Token header for fetch, and as ?token= on <img>, <video>, links and WebSockets,
// which can't send headers. On the laptop itself no token is needed.

const KEY = "dogwatch-token";

export function readToken(search = globalThis.location?.search ?? "", store = globalThis.sessionStorage) {
  const fromUrl = new URLSearchParams(search).get("token");
  try {
    if (fromUrl) store?.setItem(KEY, fromUrl);
    return fromUrl || store?.getItem(KEY) || null;
  } catch {
    return fromUrl || null; // storage blocked (private mode): the URL still works
  }
}

let token = readToken();
export const getToken = () => token;
export const setToken = (t) => { token = t || null; };

/** Add ?token= to a URL when we have one (for <img src>, links, WebSockets). */
export function withToken(url, t = token) {
  if (!url || !t) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t);
}

export function wsUrl(path, loc = globalThis.location) {
  const proto = loc.protocol === "https:" ? "wss" : "ws";
  return withToken(`${proto}://${loc.host}${path}`);
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** fetch() a JSON API path. Throws ApiError with the server's message on failure. */
export async function api(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  const h = { ...headers };
  if (token) h["X-Access-Token"] = token;
  let payload = body;
  if (body !== undefined && !raw) {
    h["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(path, { method, headers: h, body: payload });
  } catch {
    throw new ApiError("Can't reach the DogWatch server. Check that it is still running on the laptop.", 0);
  }
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join("; ") : data.detail;
    const msg = r.status === 401
      ? "This device needs the access link. Open the address the laptop shows (it ends in ?token=...)."
      : detail || r.statusText || `Request failed (${r.status})`;
    throw new ApiError(msg, r.status);
  }
  return r.status === 204 ? null : r.json();
}
