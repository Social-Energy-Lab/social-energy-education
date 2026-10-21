// Load the public data: meta, the binary tables (decoded by the explorer's model.js) and the
// camp-level aggregates. Everything is same-origin, under data/.
import { decode } from "./model.js";

async function fetchOk(url, kind) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return kind === "json" ? res.json() : res.arrayBuffer();
}

/** {meta, b, agg} for the site; agg is {} when the aggregates are missing. */
export async function loadSite(base = "data/") {
  const meta = await fetchOk(`${base}meta.json`, "json");
  const names = Object.keys(meta.files);
  const [buffers, agg] = await Promise.all([
    Promise.all(names.map((n) => fetchOk(`${base}${n}.bin`, "bin"))),
    fetchOk(`${base}aggregates.json`, "json").catch(() => ({})),
  ]);
  const b = decode(meta, Object.fromEntries(names.map((n, i) => [n, buffers[i]])));
  return { meta, b, agg };
}
