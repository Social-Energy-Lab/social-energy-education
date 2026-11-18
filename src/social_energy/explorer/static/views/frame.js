// The paused frame: who is in it, who is close to whom now (physical) and whether they had been
// close before this window (social: familiar or a new constellation), the programme running,
// the self-reports in the window with what was written about them, and the people picked in the
// network side by side.
import { descriptionAt, descriptionsOf, frame, louderThan, pairHistory, pressesIn, programmeAt, sharedMoments, windowRange } from "../model.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const SHARED_S = 5 * 60;
// Close time before the window that makes a pair acquainted, and close: 1 h and 5 h.
const LEVEL_MIN = [60, 300];
const LEVEL_NAME = ["new", "acquainted", "close"];

export function create(el, ctx) {
  const { meta, b } = ctx;
  const binMin = meta.bin_seconds / 60;
  let histKey = "";
  let history = null;
  let sharedKey = null;
  let shared = null;
  let lastKey = "";

  const hours = (bins) => {
    const m = bins * binMin;
    return m < 60 ? `${m} min` : `${(m / 60).toFixed(m < 600 ? 1 : 0)} h`;
  };
  const name = (i) => esc(ctx.personName(i));
  const cut = (t) => (t.length > 160 ? `${t.slice(0, 159)}…` : t);

  function update(state, p, e, changed) {
    if (state.playing) {
      if (lastKey !== "playing") {
        lastKey = "playing";
        el.innerHTML = "<p class='muted'>Playing. Pause (space bar or ▶) to see who is together at that moment, with their place, the programme and what they wrote.</p>";
      }
      return;
    }
    const key = [Math.floor(state.bin), p.closeRssi, p.minBins, p.windowBins, state.picked.join(","),
      changed.has("theme")].join("|");
    if (key === lastKey) return;
    lastKey = key;

    const bin = Math.floor(state.bin);
    const startBin = Math.max(0, p.endBin - p.windowBins);
    const hk = `${p.closeRssi}|${startBin}`;
    if (hk !== histKey) {
      histKey = hk;
      history = pairHistory(b, p.closeRssi, startBin);
    }
    if (sharedKey !== p.closeRssi) {
      sharedKey = p.closeRssi;
      shared = sharedMoments(b, p.closeRssi, SHARED_S, meta.bin_seconds);
    }
    const vis = new Uint8Array(ctx.nNodes);
    const [slo, shi] = windowRange(b.seen.bin, p.endBin, p.windowBins);
    for (let i = slo; i < shi; i++) vis[b.seen.node[i]] = 1;
    const f = frame(e, history, LEVEL_MIN.map((m) => m / binMin), vis);

    // Place at the playhead.
    const locOf = new Int32Array(ctx.nNodes).fill(-1);
    const [rlo, rhi] = windowRange(b.rooms.bin, bin + 1, 1);
    for (let i = rlo; i < rhi; i++) locOf[b.rooms.node[i]] = b.rooms.loc[i];
    const place = (i) => (locOf[i] >= 0 ? esc(meta.locations[locOf[i]].label) : "<span class='muted'>not placed</span>");

    // Presses in the window.
    const pIdx = pressesIn(b, startBin * meta.bin_seconds, p.endBin * meta.bin_seconds);
    const pressCount = new Uint16Array(ctx.nNodes);
    for (const k of pIdx) pressCount[b.presses.node[k]]++;

    const picked = state.picked;
    const nTies = f.ties.length;
    const pct = (n) => (nTies ? ` (${Math.round((100 * n) / nTies)}%)` : "");
    const win = state.windowMinutes % 60 ? `${state.windowMinutes} min` : `${state.windowMinutes / 60} h`;
    const prog = programmeAt(ctx.events, bin);

    const parts = [];
    parts.push(`<p class="frame-sum"><b>${ctx.dayLabel(bin)} ${ctx.clockLabel(bin)}</b>, the ${win} before:
      <b>${f.people.length}</b> people heard, <b>${nTies}</b> ties. By how long the two had been close
      before this window: <span class="lv lv0"></span><b>${f.counts[0]}</b>${pct(f.counts[0])} <i>new</i> (under 1 h),
      <span class="lv lv1"></span><b>${f.counts[1]}</b>${pct(f.counts[1])} <i>acquainted</i> (1–5 h),
      <span class="lv lv2"></span><b>${f.counts[2]}</b>${pct(f.counts[2])} <i>close</i> (5 h or more).</p>`);
    if (ctx.events.length) {
      parts.push(`<p class="frame-prog">Programme now: ${prog.length
        ? prog.slice(0, 8).map((ev) => `<b>${esc(ev.label)}</b>${ev.all_camp ? "" : " <span class='muted'>(rooms)</span>"}`).join(" · ") +
          (prog.length > 8 ? ` · <span class="muted">+${prog.length - 8} more</span>` : "")
        : "<span class='muted'>nothing recorded</span>"}</p>`);
    }

    // How the halls sounded at the playhead, each against its own recorded time.
    if (ctx.sound) {
      const now = ctx.sound.rooms.map((room, r) => {
        const v = ctx.sound.leq[r][bin];
        return v === null ? `${esc(room)} <span class='muted'>not recorded</span>`
          : `${esc(room)} <b>louder than ${louderThan(ctx.sound.sorted[r], v)}%</b> of its recorded time`;
      });
      parts.push(`<p class="frame-prog">Sound now: ${now.join(" · ")}</p>`);
    }

    // Picked people side by side.
    if (!picked.length) {
      parts.push("<p class='hint muted small'>Pick people (a dot in the network, or a row below) to compare them side by side.</p>");
    }
    if (picked.length) {
      const tieOf = new Map(f.ties.map((t) => [t.a * 65536 + t.b, t]));
      const pk = (x, y) => Math.min(x, y) * 65536 + Math.max(x, y);
      const head = picked.map((i) => `<th>${name(i)}</th>`).join("");
      const rows = picked.map((i) => {
        const cells = picked.map((j) => {
          if (i === j) return "<td class='diag'>–</td>";
          const t = tieOf.get(pk(i, j));
          const before = history.get(pk(i, j)) ?? 0;
          return `<td class="${t ? `now lvc${t.level}` : ""}">` +
            `${t ? `<b>${t.bins * binMin} min</b> now` : "<span class='muted'>not close now</span>"}` +
            `<br><span class="muted">${before ? `${hours(before)} before` : "never before"}</span></td>`;
        }).join("");
        return `<tr><th>${name(i)} <span class="muted">${esc(ctx.courseName(ctx.nodeCourse[i]))}</span></th>${cells}</tr>`;
      }).join("");
      parts.push(`<div class="picked">
        <div class="chips">${picked.map((i) => `<span class="chip"><b>${name(i)}</b>
          ${ctx.openPerson ? `<button type="button" data-open="${i}" title="Open in the person view">open</button>` : ""}
          <button type="button" data-unpick="${i}" aria-label="Remove ${name(i)}">×</button></span>`).join("")}
          <button type="button" class="clear">clear</button></div>
        ${picked.length > 1 ? `<table class="pairs"><tr><th></th>${head}</tr>${rows}</table>
        <p class="muted small">Now: minutes at close range in the window. Before: close time from the start of the study to the window's start, at the same close range.</p>` : ""}
      </div>`);
    }

    // People in the frame, most ties first.
    const people = f.people.slice().sort((x, y) => y.ties - x.ties || x.node - y.node);
    const rows = people.map(({ node: i, ties, levels }) => `<tr data-node="${i}" class="${picked.includes(i) ? "on" : ""}">
      <td><span class="swatch" style="background:${ctx.nodeCourse[i] < 0 ? ctx.colors.unknown : ctx.colors.course[ctx.nodeCourse[i]]}"></span>${name(i)}</td>
      <td>${esc(ctx.courseName(ctx.nodeCourse[i]))}</td><td>${place(i)}</td>
      <td class="num">${ties}</td><td class="num">${levels[0] || ""}</td>
      <td class="num">${pressCount[i] || ""}</td></tr>`).join("");

    // Self-reports in the window, newest first.
    const presses = pIdx.slice().reverse().map((k) => {
      const node = b.presses.node[k];
      const sec = b.presses.sec[k];
      const d = descriptionAt(ctx.moments, node, sec);
      return `<li data-press="${k}" class="${d ? "has-text" : ""}">
        <span class="t">${ctx.clockLabel(sec / meta.bin_seconds)}</span>
        <b>${name(node)}</b>${shared[k] ? " <span class='tag'>shared</span>" : ""}
        ${d ? `<span class="desc">${esc(cut(d.text))}</span>` : ""}
      </li>`;
    }).join("");

    // What people in this frame wrote about this camp day (or, when picked, any day).
    const day = ctx.dayOfBin[bin];
    const writing = ctx.moments ? descriptionsOf(ctx.moments, { day }).filter((m) => vis[m.node]) : [];
    const pickedWriting = ctx.moments
      ? picked.flatMap((i) => descriptionsOf(ctx.moments, { node: i }).filter((m) => m.day !== day || !vis[m.node]))
      : [];
    const item = (m) => `<li data-moment="${ctx.moments.indexOf(m)}" class="has-text">
      <span class="t">${m.sec !== null ? ctx.clockLabel(m.sec / meta.bin_seconds) : m.day !== null ? ctx.dayLabel(ctx.dayRange(m.day)[0]).slice(0, 6) : "–"}</span>
      <b>${name(m.node)}</b> <span class="muted">${esc(m.when ?? "")}</span>
      <span class="desc">${esc(cut(m.text))}</span></li>`;

    parts.push(`<div class="frame-cols">
      <div><h3>People in this frame <span class="muted">(click to pick)</span></h3>
        <div class="scroll"><table class="frame-people"><tr><th>person</th><th>course</th><th>place now</th>
        <th title="Ties in the window">ties</th><th title="Ties with people close for under 1 h before this window">new</th><th title="Self-report presses in the window">presses</th></tr>${rows}</table></div></div>
      <div><h3>Self-reports in the window</h3>
        ${pIdx.length ? `<ul class="press-list">${presses}</ul>` : "<p class='muted'>No presses in this window.</p>"}
        ${ctx.moments ? `<h3>Written about this day by people in the frame</h3>
        ${writing.length ? `<ul class="press-list">${writing.map(item).join("")}</ul>` : "<p class='muted'>Nothing written about this day by the people heard now.</p>"}
        ${pickedWriting.length ? `<h3>Written by the picked people, other days</h3><ul class="press-list">${pickedWriting.map(item).join("")}</ul>` : ""}
        <p class="muted small">From the paper cards: what participants wrote about a moment they marked, with the time as they gave it. Click one to read it in full.</p>` : ""}</div>
    </div>`);
    el.innerHTML = parts.join("");

    for (const tr of el.querySelectorAll("tr[data-node]")) {
      tr.addEventListener("click", () => toggle(state, Number(tr.dataset.node)));
    }
    for (const btn of el.querySelectorAll("[data-unpick]")) {
      btn.addEventListener("click", () => toggle(state, Number(btn.dataset.unpick)));
    }
    for (const btn of el.querySelectorAll("[data-open]")) {
      btn.addEventListener("click", () => ctx.openPerson(Number(btn.dataset.open), bin));
    }
    el.querySelector(".clear")?.addEventListener("click", () => ctx.set({ picked: [] }));
    for (const li of el.querySelectorAll("li[data-press]")) {
      const k = Number(li.dataset.press);
      const d = descriptionAt(ctx.moments, b.presses.node[k], b.presses.sec[k]);
      if (d) li.addEventListener("click", () => ctx.showMoment(d));
    }
    for (const li of el.querySelectorAll("li[data-moment]")) {
      li.addEventListener("click", () => ctx.showMoment(ctx.moments[Number(li.dataset.moment)]));
    }
  }

  function toggle(state, i) {
    const has = state.picked.includes(i);
    ctx.set({ picked: has ? state.picked.filter((x) => x !== i) : [...state.picked, i] });
  }

  return { update };
}
