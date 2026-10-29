// The team-meeting deck: slides are the <section class="slide"> elements of index.html.
// Keys: → ↓ PageDown Space next · ← ↑ PageUp previous · Home/End · F full screen · N notes ·
// L light/dark. The theme is the site's: dark, light when the device asks; L forces the other
// one (a washed-out projector wants light). On a narrow screen the slides simply scroll.
//
// Numbers reach the slides only through {placeholders} in the HTML, filled from the public
// asset's aggregates.numbers at runtime ({+name} shows the sign). A missing number shows "–".
// A [data-viz] element is drawn when its slide is first shown.
import { loadSite } from "../data.js";
import { setLang, setNumbers, t } from "../i18n.js";
import { mountPlayer, startPaused } from "../player.js";
import {
  drawClockBar,
  drawCopress,
  drawDashboard,
  drawEdaProfile,
  drawGradients,
  drawLogic,
  drawReasons,
  drawSky,
  drawState,
  drawSync,
} from "./viz.js";

// --- pure helpers (tested in tests/js/deck.test.mjs) ---------------------------------------

/** `{name}` → the number in English, at most `digits` decimals; `{+name}` adds the sign. */
export function fillDeck(template, numbers, digits = 2) {
  const fmt = new Intl.NumberFormat("en", { maximumFractionDigits: digits });
  return template.replace(/\{(\+?)([a-z0-9_]+)\}/g, (_, plus, name) => {
    const v = numbers?.[name];
    if (typeof v !== "number" || !Number.isFinite(v)) return "–";
    const s = fmt.format(v);
    return plus && v > 0 ? `+${s}` : s;
  });
}

/** The theme L switches to: the opposite of the forced one, else of what the device shows. */
export function nextTheme(forced, deviceLight) {
  const light = forced ? forced === "light" : Boolean(deviceLight);
  return light ? "dark" : "light";
}

/** The slide number as the site numbers its chapters: 01, 02, … */
export const slideNumber = (i) => String(i + 1).padStart(2, "0");

/** The slide index a location hash points to (`#3` is the third slide), clamped. */
export function slideFromHash(hash, count) {
  const n = Number.parseInt(String(hash ?? "").replace(/^#\/?/, ""), 10);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(count - 1, n - 1));
}

/** What a key does: +1, -1, "first", "last", "full", "notes", "theme" or null. */
export function keyAction(key) {
  if (["ArrowRight", "ArrowDown", "PageDown", " ", "Enter"].includes(key)) return 1;
  if (["ArrowLeft", "ArrowUp", "PageUp", "Backspace"].includes(key)) return -1;
  if (key === "Home") return "first";
  if (key === "End") return "last";
  if (key === "f" || key === "F") return "full";
  if (key === "n" || key === "N") return "notes";
  if (key === "l" || key === "L") return "theme";
  return null;
}

// --- the page --------------------------------------------------------------------------------

const reduced = startPaused(globalThis.matchMedia?.bind(globalThis));
const narrowQuery = globalThis.matchMedia?.("(max-width: 760px)");
let site = null;
let slides = [];
let current = 0;
const drawn = new WeakSet();

function fillPlaceholders(root, numbers) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (walker.currentNode.nodeValue.includes("{")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) node.nodeValue = fillDeck(node.nodeValue, numbers);
}

async function chapter(name) {
  try {
    return await import(`../chapters/${name}.js`);
  } catch {
    return null;
  }
}

async function drawViz(el) {
  const agg = site?.agg ?? {};
  const opts = { reduced, t, lang: () => "en", meta: site?.meta ?? null };
  const kind = el.dataset.viz;
  try {
    if (kind === "network") {
      if (!site) return;
      el.classList.add("player-host");
      mountPlayer(el, site, t, { lang: () => "en", paused: true, reduced });
    } else if (["null", "moments", "circles", "day", "places"].includes(kind)) {
      const mod = await chapter(kind);
      mod?.render(el, agg, t, opts);
    } else if (kind === "state") drawState(el, agg, opts);
    else if (kind === "sync") {
      drawSync(el, opts);
      drawClockBar(el, agg.numbers);
    } else if (kind === "eda") drawEdaProfile(el, agg, opts);
    else if (kind === "reasons") drawReasons(el, agg, opts);
    else if (kind === "gradients") {
      drawGradients(el, agg, opts);
      const more = document.createElement("div");
      el.append(more);
      drawCopress(more, agg, opts);
    } else if (kind === "logic") drawLogic(el, opts);
    else if (kind === "dashboard") drawDashboard(el, opts);
    else if (kind === "sky") drawSky(el);
  } catch (err) {
    console.error(`viz ${kind}`, err);
  }
}

function drawSlide(slide) {
  if (drawn.has(slide)) return;
  drawn.add(slide);
  for (const el of slide.querySelectorAll("[data-viz]")) drawViz(el);
}

const isScroll = () => Boolean(narrowQuery?.matches);

function show(i, { focus = false } = {}) {
  current = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach((s, k) => {
    s.classList.toggle("active", k === current);
    s.setAttribute("aria-hidden", String(!isScroll() && k !== current));
  });
  document.getElementById("counter").textContent = `${current + 1} / ${slides.length}`;
  document.body.classList.toggle(
    "on-night",
    !isScroll() && slides[current].classList.contains("night-slide"),
  );
  document.getElementById("progress").style.width = `${((current + 1) / slides.length) * 100}%`;
  try {
    history.replaceState(null, "", `#${current + 1}`);
  } catch {
    // file:// cannot rewrite its URL; the deck still moves.
  }
  if (isScroll()) {
    if (focus) slides[current].scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
  } else {
    // Draw after layout, so a chart measures the slide it is on.
    requestAnimationFrame(() => drawSlide(slides[current]));
  }
}

function fullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}

