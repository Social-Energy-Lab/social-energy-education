// Language and copy: German by default, English by toggle. Numbers reach the copy only through
// {placeholders}, filled from aggregates.numbers at runtime, so no result is written in git.
import de from "./strings/de.js";
import en from "./strings/en.js";

export const LANGS = { de, en };
const STORAGE_KEY = "see-lang";
const supported = (v) => {
  const code = typeof v === "string" ? v.slice(0, 2).toLowerCase() : "";
  return Object.hasOwn(LANGS, code) ? code : null;
};

let lang = "de";
let numbers = {};

/** `{name}` → the number formatted for `lang` (at most two decimals), a string as it is, else "–". */
export function fill(template, values, lang) {
  const fmt = new Intl.NumberFormat(lang, { maximumFractionDigits: 2 });
  return template.replace(/\{([a-z0-9_]+)\}/g, (_, name) => {
    const v = values?.[name];
    if (typeof v === "number") return Number.isFinite(v) ? fmt.format(v) : "–";
    if (typeof v === "string") return v;
    return "–";
  });
}

/** `?lang=` first, then the stored choice, then the browser's language, else German. */
export function pickLang({ search = "", stored = null, browser = "" } = {}) {
  const fromUrl = new URLSearchParams(search).get("lang");
  return supported(fromUrl) ?? supported(stored) ?? supported(browser) ?? "de";
}

function readStored() {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

/** Pick the language from the page's URL, storage and browser. Call once at start. */
export function initLang() {
  lang = pickLang({
    search: globalThis.location?.search ?? "",
    stored: readStored(),
    browser: globalThis.navigator?.language ?? "",
  });
  return lang;
}

export function getLang() {
  return lang;
}

/** Switch language; `remember` stores the choice for the next visit (when storage works). */
export function setLang(next, remember = false) {
  lang = supported(next) ?? "de";
  if (remember) {
    try {
      globalThis.localStorage?.setItem(STORAGE_KEY, lang);
    } catch {
      // Private window or blocked storage: the choice lasts for this visit only.
    }
  }
  return lang;
}

export function setNumbers(values) {
  numbers = values ?? {};
}

/** The copy for `key` in the current language, numbers filled; `extra` adds more values. */
export function t(key, extra) {
  const text = LANGS[lang][key] ?? LANGS.de[key];
  if (text === undefined) return key;
  return fill(text, extra ? { ...numbers, ...extra } : numbers, lang);
}
