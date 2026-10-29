// The team-meeting deck's pure helpers: placeholders, navigation, and the rows each chart draws.
//
// The deck imports ../player.js, which imports ./model.js from the explorer, so the static files
// are assembled into a temporary directory the way build_site does.
import assert from "node:assert/strict";
import { cpSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const SRC = fileURLToPath(new URL("../../src/social_energy/", import.meta.url));
const SITE = mkdtempSync(join(tmpdir(), "see-deck-test-"));
cpSync(join(SRC, "site", "static"), SITE, { recursive: true });
cpSync(join(SRC, "explorer", "static", "model.js"), join(SITE, "model.js"));
process.on("exit", () => rmSync(SITE, { recursive: true, force: true }));
const load = (name) => import(pathToFileURL(join(SITE, name)).href);

const deck = await load("deck/deck.js");
const viz = await load("deck/viz.js");

test("placeholders are filled in English, a missing number is a dash, + shows the sign", () => {
  assert.equal(deck.fillDeck("{a}× ({b} to {c})", { a: 2.064, b: 1.6, c: 1234.5 }), "2.06× (1.6 to 1,234.5)");
  assert.equal(deck.fillDeck("{nope} and {a}", { a: NaN }), "– and –");
  assert.equal(deck.fillDeck("{+a} / {+b} / {+c}", { a: 0.33, b: -0.15, c: 0 }), "+0.33 / -0.15 / 0");
  assert.equal(deck.fillDeck("plain {text", {}), "plain {text");
});

test("the hash picks a slide, clamped to the deck", () => {
  assert.equal(deck.slideFromHash("#3", 15), 2);
  assert.equal(deck.slideFromHash("#/15", 15), 14);
  assert.equal(deck.slideFromHash("#99", 15), 14);
  assert.equal(deck.slideFromHash("#0", 15), 0);
  assert.equal(deck.slideFromHash("", 15), 0);
});

test("arrows, space and page keys move; F, N and L toggle", () => {
  for (const k of ["ArrowRight", "ArrowDown", "PageDown", " "]) assert.equal(deck.keyAction(k), 1);
  for (const k of ["ArrowLeft", "ArrowUp", "PageUp"]) assert.equal(deck.keyAction(k), -1);
  assert.equal(deck.keyAction("Home"), "first");
  assert.equal(deck.keyAction("End"), "last");
  assert.equal(deck.keyAction("f"), "full");
  assert.equal(deck.keyAction("N"), "notes");
  assert.equal(deck.keyAction("l"), "theme");
  assert.equal(deck.keyAction("L"), "theme");
  assert.equal(deck.keyAction("d"), null);
  assert.equal(deck.keyAction("x"), null);
});

test("L switches away from the theme on screen: the forced one, else the device's", () => {
  assert.equal(deck.nextTheme(undefined, false), "light");
  assert.equal(deck.nextTheme(undefined, true), "dark");
  assert.equal(deck.nextTheme("light", false), "dark");
  assert.equal(deck.nextTheme("dark", true), "light");
  assert.equal(deck.slideNumber(3), "04");
});

test("each source says in one line why it keeps less than it recorded", () => {
  const rows = viz.stateRows([
    { source: "beacons", people: 79, raw: 1000, clean: 983 },
    { source: "survey", people: 80, raw: 10, clean: 9 },
    { source: "heart_rate", people: 60, raw: 100, clean: 49 },
    { source: "interviews", people: 60, raw: 12, clean: 10 },
  ]);
  const why = Object.fromEntries(rows.map((r) => [r.key, viz.dropReason(r)]));
  assert.match(why.beacons, /^Dropped, about 2%: copies/);
  assert.equal(why.survey, "One double submission removed.");
  assert.match(why.heart_rate, /about half of the worn minutes/);
  assert.match(why.interviews, /^2 recordings are not from participants/);
  assert.match(viz.dropReason({ key: "presses" }), /under 60 s apart are one episode/);
  assert.equal(viz.roughShare(0.4), "about 0.4%");
});

test("data state keeps the source order and drops incomplete rows", () => {
  const rows = viz.stateRows([
    { source: "survey", people: 80, raw: 88, clean: 87 },
    { source: "beacons", people: 79, raw: 1000, clean: 900 },
    { source: "eda", people: 70, raw: 0, clean: 0 },
    { source: "nonsense", people: 9, raw: 5, clean: 5 },
  ]);
  assert.deepEqual(rows.map((r) => [r.key, Math.round(r.kept)]), [["beacons", 90], ["survey", 99]]);
});

test("short counts", () => {
  assert.equal(viz.shortCount(63722085), "63.7M");
  assert.equal(viz.shortCount(48927), "48.9k");
  assert.equal(viz.shortCount(2534), "2,534");
  assert.equal(viz.shortCount(undefined), "–");
});

test("gradient rows group by measure in a fixed order, samples in a fixed order", () => {
  const groups = viz.gradientGroups([
    { measure: "lust", sample: "between", r: 0.01, null_lo: -0.03, null_hi: 0.03 },
    { measure: "trust", sample: "within", r: -0.1, null_lo: -0.09, null_hi: 0.1 },
    { measure: "trust", sample: "all", r: -0.01, null_lo: -0.03, null_hi: 0.04 },
    { measure: "trust", sample: "between", r: null, null_lo: -0.03, null_hi: 0.04 },
  ]);
  assert.deepEqual(groups.map((g) => g.key), ["trust", "lust"]);
  assert.deepEqual(groups[0].dots.map((d) => d.sample), ["all", "within"]);
  assert.equal(groups[1].dots[0].sampleIndex, 2);
});

test("co-press rows run near to far for one measure", () => {
  const rows = viz.copressRows([
    { measure: "trust", tercile: "far", share: 8.8, time_null: 3.6 },
    { measure: "lust", tercile: "near", share: 7.7, time_null: 4.3 },
    { measure: "trust", tercile: "near", share: 7.4, time_null: 4.1 },
  ]);
  assert.deepEqual(rows.map((r) => r.tercile), ["near", "far"]);
});

test("the EDA profile is sorted by offset and drops incomplete rows", () => {
  const rows = viz.profileRows([
    { offset: 2, observed: 0.1, null_lo: -0.2, null_hi: 0.2 },
    { offset: -1, observed: 0, null_lo: -0.2, null_hi: 0.2 },
    { offset: 0, observed: null, null_lo: -0.2, null_hi: 0.2 },
  ]);
  assert.deepEqual(rows.map((r) => r.offset), [-1, 2]);
});

test("reasons for one direction, largest share first, named from the copy", () => {
  const rows = viz.reasonRows(
    [
      { reason: "arts", direction: "opens", share: 48 },
      { reason: "people", direction: "opens", share: 93 },
      { reason: "fatigue", direction: "closes", share: 21 },
    ],
    "opens",
  );
  assert.deepEqual(rows.map((r) => [r.name, r.value]), [["Other people", 93], ["Music and the arts", 48]]);
});

test("the clock illustration's lanes end aligned on the programme's clock", () => {
  const lanes = viz.syncLanes();
  const programme = lanes[0].events.map((e) => e.true);
  for (const lane of lanes) {
    for (const e of lane.events) assert.ok(programme.includes(e.true));
  }
  assert.ok(lanes.slice(1).every((l) => l.events.some((e) => e.raw !== e.true)));
});