function onKey(e) {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  // The network's own controls keep their keys (arrows scrub, space plays).
  if (e.target.closest?.(".player, input, textarea, select")) return;
  const act = keyAction(e.key);
  if (act === null) return;
  if (e.key === " " && e.target.closest?.("button, a")) return;
  e.preventDefault();
  if (act === "full") fullscreen();
  else if (act === "notes") document.body.classList.toggle("show-notes");
  else if (act === "theme") {
    const root = document.documentElement;
    const deviceLight = globalThis.matchMedia?.("(prefers-color-scheme: light)").matches;
    root.dataset.theme = nextTheme(root.dataset.theme, deviceLight);
  } else if (act === "first") show(0, { focus: true });
  else if (act === "last") show(slides.length - 1, { focus: true });
  else show(current + act, { focus: true });
}

function onSwipe() {
  let x0 = null;
  let y0 = null;
  document.addEventListener("touchstart", (e) => {
    if (isScroll() || e.target.closest(".player")) return;
    x0 = e.touches[0].clientX;
    y0 = e.touches[0].clientY;
  }, { passive: true }); // prettier-ignore
  document.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    const dy = e.changedTouches[0].clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) show(current + (dx < 0 ? 1 : -1));
  });
}

function watchScroll() {
  // In scroll mode every slide draws as it comes into view, and the counter follows.
  if (typeof IntersectionObserver === "undefined") {
    slides.forEach(drawSlide);
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      if (!isScroll()) return;
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        drawSlide(e.target);
        const k = slides.indexOf(e.target);
        if (k >= 0 && e.intersectionRatio > 0.5) {
          current = k;
          document.getElementById("counter").textContent = `${k + 1} / ${slides.length}`;
        }
      }
    },
    { threshold: [0.05, 0.55] },
  );
  slides.forEach((s) => io.observe(s));
}

async function main() {
  setLang("en");
  slides = [...document.querySelectorAll(".slide")];
  slides.forEach((s, k) => {
    const h2 = s.querySelector("h2");
    if (h2) h2.dataset.n = slideNumber(k);
  });
  document.body.classList.toggle("scroll", isScroll());
  narrowQuery?.addEventListener?.("change", () => {
    document.body.classList.toggle("scroll", isScroll());
    show(current);
  });
  try {
    site = await loadSite("../data/");
  } catch (err) {
    console.error(err);
    document.getElementById("data-error").hidden = false;
  }
  const numbers = site?.agg?.numbers ?? {};
  setNumbers(numbers);
  fillPlaceholders(document.getElementById("slides"), numbers);
  document.getElementById("badge").hidden = !site?.meta?.synthetic;
  document.addEventListener("keydown", onKey);
  document.getElementById("prev").addEventListener("click", () => show(current - 1));
  document.getElementById("next").addEventListener("click", () => show(current + 1));
  onSwipe();
  watchScroll();
  show(slideFromHash(location.hash, slides.length), { focus: isScroll() });
  document.body.classList.add("ready");
}

if (typeof document !== "undefined") main();
