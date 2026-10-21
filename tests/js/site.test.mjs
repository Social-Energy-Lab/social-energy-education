// The public site's pure helpers: language, number placeholders, the player's timeline.
//
// player.js imports ./model.js, which the build copies next to it from the explorer, so the
// static files are assembled into a temporary directory the way build_site does.
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const SRC = fileURLToPath(new URL("../../src/social_energy/", import.meta.url));
const SITE = mkdtempSync(join(tmpdir(), "see-site-test-"));
cpSync(join(SRC, "site", "static"), SITE, { recursive: true });
cpSync(join(SRC, "explorer", "static", "model.js"), join(SITE, "model.js"));
process.on("exit", () => rmSync(SITE, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(SITE, name)).href);

const i18n = await load("i18n.js");
const player = await load("player.js");
const de = (await load("strings/de.js")).default;
const en = (await load("strings/en.js")).default;

test("fill formats numbers for the language, at most two decimals", () => {
  assert.equal(i18n.fill("x {a}", { a: 2.064 }, "de"), "x 2,06");
  assert.equal(i18n.fill("x {a}", { a: 2.064 }, "en"), "x 2.06");
  assert.equal(i18n.fill("{a} and {a}", { a: 1234.5 }, "de"), "1.234,5 and 1.234,5");
});

test("an unknown or non-numeric placeholder becomes a dash", () => {
  assert.equal(i18n.fill("x {nope}", {}, "de"), "x –");
  assert.equal(i18n.fill("x {a}", { a: NaN }, "de"), "x –");
  assert.equal(i18n.fill("x {a}", { a: null }, "en"), "x –");
});

test("string values are inserted as they are, text without placeholders is unchanged", () => {
  assert.equal(i18n.fill("{day}, {n}", { day: "Mo 17.", n: 3 }, "de"), "Mo 17., 3");
  assert.equal(i18n.fill("plain", {}, "en"), "plain");
});

test("language: ?lang= first, then the stored choice, then the browser, else German", () => {
  assert.equal(i18n.pickLang({ search: "?lang=en", stored: "de", browser: "de-DE" }), "en");
  assert.equal(i18n.pickLang({ search: "?lang=fr", stored: "en", browser: "de" }), "en");
  assert.equal(i18n.pickLang({ search: "", stored: null, browser: "en-GB" }), "en");
  assert.equal(i18n.pickLang({ search: "", stored: null, browser: "fr-FR" }), "de");
  assert.equal(i18n.pickLang({}), "de");
});

test("t looks up the current language and fills the numbers", () => {
  i18n.setLang("en");
  i18n.setNumbers({ n_participants: 12 });
  assert.equal(i18n.getLang(), "en");
  assert.equal(i18n.t("no.such.key"), "no.such.key");
  assert.equal(i18n.t("banner_synthetic"), en.banner_synthetic);
  i18n.setLang("de");
  assert.equal(i18n.t("banner_synthetic"), de.banner_synthetic);
});

test("both languages have the same keys and the same placeholders", () => {
  assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort());
  const holes = (s) => (s.match(/\{[a-z0-9_]+\}/g) ?? []).sort();
  for (const k of Object.keys(de)) assert.deepEqual(holes(de[k]), holes(en[k]), k);
});

test("copy states no number literally: every digit sits in a placeholder", () => {
  // Method settings are written as words; a digit outside {…} could be a leaked result.
  const allowed = /\{[a-z0-9_]+\}|https?:\/\/\S+|\b2026\b/g;
  for (const strings of [de, en]) {
    for (const [k, v] of Object.entries(strings)) {
      assert.ok(!/\d/.test(v.replace(allowed, "")), `${k}: ${v}`);
    }
  }
});

test("the synthetic banner exists in both languages", () => {
  assert.match(de.banner_synthetic, /erfundenen Daten/);
  assert.match(en.banner_synthetic, /synthetic data/);
});

test("shownBins keeps only the bins with shown == 1", () => {
  const bins = { shown: Uint8Array.from([1, 1, 0, 0, 1, 0, 1]) };
  assert.deepEqual(Array.from(player.shownBins(bins)), [0, 1, 4, 6]);
  assert.ok(player.shownBins(bins) instanceof Uint32Array);
});

test("startPaused under reduced motion, from a media query list or matchMedia itself", () => {
  assert.equal(player.startPaused({ matches: true }), true);
  assert.equal(player.startPaused({ matches: false }), false);
  assert.equal(player.startPaused((q) => ({ matches: q.includes("reduce") })), true);
  assert.equal(player.startPaused(undefined), false);
});

test("closeView gives every public pair a close-range reading for model.edges", () => {
  const b = {
    pairs: {
      bin: Uint16Array.from([0, 1, 2, 2]),
      a: Uint16Array.from([0, 0, 0, 1]),
      b: Uint16Array.from([1, 1, 1, 2]),
    },
  };
  const e = player.windowEdges(player.closeView(b), 3, 24, 3);
  assert.deepEqual([e.a, e.b, e.bins], [[0], [1], [3]]);
  assert.equal(b.pairs.rssi, undefined, "the decoded bundle is not changed");
});

test("glow fades over eight bins after a press and is zero before it", () => {
  const presses = { bin: Uint16Array.from([10, 12]), node: Uint16Array.from([0, 1]) };
  const g = player.glowAt(presses, 12, 3);
  assert.ok(Math.abs(g[0] - (1 - 2 / 8)) < 1e-9);
  assert.equal(g[1], 1);
  assert.equal(g[2], 0);
  assert.deepEqual(Array.from(player.glowAt(presses, 9, 3)), [0, 0, 0]);
  assert.equal(player.glowAt(presses, 18, 3)[0], 0);
});

