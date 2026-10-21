// The page: copy in the chosen language, the synthetic banner, the hero player and the story
// chapters. A chapter is ./chapters/<name>.js exporting render(el, agg, t, opts); a chapter
// that is not there yet leaves a quiet placeholder and the rest of the page works.
import { loadSite } from "./data.js";
import { getLang, initLang, setLang, setNumbers, t } from "./i18n.js";
import { mountPlayer, startPaused } from "./player.js";

const CHAPTERS = ["day", "circles", "moments", "places", "null", "how"];
const reduced = startPaused(globalThis.matchMedia?.bind(globalThis));
const modules = new Map();
let site = null;
let player = null;

function applyStrings() {
  document.documentElement.lang = getLang();
  document.title = t("page_title");
  document.querySelector('meta[name="description"]')?.setAttribute("content", t("page_description"));
  for (const node of document.querySelectorAll("[data-t]")) node.textContent = t(node.dataset.t);
  const toggle = document.getElementById("lang");
  toggle.textContent = t("lang_switch");
  toggle.setAttribute("aria-label", t("lang_switch_label"));
  toggle.lang = getLang() === "de" ? "en" : "de";
}

function chartFor(name) {
  return document.getElementById(`chart-${name}`);
}

async function loadChapter(name) {
  if (!modules.has(name)) {
    modules.set(
      name,
      import(`./chapters/${name}.js`).catch(() => null), // not built yet
    );
  }
  return modules.get(name);
}

async function renderChapters() {
  const opts = { reduced, player, lang: getLang };
  await Promise.all(
    CHAPTERS.map(async (name) => {
      const el = chartFor(name);
      if (!el) return;
      const mod = await loadChapter(name);
      el.replaceChildren();
      if (!mod?.render) {
        if (name !== "how") {
          const p = document.createElement("p");
          p.className = "pending";
          p.textContent = t("chart_pending");
          el.append(p);
        }
        return;
      }
      try {
        mod.render(el, site?.agg ?? {}, t, opts);
      } catch (err) {
        console.error(`chapter ${name}`, err);
      }
    }),
  );
}

function switchLang() {
  setLang(getLang() === "de" ? "en" : "de", true);
  try {
    const url = new URL(location.href);
    url.searchParams.set("lang", getLang());
    history.replaceState(null, "", url);
  } catch {
    // An opaque origin (file://) cannot rewrite its URL; the language still switches.
  }
  applyStrings();
  player?.relabel();
  renderChapters();
}

async function main() {
  initLang();
  applyStrings();
  document.getElementById("lang").addEventListener("click", switchLang);
  const host = document.getElementById("hero-player");
  try {
    site = await loadSite("data/");
  } catch (err) {
    console.error(err);
    host.innerHTML = "";
    const p = document.createElement("p");
    p.className = "error";
    p.dataset.t = "player_error";
    p.textContent = t("player_error");
    host.append(p);
    renderChapters();
    return;
  }
  setNumbers(site.agg?.numbers ?? {});
  document.getElementById("banner").hidden = !site.meta.synthetic;
  applyStrings();
  player = mountPlayer(host, site, t, { lang: getLang, paused: reduced, reduced });
  await renderChapters();
}

main();
