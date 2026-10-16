// ric.wiim — pure display/state helpers for the WiiM bar widget + panel.
//
// All functions are pure: they take the parsed daemon snapshot JSON (or
// primitives) and return display strings/glyphs/options, so they can be
// unit-tested outside Qt (tests/test_model.js with node).

// Nerd Font glyphs (verified present in JetBrainsMono Nerd Font).
var ICON = {
  play: "\u{F040A}",      // 󰐊
  pause: "\u{F03E4}",     // 󰏤
  prev: "\u{F04AE}",      // 󰒮
  next: "\u{F04AD}",      // 󰒭
  nowplaying: "\u{F075A}",// 󰝚
  volHigh: "\u{F057E}",   // 󰕾
  volLow: "\u{F057F}",    // 󰕿
  volMute: "\u{F075F}",   // 󰝟
  shuffle: "\u{F0D1D}",   // 󰴝
  repeat: "\u{F0456}",    // 󰑖
  repeatOne: "\u{F0450}", // 󰑐
  loopOff: "\u{F0453}",   // 󰑓 (reuse refresh-ish for "no repeat")
  sleep: "\u{F04AA}",     // 󰒪
  refresh: "\u{F0453}",   // 󰑓
  wifi: "\u{F05A9}",      // 󰖩
  bluetooth: "\u{F00AF}", // 󰂯
  speaker: "\u{F04C3}",   // 󰓃
  music: "\u{F0388}",     // 󰎈
  radio: "\u{F04FB}",     // 󰓻
  optical: "\u{F0CE6}",   // 󰳦
  linein: "\u{F04CC}",    // 󰓌
  usb: "\u{F01C7}",       // 󰇇
  disc: "\u{F04C6}",      // 󰓆
  sliders: "\u{F0497}",   // 󰒗
  folder: "\u{F024B}",    // 󰋋
  timer: "\u{F051F}",     // 󰔟
  airplay: "\u{F021D}",   // 󰈝
  spotify: "\u{F04C7}",   // 󰓇
  tidal: "\u{F0590}",     // 󰖐
  chevronRight: "\u{F0142}", // 󰄂
  chevronLeft: "\u{F0141}",  // 󰄁
  power: "\u{F0425}"      // 󰐥
}

var SOURCE_ICONS = {
  wifi: ICON.wifi, bluetooth: ICON.bluetooth, "line-in": ICON.linein,
  optical: ICON.optical, udisk: ICON.usb, airplay: ICON.airplay,
  dlna: ICON.speaker, spotify: ICON.spotify, tidal: ICON.tidal,
  none: ICON.speaker, mirror: ICON.speaker, slave: ICON.speaker,
  voicemail: ICON.speaker
}

var LOOP_ICONS = {
  sequence: ICON.repeat, single: ICON.repeatOne, shuffle: ICON.shuffle,
  "shuffle-once": ICON.shuffle, none: ICON.loopOff
}

var LOOP_LABEL = {
  sequence: "Loop all", single: "Repeat one", shuffle: "Shuffle",
  "shuffle-once": "Shuffle once", none: "No repeat"
}

var STATUS_LABEL = {
  play: "Playing", pause: "Paused", loading: "Buffering",
  stop: "Stopped", none: "Idle"
}

var SLEEP_OPTIONS = [
  { value: "0", label: "—" },
  { value: "900", label: "15m" },
  { value: "1800", label: "30m" },
  { value: "2700", label: "45m" },
  { value: "3600", label: "1h" },
  { value: "5400", label: "1.5h" }
]

function sourceIcon(id) { return SOURCE_ICONS[id] || ICON.speaker }
function loopIcon(mode) { return LOOP_ICONS[mode] || LOOP_ICONS.none }
function loopLabel(mode) { return LOOP_LABEL[mode] || "No repeat" }

function fmtMs(ms) {
  var s = Math.max(0, Math.floor((Number(ms) || 0) / 1000))
  var h = Math.floor(s / 3600)
  var m = Math.floor((s % 3600) / 60)
  var sec = s % 60
  var mm = h > 0 ? String(m).padStart(2, "0") : String(m)
  var tail = String(sec).padStart(2, "0")
  return h > 0 ? h + ":" + mm + ":" + tail : mm + ":" + tail
}