test("night gaps: a jump between consecutive shown bins", () => {
  const shown = Uint32Array.from([0, 1, 2, 9, 10, 20]);
  assert.equal(player.isGap(shown, 2), true); // 2 -> 9
  assert.equal(player.isGap(shown, 1), false);
  assert.equal(player.isGap(shown, 5), false); // last one
});

test("dayStarts: the first shown index of each camp day", () => {
  const bins = { shown: Uint8Array.from([1, 1, 0, 1, 1, 1]), day: Uint8Array.from([0, 0, 0, 1, 1, 2]) };
  const shown = player.shownBins(bins);
  assert.deepEqual(player.dayStarts(bins, shown), [
    { day: 0, index: 0, bin: 0 },
    { day: 1, index: 2, bin: 3 },
    { day: 2, index: 4, bin: 5 },
  ]);
});

test("signed copy: the sentence follows the sign, the number is shown without it", () => {
  assert.deepEqual(i18n.signed("ch_moments_body3", "company_gain", { company_gain: 1.5 }), {
    key: "ch_moments_body3_pos",
    extra: { company_gain_abs: 1.5 },
  });
  assert.deepEqual(i18n.signed("ch_moments_body3", "company_gain", { company_gain: -0.4 }), {
    key: "ch_moments_body3_neg",
    extra: { company_gain_abs: 0.4 },
  });
  // No number: the neutral-looking positive form, with a dash for the value.
  assert.equal(i18n.signed("x", "company_gain", {}).key, "x_pos");
  i18n.setLang("de");
  i18n.setNumbers({ company_gain: -2 });
  const { key, extra } = i18n.signed("ch_moments_body3", "company_gain");
  assert.match(i18n.t(key, extra), /2 Menschen weniger/);
});

// ----------------------------------------------------------------- chapters 4 and 6

const moments = await load("chapters/moments.js").catch(() => ({}));
const nullChapter = await load("chapters/null.js").catch(() => ({}));

test("latencyBars: one bar per band, ordered by where the band starts", () => {
  const rows = [
    { band: "30-60", people: 9, ratio: 1.1, ratio_lo: 0.8, ratio_hi: 1.4 },
    { band: "0-10", people: 9, ratio: 2, ratio_lo: 1.5, ratio_hi: 2.5 },
    { band: "60+", people: 9, ratio: 0.9, ratio_lo: 0.7, ratio_hi: 1.2 },
    { band: "10-30", people: 9, ratio: 1.3, ratio_lo: 1, ratio_hi: 1.7 },
  ];
  assert.deepEqual(moments.latencyBars(rows), [
    { band: "0-10", ratio: 2, lo: 1.5, hi: 2.5 },
    { band: "10-30", ratio: 1.3, lo: 1, hi: 1.7 },
    { band: "30-60", ratio: 1.1, lo: 0.8, hi: 1.4 },
    { band: "60+", ratio: 0.9, lo: 0.7, hi: 1.2 },
  ]);
});

test("latencyBars: a row without a ratio is left out, no rows give no bars", () => {
  const rows = [{ band: "0-10", ratio: null }, { band: "10-30", ratio: 1.2 }];
  assert.deepEqual(
    moments.latencyBars(rows).map((r) => r.band),
    ["10-30"],
  );
  assert.deepEqual(moments.latencyBars(undefined), []);
});

test("forestRows: crossesNull at zero for SD effects and at one for rate ratios", () => {
  const rows = [
    { test: "c1", label: "c1", estimate: 0.2, lo: -0.1, hi: 0.5, scale: "sd" },
    { test: "c2", label: "c2", estimate: 0.4, lo: 0.1, hi: 0.7, scale: "sd" },
    { test: "c4", label: "c4", estimate: 1.2, lo: 0.9, hi: 1.6, scale: "rr" },
    { test: "c5", label: "c5", estimate: 0.5, lo: 0.2, hi: 0.8, scale: "rr" },
  ];
  const out = nullChapter.forestRows(rows);
  assert.deepEqual(
    out.map((r) => [r.label, r.scale, r.crossesNull]),
    [
      ["c1", "sd", true],
      ["c2", "sd", false],
      ["c4", "rr", true],
      ["c5", "rr", false],
    ],
  );
  assert.deepEqual(Object.keys(out[0]).sort(), [
    "crossesNull",
    "estimate",
    "hi",
    "label",
    "lo",
    "scale",
    "test",
  ]);
  // A rate ratio whose interval spans zero but not one does not cross its null.
  assert.equal(
    nullChapter.forestRows([{ label: "x", estimate: 0.5, lo: 0.2, hi: 0.9, scale: "rr" }])[0]
      .crossesNull,
    false,
  );
});

test("forestRows: rows with an unknown scale or a missing number are left out", () => {
  const rows = [
    { label: "a", estimate: 0.1, lo: -0.2, hi: 0.3, scale: "odds" },
    { label: "b", estimate: null, lo: -0.2, hi: 0.3, scale: "sd" },
    { label: "c", estimate: 0.1, lo: -0.2, hi: 0.3, scale: "sd" },
  ];
  assert.deepEqual(
    nullChapter.forestRows(rows).map((r) => r.label),
    ["c"],
  );
  assert.deepEqual(nullChapter.forestRows(undefined), []);
});
