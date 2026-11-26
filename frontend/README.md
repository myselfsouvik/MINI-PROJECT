# frontend

React dashboard (Live, Dogs, Analytics, Alerts, Zones, Model, Insights). Owner: Nandini.

**Insights page:** `GET /api/insights` returns every chart as `{title, labels, values, note}`, so each one is
`new Chart(el, {type: "bar", data: {labels: c.labels, datasets: [{label: c.title, data: c.values}]}})`.
Show `note` under the chart; it explains what the numbers can and can't say.

See [PLAN.md](../PLAN.md) for the full roadmap.

## Connecting to the backend

- **Develop:** run the backend (`python -m backend.server --demo`), then `npm run dev`. CORS already allows `http://localhost:5173`. Simplest is a Vite proxy, so the code can use relative URLs:

  ```js
  // vite.config.js
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/media": "http://127.0.0.1:8000",
                     "/ws": { target: "ws://127.0.0.1:8000", ws: true } } }
  ```

- **Demo:** `npm run build`, then the backend serves `frontend/dist` at `http://127.0.0.1:8000/`, so one command starts everything. Use relative URLs (`/api/...`) and client-side routes. The DogWatch console stays at `/console`.
- **Other devices** (phone or a teammate's laptop): the server prints an access token. Read `?token=` from the page URL and send it as an `X-Access-Token` header (or `?token=` on `<img>` and WebSocket URLs).
- **API reference:** [backend/README.md](../backend/README.md) and the live docs at `http://127.0.0.1:8000/docs`.