function fmtClock(sec) {
  var s = Math.max(0, Math.floor(Number(sec) || 0))
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0")
}

// "chip state" for the bar mark: offline|idle|playing|paused
function chipState(snap, daemonReady) {
  if (!snap) return daemonReady ? "idle" : "offline"
  if (!snap.online) return "offline"
  var st = snap.player ? snap.player.status : "none"
  if (st === "play" || st === "loading") return "playing"
  if (st === "pause") return "paused"
  return "idle"
}

function heroTitle(snap) {
  if (!snap || !snap.online) return "Play Room Speakers"
  var t = snap.meta && snap.meta.title ? snap.meta.title : ""
  if (t) return t
  return STATUS_LABEL[snap.player.status] || "Idle"
}

function heroMeta(snap) {
  if (!snap || !snap.online) return "offline"
  var parts = []
  if (snap.meta && snap.meta.artist) parts.push(snap.meta.artist)
  if (snap.meta && snap.meta.album) parts.push(snap.meta.album)
  parts.push(snap.player.sourceLabel || "WiiM")
  return parts.join("  ·  ")
}

function barLabel(snap) {
  if (!snap || !snap.online) return ""
  var t = snap.meta && snap.meta.title ? snap.meta.title : ""
  if (!t) return ""
  var a = snap.meta && snap.meta.artist ? snap.meta.artist : ""
  return a ? t + "  ·  " + a : t
}

function volIcon(vol, mute) {
  if (mute || vol === 0) return ICON.volMute
  return vol < 35 ? ICON.volLow : ICON.volHigh
}

function tooltipText(snap) {
  if (!snap || !snap.online) return "WiiM: offline"
  var p = snap.player
  var bits = [snap.device ? snap.device.name : "WiiM",
              STATUS_LABEL[p.status] || p.status,
              p.sourceLabel, "vol " + p.vol]
  if (snap.meta && snap.meta.title) bits.unshift(snap.meta.title)
  return bits.join(" · ")
}

// ButtonGroup options for presets: number chips; names shown in the row list
function presetOptions(presets) {
  return (presets || []).map(function (p) {
    return { value: String(p.number), label: String(p.number),
             tooltip: p.name + (p.source ? " (" + p.source + ")" : "") }
  })
}

function presetName(presets, number) {
  for (var i = 0; i < (presets || []).length; i++)
    if (presets[i].number === number) return presets[i].name
  return "Preset " + number
}

function sourceOptions(sources) {
  return (sources || []).map(function (s) {
    return { value: s.id, label: s.label }
  })
}

function eqOptions(list) {
  var opts = [{ value: "__off", label: "Off" }]
  for (var i = 0; i < (list || []).length; i++)
    opts.push({ value: list[i], label: list[i] })
  return opts
}

function sleepOptions() { return SLEEP_OPTIONS }

function nextSleep(sec) {
  var order = [0, 900, 1800, 2700, 3600, 5400]
  var i = order.indexOf(Number(sec) || 0)
  return order[(i + 1) % order.length]
}

function sleepLabel(sec) {
  sec = Number(sec) || 0
  if (sec <= 0) return ""
  for (var i = 0; i < SLEEP_OPTIONS.length; i++)
    if (SLEEP_OPTIONS[i].value === String(sec)) return SLEEP_OPTIONS[i].label
  return fmtClock(sec)
}

// Remaining sleep-timer seconds: device reports the configured length,
// not a countdown; we age it from the snapshot timestamp.
function sleepRemaining(sleep, snapTs, nowSec) {
  var sec = sleep && sleep.sec > 0 ? sleep.sec : 0
  if (sec <= 0) return 0
  var elapsed = 0
  if (snapTs) {
    var t = Date.parse(snapTs)
    if (!isNaN(t)) elapsed = Math.max(0, nowSec - t / 1000)
  }
  return Math.max(0, Math.round(sec - elapsed))
}

