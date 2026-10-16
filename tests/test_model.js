#!/usr/bin/env node
// Unit tests for Model.js (pure helpers). Run: node tests/test_model.js
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Model.js is a plain QML-importable JS module (var/function declarations):
// evaluate it in a sandbox to get its namespace.
const src = fs.readFileSync(path.join(__dirname, "..", "Model.js"), "utf8");
const ctx = vm.createContext({});
vm.runInContext(src + "\nthis.M = {ICON, fmtMs, fmtClock, chipState, heroTitle, heroMeta, barLabel, volIcon, tooltipText, presetOptions, presetName, sourceOptions, eqOptions, sleepOptions, nextSleep, sleepLabel, sleepRemaining, libraryRows, libraryCrumb, clampVol, clampSeek, parseLine, fixtureSnapshot, fixtureLibrary};", ctx);
const M = ctx.M;

let passed = 0;
function t(name, fn) {
  try { fn(); passed++; console.log("ok - " + name); }
  catch (e) { console.error("FAIL - " + name + "\n  " + e.message); process.exitCode = 1; }
}

t("fmtMs", () => {
  assert.equal(M.fmtMs(0), "0:00");
  assert.equal(M.fmtMs(84000), "1:24");
  assert.equal(M.fmtMs(245000), "4:05");
  assert.equal(M.fmtMs(3723000), "1:02:03");
  assert.equal(M.fmtMs(null), "0:00");
});

t("chipState", () => {
  assert.equal(M.chipState(null, false), "offline");
  assert.equal(M.chipState(null, true), "idle");
  const s = M.fixtureSnapshot();
  assert.equal(M.chipState(s, true), "playing");
  s.player.status = "pause";
  assert.equal(M.chipState(s, true), "paused");
  s.player.status = "none";
  assert.equal(M.chipState(s, true), "idle");
  s.online = false;
  assert.equal(M.chipState(s, true), "offline");
});

t("hero", () => {
  const s = M.fixtureSnapshot();
  assert.equal(M.heroTitle(s), "Teardrop");
  assert.ok(M.heroMeta(s).includes("Massive Attack"));
  assert.ok(M.heroMeta(s).includes("TIDAL Connect"));
  s.meta.title = "";
  assert.equal(M.heroTitle(s), "Playing");
});

t("barLabel", () => {
  const s = M.fixtureSnapshot();
  assert.equal(M.barLabel(s), "Teardrop  ·  Massive Attack");
  s.meta.title = "";
  assert.equal(M.barLabel(s), "");
});

t("volIcon", () => {
  assert.equal(M.volIcon(0, false), M.ICON.volMute);
  assert.equal(M.volIcon(50, true), M.ICON.volMute);
  assert.equal(M.volIcon(20, false), M.ICON.volLow);
  assert.equal(M.volIcon(80, false), M.ICON.volHigh);
});

t("presets", () => {
  const s = M.fixtureSnapshot();
  const opts = M.presetOptions(s.presets);
  assert.deepEqual(opts.map(o => o.value), ["1", "2", "5"]);
  assert.ok(opts[0].tooltip.includes("Radio Paradise"));
  assert.equal(M.presetName(s.presets, 5), "My TIDAL Mix");
});

t("sleep cycle + labels", () => {
  assert.equal(M.nextSleep(0), 900);
  assert.equal(M.nextSleep(5400), 0);
  assert.equal(M.sleepLabel(1800), "30m");
  assert.equal(M.sleepLabel(0), "");
});

t("sleepRemaining ages from ts", () => {
  const ts = new Date(Date.now() - 60000).toISOString();
  const left = M.sleepRemaining({ sec: 900 }, ts, Date.now() / 1000);
  assert.ok(left > 820 && left <= 845, "got " + left);
  assert.equal(M.sleepRemaining({ sec: 0 }, ts, 0), 0);
});

t("libraryRows dirs-then-tracks", () => {
  const rows = M.libraryRows(M.fixtureLibrary());
  assert.equal(rows.length, 3);
  assert.equal(rows[0].kind, "dir");
  assert.equal(rows[0].meta, "2 tracks");
  assert.equal(rows[2].kind, "track");
});

t("libraryCrumb", () => {
  assert.equal(M.libraryCrumb(""), "Music");
  assert.ok(M.libraryCrumb("a/b").includes("a"));
});

t("clamps", () => {
  assert.equal(M.clampVol(150), 100);
  assert.equal(M.clampVol(-5), 0);
  assert.equal(M.clampVol("42"), 42);
  assert.equal(M.clampSeek(999, 245000), 245);
  assert.equal(M.clampSeek(50, 0), 50);
});

t("parseLine", () => {
  assert.deepEqual(M.parseLine('{"a":1}'), { a: 1 });
  assert.equal(M.parseLine("junk"), null);
  assert.equal(M.parseLine(""), null);
});

t("fixture snapshot matches daemon contract", () => {
  const s = M.fixtureSnapshot();
  for (const k of ["online", "ts", "player", "meta", "device", "presets", "eq", "output", "sleep", "sources"])
    assert.ok(k in s, "missing " + k);
  for (const k of ["status", "mode", "source", "sourceLabel", "loop", "curpos",
                   "totlen", "vol", "mute", "queueCount", "queueIndex", "isSlave"])
    assert.ok(k in s.player, "missing player." + k);
});

console.log("\n" + passed + " model tests passed");
