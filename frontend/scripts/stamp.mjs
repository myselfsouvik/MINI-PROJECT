// Runs after `npm run build`: writes dist/source.sha256, a fingerprint of the code the build came from.
// start.bat / start.sh (backend/build_frontend.py, same recipe) compare it with the code to decide
// whether the dashboard needs rebuilding. Line endings don't count, so Windows and Mac/Linux agree.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const SOURCES = ["src", "public", "index.html", "package.json", "package-lock.json", "vite.config.js"];

const walk = (p) => (statSync(p).isDirectory() ? readdirSync(p).flatMap((n) => walk(join(p, n))) : [p]);
const rel = (f) => relative(root, f).split(sep).join("/");

const hash = createHash("sha256");
for (const name of SOURCES) {
  const p = join(root, name);
  if (!existsSync(p)) continue;
  const files = walk(p).sort((a, b) => (rel(a) < rel(b) ? -1 : rel(a) > rel(b) ? 1 : 0));
  for (const f of files) {
    const text = readFileSync(f).toString("latin1").replaceAll("\r\n", "\n");
    hash.update(Buffer.concat([Buffer.from(rel(f) + "\0"), Buffer.from(text, "latin1"), Buffer.from("\0")]));
  }
}
writeFileSync(join(root, "dist", "source.sha256"), hash.digest("hex") + "\n");