// Library rows from `wiim library` JSON: dirs first, then tracks.
function libraryRows(lib) {
  var rows = []
  var dirs = (lib && lib.dirs) || []
  var tracks = (lib && lib.tracks) || []
  for (var i = 0; i < dirs.length; i++)
    rows.push({ kind: "dir", name: dirs[i].name, path: dirs[i].path,
                meta: dirs[i].tracks + (dirs[i].tracks === 1 ? " track" : " tracks") })
  for (var j = 0; j < tracks.length; j++)
    rows.push({ kind: "track", name: tracks[j].name, path: tracks[j].path, meta: "" })
  return rows
}

function libraryCrumb(rel) {
  return rel ? rel.split("/").join("  " + ICON.chevronRight + "  ") : "Music"
}

// Clamp helpers
function clampVol(v) {
  v = Math.round(Number(v) || 0)
  return Math.max(0, Math.min(100, v))
}

function clampSeek(sec, totlenMs) {
  var max = (Number(totlenMs) || 0) / 1000
  return Math.max(0, max > 0 ? Math.min(sec, max) : sec)
}

// Parse one daemon stdout line; returns null on junk.
function parseLine(text) {
  try {
    var obj = JSON.parse(String(text))
    return obj && typeof obj === "object" ? obj : null
  } catch (e) {
    return null
  }
}

// ---------------------------------------------------------------------------
// Fixture data: prototype/demo mode (setting "fixture" = true) and tests.
// Mirrors the real daemon snapshot contract exactly.
// ---------------------------------------------------------------------------

function fixtureSnapshot() {
  return {
    online: true,
    ts: new Date().toISOString(),
    player: {
      status: "play", mode: "32", source: "tidal", sourceLabel: "TIDAL Connect",
      loop: "shuffle", curpos: 84000, totlen: 245000, vol: 42, mute: false,
      queueCount: 12, queueIndex: 3, isSlave: false, eqIndex: 4
    },
    meta: {
      title: "Teardrop", artist: "Massive Attack", album: "Mezzanine",
      artUrl: "", sampleRate: "44100", bitDepth: "24"
    },
    device: {
      name: "Play Room Speakers", model: "WiiM Pro Receiver",
      firmware: "Linkplay.4.8.827634", uuid: "FIXTURE", mac: "40:D9:5A:30:39:3C",
      ip: "192.168.183.8", group: "0", presetKeys: 12, internet: true
    },
    presets: [
      { number: 1, name: "Radio Paradise", source: "RadioParadise", picurl: "" },
      { number: 2, name: "BBC Radio Norfolk", source: "Linkplay Radio", picurl: "" },
      { number: 5, name: "My TIDAL Mix", source: "TIDAL", picurl: "" }
    ],
    eq: { stat: "On", list: ["Flat", "Bass Booster", "Classical", "Deep",
                             "Jazz", "Movie", "Pop", "Rock", "Vocal Booster"] },
    output: { hardware: "Coax out" },
    sleep: { sec: 0 },
    sources: [
      { id: "wifi", label: "Wi-Fi", active: false },
      { id: "bluetooth", label: "Bluetooth", active: false },
      { id: "line-in", label: "Line-in", active: false },
      { id: "optical", label: "Optical", active: false }
    ]
  }
}

function fixtureLibrary() {
  return {
    root: "/home/demo/Music", rel: "",
    dirs: [
      { name: "Massive Attack", path: "Massive Attack", tracks: 2 },
      { name: "Radiohead", path: "Radiohead", tracks: 1 }
    ],
    tracks: [
      { name: "Field Recordings 2019", path: "Field Recordings 2019", kind: "track" }
    ]
  }
}

function fixtureLibraryInner() {
  return {
    root: "/home/demo/Music", rel: "Massive Attack",
    dirs: [
      { name: "Mezzanine", path: "Massive Attack/Mezzanine", tracks: 2 },
      { name: "Heligoland", path: "Massive Attack/Heligoland", tracks: 1 }
    ],
    tracks: []
  }
}
