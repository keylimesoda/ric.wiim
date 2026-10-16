import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons
import "Model.js" as Model

// ric.wiim — WiiM controller in the Omarchy bar.
//
// Bar chip: an animated equalizer mark (+ now-playing text) for the WiiM
// zone. Click opens the control panel; middle-click toggles playback;
// scrolling over the chip nudges volume.
//
// Panel: keyboard-first, TUI-flavoured (hjkl + Tab sections, direct music
// keys), built on the house Panel/KeyboardPanel/PanelKeyCatcher pattern
// (see ric.daikin). State streams from `bin/wiim daemon` (watch + serve +
// stdin commands); `fixture: true` renders the whole surface from fake
// data for design work and demos.
Panel {
  id: root
  moduleName: "ric.wiim"
  ipcTarget: "ric.wiim"
  manageIpc: false // own IpcHandler: expose transport actions to the shell

  // ---- settings -----------------------------------------------------------
  readonly property string pluginDir: {
    if (manifest && manifest.__sourceDir) return String(manifest.__sourceDir)
    var url = String(Qt.resolvedUrl("."))
    if (url.indexOf("file://") === 0) url = url.slice(7)
    return url.replace(/\/+$/, "")
  }
  readonly property string bin: pluginDir + "/bin/wiim"
  readonly property string deviceIp: String(setting("deviceIp", "192.168.183.8"))
  readonly property string musicDir: String(setting("musicDir", "~/Music"))
  readonly property int volStep: Math.max(1, Math.min(20, Number(setting("volStep", 5)) || 5))
  readonly property int pollMs: Math.max(200, Math.min(2000, Number(setting("pollMs", 500)) || 500))
  readonly property bool barText: setting("barText", true) !== false
  readonly property bool fixtureMode: setting("fixture", false) === true

  // ---- theme ---------------------------------------------------------------
  property var shell: null
  property var manifest: null
  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property string ff: root.bar ? root.bar.fontFamily : Style.font.family
  readonly property bool vertical: root.bar ? root.bar.vertical : false
  readonly property real controlH: Style.spacing.controlHeight
  readonly property int barH: root.bar ? root.bar.barSize : Style.bar.sizeHorizontal

  // ---- live state ----------------------------------------------------------
  property var snap: null
  property var serveInfo: null
  property bool daemonReady: false
  property string lastError: ""
  property int cmdSeq: 0
  property var pendingKind: ({})   // seq -> result routing key
  property int backoffMs: 1000

  // progress smoothing: device curpos is resynced by state/tick events;
  // between events we advance locally so the slider glides.
  property int curposLocal: 0
  property int curposTotal: 0
  property int sleepLeft: 0

  // library navigation
  property string libPath: ""
  property var libRows: []
  property bool libLoaded: false

  // ---- cursor model ---------------------------------------------------------
  // Sections are the j/k (or Tab) stops; each keeps its own index.
  readonly property var sectionOrder: ["transport", "progress", "volume",
    "presets", "source", "eq", "sleep", "library", "device"]
  property string focusSection: "transport"
  property var secIdx: ({})
  property bool cursorActive: false
  property bool viaEnter: false

  function idx(sec) { return secIdx[sec] !== undefined ? secIdx[sec] : 0 }
  function setIdx(sec, v) { var m = {}; for (var k in secIdx) m[k] = secIdx[k];
    m[sec] = v; secIdx = m }

  function isListSection(sec) { return sec === "presets" || sec === "library" }
  function listCount(sec) {
    if (sec === "presets") return snap && snap.presets ? snap.presets.length : 0
    if (sec === "library") return libRows.length
    return 0
  }

  function moveSection(dy) {
    var order = sectionOrder
    var i = order.indexOf(focusSection)
    var next = order[Math.max(0, Math.min(order.length - 1, i + dy))]
    if (next === focusSection) return
    focusSection = next
    // land list cursors on the first row, chips on their current value
    if (isListSection(next) && idx(next) >= listCount(next)) setIdx(next, 0)
  }

  function moveCursor(dx, dy) {
    cursorActive = true
    if (dy !== 0) {
      if (isListSection(focusSection) && listCount(focusSection) > 0) {
        var n = listCount(focusSection)
        setIdx(focusSection, Math.max(0, Math.min(n - 1, idx(focusSection) + dy)))
      } else {
        moveSection(dy)
      }
      return
    }
    switch (focusSection) {
      case "progress": seekRel(dx * 10); break
      case "volume": volStepBy(dx * volStep); break
      case "transport": setIdx("transport", Math.max(0, Math.min(3, idx("transport") + dx))); break
      case "source": {
        var srcs = snap && snap.sources ? snap.sources : []
        if (srcs.length) setIdx("source", (idx("source") + dx + srcs.length) % srcs.length)
        break
      }
      case "eq": eqCycle(dx); break
      case "sleep": {
        var so = Model.sleepOptions()
        setIdx("sleep", (idx("sleep") + dx + so.length) % so.length)
        break
      }
      case "presets": case "library": {
        var c = listCount(focusSection)
        if (c) setIdx(focusSection, Math.max(0, Math.min(c - 1, idx(focusSection) + dx)))
        break
      }
    }
  }

  function activateSection() {
    cursorActive = true
    switch (focusSection) {
      case "transport": {
        var i = idx("transport")
        if (i === 0) prevTrack(); else if (i === 1) togglePlay()
        else if (i === 2) nextTrack(); else loopCycle()
        break
      }
      case "volume": muteToggle(); break
      case "presets": {
        var ps = snap && snap.presets ? snap.presets : []
        if (ps.length) presetPlay(ps[idx("presets")].number)
        break
      }
      case "source": {
        var srcs = snap && snap.sources ? snap.sources : []
        if (srcs.length) sourceSet(srcs[idx("source")].id)
        break
      }
      case "eq": eqDropdown.toggle(); break
      case "sleep": {
        var so = Model.sleepOptions()
        sleepSet(Number(so[idx("sleep")].value))
        break
      }
      case "library": libraryActivate(idx("library")); break
      case "device": refresh(); break
    }
  }

  // ---- derived state --------------------------------------------------------
  readonly property bool online: snap !== null && snap.online === true
  readonly property string status: online ? snap.player.status : "none"
  readonly property bool playing: status === "play" || status === "loading"
  readonly property bool paused: status === "pause"
  readonly property bool hasTrack: online && snap.meta && snap.meta.title !== ""
  readonly property int vol: online ? snap.player.vol : 0
  readonly property bool muted: online && snap.player.mute
  readonly property string chipState: Model.chipState(snap, daemonReady || fixtureMode)

  // ---- actions --------------------------------------------------------------
  function sendCmd(cmd, args) {
    if (fixtureMode) { fixtureApply(cmd, args || {}); return }
    if (!daemonProc.running) { lastError = "wiim daemon not running"; return }
    cmdSeq += 1
    var req = { id: cmdSeq, cmd: cmd }
    if (args) req.args = args
    daemonProc.write(JSON.stringify(req) + "\n")
  }

  function sendCmdTracked(kind, cmd, args) {
    if (fixtureMode) { fixtureApply(cmd, args || {}); return }
    if (!daemonProc.running) return
    cmdSeq += 1
    var m = {}; for (var k in pendingKind) m[k] = pendingKind[k]
    m[cmdSeq] = kind; pendingKind = m
    var req = { id: cmdSeq, cmd: cmd }
    if (args) req.args = args
    daemonProc.write(JSON.stringify(req) + "\n")
  }

  function patchSnapPlayer(part) {
    if (!snap) return
    var copy = JSON.parse(JSON.stringify(snap))
    for (var k in part) copy.player[k] = part[k]
    snap = copy
  }

  function refresh() { sendCmd("status", { full: true }) }

  function togglePlay() {
    if (fixtureMode) { fixtureApply("toggle", {}); return }
    if (playing) patchSnapPlayer({ status: "pause" })
    else if (paused) patchSnapPlayer({ status: "play" })
    sendCmd("toggle")
  }
  function nextTrack() { sendCmd("next") }
  function prevTrack() { sendCmd("prev") }
  function stopPlay() { patchSnapPlayer({ status: "stop" }); sendCmd("stop") }

  function volSetTo(v) {
    v = Model.clampVol(v)
    patchSnapPlayer({ vol: v, mute: false })
    sendCmd("vol", { value: v })
  }
  function volStepBy(d) { volSetTo(vol + d) }
  function muteToggle() {
    var on = !muted
    patchSnapPlayer({ mute: on })
    sendCmd("mute", { on: on })
  }

  function seekRel(dsec) {
    if (!online) return
    var cur = curposLocal / 1000 + dsec
    cur = Model.clampSeek(cur, curposTotal)
    curposLocal = Math.round(cur * 1000)
    sendCmd("seek", { sec: Math.round(cur) })
  }

  function loopCycle() {
    var order = ["sequence", "single", "shuffle", "none"]
    var cur = online ? snap.player.loop : "none"
    var i = order.indexOf(cur === "shuffle-once" ? "shuffle" : cur)
    sendCmd("loop", { mode: order[(i + 1) % order.length] })
  }

  function presetPlay(n) { sendCmd("preset", { number: n }) }

  function sourceSet(id) { sendCmd("source", { id: id }) }
  function sourceCycle() {
    var srcs = snap && snap.sources ? snap.sources : []
    if (!srcs.length) return
    var cur = online ? snap.player.source : ""
    var i = 0
    for (var j = 0; j < srcs.length; j++) if (srcs[j].id === cur) i = j
    sourceSet(srcs[(i + 1) % srcs.length].id)
  }

  function eqCycle(dir) {
    var list = online && snap.eq ? snap.eq.list : []
    if (!list.length) return
    var cur = eqCurrent()
    var i = list.indexOf(cur)
    var next = list[(i + dir + list.length) % list.length]
    sendCmd("eq", { name: next })
  }
  function eqCurrent() {
    if (!online || snap.eq.stat !== "On") return "__off"
    // the firmware reports the loaded EQ only via getPlayerStatus.eq index
    var li = snap.eq.list || []
    var pi = Number(snap.player.eqIndex)
    if (!isNaN(pi) && pi >= 0 && pi < li.length) return li[pi]
    return eqShown
  }
  property string eqShown: "__off" // display fallback (device has no readback)

  function eqSet(name) {
    if (name === "__off") { eqShown = "__off"; sendCmd("eqOff") }
    else { eqShown = name; sendCmd("eq", { name: name }) }
  }

  function sleepSet(sec) {
    if (sec > 0) sendCmd("sleep", { sec: sec })
    else sendCmd("sleep", { sec: 0 })
  }
  function sleepCycle() {
    var cur = online ? snap.sleep.sec : 0
    sleepSet(Model.nextSleep(cur))
  }

  // ---- library ---------------------------------------------------------------
  function refreshLibrary() { sendCmdTracked("library", "library", { path: libPath }) }
  function libraryOpen(path) { libPath = path; refreshLibrary() }
  function libraryUp() {
    if (!libPath) return
    var i = libPath.lastIndexOf("/")
    libraryOpen(i < 0 ? "" : libPath.substring(0, i))
  }
  function libraryActivate(i) {
    if (i < 0 || i >= libRows.length) return
    var row = libRows[i]
    if (row.kind === "dir") libraryOpen(row.path)
    else sendCmd("playFile", { path: row.path })
  }
  function playPath(p) { sendCmd("playFile", { path: p }) }
  function playAlbum(p) { sendCmd("playAlbum", { path: p }) }

  // ---- daemon -----------------------------------------------------------------
  function handleLine(text) {
    var obj = Model.parseLine(text)
    if (!obj) return
    if (obj.event === "hello") {
      daemonReady = true
      serveInfo = obj.serve || null
      backoffMs = 1000
      lastError = ""
      refreshLibrary()
    } else if (obj.event === "state") {
      applySnapshot(obj.snapshot)
    } else if (obj.event === "tick") {
      curposLocal = obj.curpos || 0
      curposTotal = obj.totlen || 0
    } else if (obj.event === "offline") {
      lastError = obj.error || "offline"
    } else if (obj.id !== undefined) {
      var kind = pendingKind[obj.id]
      if (kind !== undefined) {
        var m = {}; for (var k in pendingKind) if (k !== String(obj.id) && k !== obj.id) m[k] = pendingKind[k]
        pendingKind = m
        if (obj.ok && kind === "library" && obj.result) {
          libRows = Model.libraryRows(obj.result)
          libLoaded = true
          if (idx("library") >= libRows.length) setIdx("library", 0)
        }
      }
      if (obj.ok === false && obj.error) lastError = String(obj.error)
    }
  }

  function applySnapshot(s) {
    if (!s) return
    snap = s
    lastError = ""
    curposLocal = s.player.curpos || 0
    curposTotal = s.player.totlen || 0
    if (s.eq && s.eq.stat === "Off") eqShown = "__off"
  }

  Process {
    id: daemonProc
    command: [root.bin, "daemon", "--ip", root.deviceIp,
              "--dir", root.musicDir,
              "--interval", String(root.pollMs / 1000)]
    running: !root.fixtureMode
    stdinEnabled: true

    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function (data) { root.handleLine(data) }
    }
    stderr: StdioCollector { waitForEnd: true }

    onExited: {
      if (root.fixtureMode) return
      root.daemonReady = false
      restartTimer.restart()
    }
  }

  Timer {
    id: restartTimer
    interval: root.backoffMs
    onTriggered: {
      root.backoffMs = Math.min(30000, root.backoffMs * 2)
      if (!root.fixtureMode) daemonProc.running = true
    }
  }

  // settings changes restart the daemon cleanly
  onDeviceIpChanged: restartDaemon()
  onMusicDirChanged: restartDaemon()
  onPollMsChanged: restartDaemon()
  function restartDaemon() {
    if (root.fixtureMode) return
    daemonProc.running = false
    Qt.callLater(function () { daemonProc.running = true })
  }

  // progress + sleep countdown smoothing
  Timer {
    interval: 250
    repeat: true
    running: root.online && (root.playing || (root.online && root.snap.sleep.sec > 0))
    onTriggered: {
      if (root.playing) {
        root.curposLocal += 250
        if (root.curposTotal > 0 && root.curposLocal > root.curposTotal)
          root.curposLocal = root.curposTotal
      }
      root.sleepLeft = Model.sleepRemaining(root.snap.sleep, root.snap.ts,
                                           Date.now() / 1000)
    }
  }

  // ---- fixture mode ---------------------------------------------------------
  function initFixture() {
    daemonReady = true
    snap = Model.fixtureSnapshot()
    curposLocal = snap.player.curpos
    curposTotal = snap.player.totlen
    libRows = Model.libraryRows(Model.fixtureLibrary())
    libLoaded = true
    serveInfo = { port: 0, urlBase: "http://fixture" }
    console.log("WIIM-INIT fixture mode armed")
  }

  // The host injects `settings` after Component.onCompleted, so fixture mode
  // must also be armed from the settings-changed edge, not only on completion.
  onFixtureModeChanged: {
    if (fixtureMode) {
      initFixture()
    } else {
      snap = null
      daemonReady = false
      libRows = []
      libLoaded = false
      restartDaemon()
    }
  }

  function fixtureApply(cmd, a) {
    if (!snap) snap = Model.fixtureSnapshot()
    var copy = JSON.parse(JSON.stringify(snap))
    switch (cmd) {
      case "toggle": copy.player.status = copy.player.status === "play" ? "pause" : "play"; break
      case "play": copy.player.status = "play"; break
      case "pause": copy.player.status = "pause"; break
      case "stop": copy.player.status = "stop"; break
      case "next": copy.player.queueIndex = Math.min(copy.player.queueCount, copy.player.queueIndex + 1); break
      case "prev": copy.player.queueIndex = Math.max(0, copy.player.queueIndex - 1); break
      case "vol": copy.player.vol = Model.clampVol(a.value); break
      case "mute": copy.player.mute = !!a.on; break
      case "seek": copy.player.curpos = Math.round(a.sec * 1000); break
      case "loop": copy.player.loop = a.mode; break
      case "source":
        copy.player.source = a.id
        copy.player.sourceLabel = ({ wifi: "Wi-Fi", bluetooth: "Bluetooth",
          "line-in": "Line-in", optical: "Optical", udisk: "USB" })[a.id] || a.id
        copy.player.status = "play"
        for (var i = 0; i < copy.sources.length; i++)
          copy.sources[i].active = copy.sources[i].id === a.id
        break
      case "preset": {
        var p = null
        for (var j = 0; j < copy.presets.length; j++)
          if (copy.presets[j].number === a.number) p = copy.presets[j]
        if (p) {
          copy.meta.title = p.name; copy.meta.artist = p.source
          copy.meta.album = ""; copy.player.status = "play"
          copy.player.source = "wifi"; copy.player.sourceLabel = "WiiM"
          copy.player.totlen = 0
        }
        break
      }
      case "eq": copy.eq.stat = "On"; break
      case "eqOff": copy.eq.stat = "Off"; break
      case "sleep": copy.sleep.sec = a.sec > 0 ? a.sec : 0; break
      case "playFile": copy.meta.title = String(a.path).split("/").pop();
                       copy.meta.artist = "Local library"
                       copy.player.status = "play"; break
      case "playAlbum": copy.meta.title = "Album playback"
                        copy.meta.artist = "Local library"
                        copy.player.status = "play"
                        copy.player.queueCount = 10; break
      case "library": {
        var rel = String(a.path || "")
        var lib = rel === "" ? Model.fixtureLibrary()
                : rel.indexOf("Massive Attack") === 0 ? Model.fixtureLibraryInner()
                : { dirs: [], tracks: [] }
        libRows = Model.libraryRows(lib)
        libLoaded = true
        if (idx("library") >= libRows.length) setIdx("library", 0)
        break
      }
    }
    applySnapshot(copy)
    if (cmd === "eq") eqShown = a.name
    if (cmd === "eqOff") eqShown = "__off"
  }

  Component.onCompleted: {
    console.log("WIIM-INIT bin=" + root.bin + " ip=" + root.deviceIp +
      " fixture=" + root.fixtureMode + " kc=" + (keyCatcher !== undefined))
    if (root.fixtureMode) initFixture()
  }

  onOpenedChanged: {
    if (root.opened) {
      root.refresh()
      root.refreshLibrary()
      root.cursorActive = false
      root.focusSection = "transport"
    }
  }

  // ---- IPC -------------------------------------------------------------------
  IpcHandler {
    target: "ric.wiim"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }

    function playPause(): string { root.togglePlay(); return "ok" }
    function next(): string { root.nextTrack(); return "ok" }
    function previous(): string { root.prevTrack(); return "ok" }
    function stop(): string { root.stopPlay(); return "ok" }
    function volSet(v: real): string { root.volSetTo(v); return "ok" }
    function volStep(d: real): string { root.volStepBy(d); return "ok" }
    function mute(state: string): string {
      if (state === "on") { if (!root.muted) root.muteToggle() }
      else if (state === "off") { if (root.muted) root.muteToggle() }
      else root.muteToggle()
      return "ok"
    }
    function preset(n: int): string { root.presetPlay(n); return "ok" }
    function source(id: string): string { root.sourceSet(id); return "ok" }
    function eq(name: string): string { root.eqSet(name); return "ok" }
    function seek(sec: real): string {
      if (root.online) { root.curposLocal = Math.round(sec * 1000); root.sendCmd("seek", { sec: Math.round(sec) }) }
      return "ok"
    }
    function loop(mode: string): string { root.sendCmd("loop", { mode: mode }); return "ok" }
    function sleep(sec: int): string { root.sleepSet(sec); return "ok" }
    function playPath(p: string): string { root.playPath(p); return "ok" }
    function playAlbum(p: string): string { root.playAlbum(p); return "ok" }
    function refresh(): void { root.refresh() }

    function status(): string {
      if (!root.snap) return JSON.stringify({ online: false })
      return JSON.stringify({
        online: root.snap.online, status: root.snap.player.status,
        source: root.snap.player.source, vol: root.snap.player.vol,
        mute: root.snap.player.mute, title: root.snap.meta.title,
        artist: root.snap.meta.artist, name: root.snap.device ? root.snap.device.name : ""
      })
    }

    // debug surface (mirrors ric.daikin conventions)
    function dumpState(): string {
      return JSON.stringify({
        online: root.online, status: root.status, daemonRunning: daemonProc.running,
        daemonReady: root.daemonReady, lastError: root.lastError,
        fixtureMode: root.fixtureMode, settings: root.settings,
        serve: root.serveInfo, libPath: root.libPath, libRows: root.libRows.length,
        focusSection: root.focusSection
      })
    }
  }

  // ---- bar chip ----------------------------------------------------------------
  implicitWidth: chip.implicitWidth
  implicitHeight: chip.implicitHeight

  Item {
    id: chip
    implicitWidth: barTextRow.implicitWidth + Style.space(17)
    implicitHeight: root.barH

    Row {
      id: barTextRow
      anchors.centerIn: parent
      spacing: Style.space(6)

      EqMark {
        anchors.verticalCenter: parent.verticalCenter
        size: Style.bar.iconCanvas
        ink: root.chipInk
        animating: root.chipState === "playing"
      }

      // Now-playing text: glides when it does not fit (brumm-style), else
      // elides. Hidden when there is no track or barText is off.
      Item {
        id: clip
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(Style.space(170), barLabel.implicitWidth)
        height: barLabel.height
        visible: root.barText && !root.vertical && barLabel.text !== ""
        clip: true

        Text {
          id: barLabel
          anchors.verticalCenter: parent.verticalCenter
          width: implicitWidth
          textFormat: Text.PlainText
          text: Model.barLabel(root.snap)
          color: root.fg
          font.family: root.ff
          font.pixelSize: Style.font.body

          SequentialAnimation on x {
            running: root.chipState === "playing" &&
                     barLabel.implicitWidth > clip.width && !root.opened
            loops: Animation.Infinite
            onRunningChanged: if (!running) barLabel.x = 0
            PauseAnimation { duration: 2500 }
            NumberAnimation {
              from: 0
              to: clip.width - barLabel.implicitWidth
              duration: Math.max(1, barLabel.implicitWidth - clip.width) * 55
            }
          }
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton
      cursorShape: Qt.PointingHandCursor
      onClicked: function (mouse) {
        if (mouse.button === Qt.MiddleButton) root.togglePlay()
        else root.toggle()
      }
      onWheel: function (wheel) {
        root.volStepBy(wheel.angleDelta.y > 0 ? root.volStep : -root.volStep)
      }
      onEntered: if (root.bar) root.bar.showTooltip(chip, Model.tooltipText(root.snap))
      onExited: if (root.bar) root.bar.hideTooltip(chip)
    }
  }

  readonly property color chipInk:
    root.chipState === "offline" ? Qt.alpha(root.fg, 0.30)
    : root.chipState === "idle" ? Qt.alpha(root.fg, 0.50)
    : root.chipState === "paused" ? Qt.alpha(root.fg, 0.70)
    : root.fg

  // ---- panel ---------------------------------------------------------------------
  KeyboardPanel {
    id: panel
    anchorItem: chip
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(900))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onMoveRequested: function (dx, dy) { root.moveCursor(dx, dy) }
      onReturnRequested: root.viaEnter = true
      onActivateRequested: {
        if (root.viaEnter) { root.viaEnter = false; root.activateSection() }
        else root.togglePlay()
      }
      onCloseRequested: root.close()
      onTabRequested: function (direction) {
        if (Math.abs(direction) === 1) {
          cursorActive = true
          moveSection(direction)
        }
      }
      onDeleteRequested: { if (root.focusSection === "library") root.libraryUp() }
      onTextKey: function (t) {
        if (t === ",") root.prevTrack()
        else if (t === ".") root.nextTrack()
        else if (t === "+" || t === "=") root.volStepBy(root.volStep)
        else if (t === "-" || t === "_") root.volStepBy(-root.volStep)
        else if (t === "m") root.muteToggle()
        else if (t === "s") root.sourceCycle()
        else if (t === "e") root.eqCycle(1)
        else if (t === "t") root.sleepCycle()
        else if (t === "r") root.refresh()
        else if (t === "u") root.libraryUp()
        else if (t >= "1" && t <= "9") root.presetPlay(Number(t))
        else if (t === "0") root.presetPlay(10)
      }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: panelColumn.implicitHeight > height
          ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(13)

          // ---------- Hero: art · title · artist/source ----------
          PanelHero {
            iconComponent: artTile
            title: Model.heroTitle(root.snap)
            meta: Model.heroMeta(root.snap)
            detail: root.online && root.snap.player.isSlave ? "GROUP" : ""
            foreground: root.fg
            fontFamily: root.ff
          }

          // ---------- Transport ----------
          Row {
            width: parent.width
            spacing: Style.space(8)

            // prev / play / next cluster
            Row {
              spacing: Style.space(6)
              TransportButton { glyph: Model.ICON.prev; label: "Previous"
                cursorOn: root.cursorActive && root.focusSection === "transport" && root.idx("transport") === 0
                onClicked: root.prevTrack()
                onHovered: function (h) { if (h) root.setCursor("transport", 0) } }
              TransportButton { glyph: root.playing ? Model.ICON.pause : Model.ICON.play
                label: root.playing ? "Pause" : "Play"
                wide: true
                cursorOn: root.cursorActive && root.focusSection === "transport" && root.idx("transport") === 1
                onClicked: root.togglePlay()
                onHovered: function (h) { if (h) root.setCursor("transport", 1) } }
              TransportButton { glyph: Model.ICON.next; label: "Next"
                cursorOn: root.cursorActive && root.focusSection === "transport" && root.idx("transport") === 2
                onClicked: root.nextTrack()
                onHovered: function (h) { if (h) root.setCursor("transport", 2) } }
            }

            Item { width: Math.max(0, parent.width - transportClusterWidth()
                    - loopChip.implicitWidth - parent.spacing * 2); height: 1 }

            // loop mode chip
            Button {
              id: loopChip
              height: root.controlH
              iconText: Model.loopIcon(root.online ? root.snap.player.loop : "none")
              text: Model.loopLabel(root.online ? root.snap.player.loop : "none")
              bordered: true
              foreground: root.fg
              fontFamily: root.ff
              hasCursor: root.cursorActive && root.focusSection === "transport" && root.idx("transport") === 3
              onClicked: root.loopCycle()
              onHovered: function (h) { if (h) root.setCursor("transport", 3) }
            }
          }

          // ---------- Progress ----------
          Row {
            width: parent.width
            spacing: Style.space(8)
            opacity: root.online && root.curposTotal > 0 ? 1.0 : 0.45

            Text {
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.curposTotal > 0 ? Model.fmtMs(root.curposLocal) : "—"
              color: root.fg
              font.family: root.ff
              font.pixelSize: Style.font.bodySmall
            }

            Rectangle {
              id: progressFrame
              width: Math.max(40, parent.width - parent.children[0].implicitWidth
                              - parent.children[2].implicitWidth - parent.spacing * 2)
              height: root.controlH
              color: "transparent"
              border.width: root.cursorActive && root.focusSection === "progress" ? 1 : 0
              border.color: Qt.alpha(root.fg, 0.75)

              PanelSlider {
                id: progressSlider
                anchors.fill: parent
                bar: root.bar
                minimum: 0
                maximum: root.curposTotal > 0 ? root.curposTotal / 1000 : 1
                step: 5
                value: root.curposTotal > 0
                  ? Math.min(root.curposLocal / 1000, root.curposTotal / 1000) : 0
                enabled: root.online && root.curposTotal > 0
                onReleased: function (v) {
                  if (root.online && root.curposTotal > 0) {
                    root.curposLocal = Math.round(v * 1000)
                    root.sendCmd("seek", { sec: Math.round(v) })
                  }
                }
              }
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.curposTotal > 0 ? Model.fmtMs(root.curposTotal)
                  : (root.online ? "LIVE" : "—")
              color: root.fg
              opacity: root.curposTotal > 0 ? 1.0 : 0.7
              font.family: root.ff
              font.pixelSize: Style.font.bodySmall
            }
          }

          // ---------- Volume ----------
          Row {
            width: parent.width
            spacing: Style.space(8)

            Button {
              id: muteBtn
              width: root.controlH + Style.space(10)
              height: root.controlH
              iconText: Model.volIcon(root.vol, root.muted)
              bordered: true
              selected: root.muted
              foreground: root.fg
              fontFamily: root.ff
              hasCursor: root.cursorActive && root.focusSection === "volume"
              onClicked: root.muteToggle()
              onHovered: function (h) { if (h) root.setCursor("volume", 0) }
            }

            Rectangle {
              id: volFrame
              width: Math.max(40, parent.width - muteBtn.width - volReadout.implicitWidth
                              - parent.spacing * 2)
              height: root.controlH
              color: "transparent"
              border.width: root.cursorActive && root.focusSection === "volume" ? 1 : 0
              border.color: Qt.alpha(root.fg, 0.75)

              PanelSlider {
                id: volSlider
                anchors.fill: parent
                bar: root.bar
                minimum: 0
                maximum: 100
                step: root.volStep
                integer: true
                value: root.vol
                enabled: root.online
                onReleased: function (v) { root.volSetTo(v) }
              }
            }

            Text {
              id: volReadout
              anchors.verticalCenter: parent.verticalCenter
              textFormat: Text.PlainText
              text: root.online ? String(root.vol) : "—"
              color: root.fg
              opacity: root.muted ? 0.45 : 1.0
              font.family: root.ff
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }
          }

          PanelSeparator { foreground: root.fg }

          // ---------- Presets ----------
          Column {
            width: parent.width
            spacing: Style.space(4)

            PanelSectionHeader {
              text: "PRESETS"
              foreground: root.fg
              fontFamily: root.ff
            }

            Repeater {
              model: root.snap && root.snap.presets ? root.snap.presets : []
              delegate: ListRow {
                required property var modelData
                required property int index
                glyph: String(modelData.number)
                glyphWide: false
                name: modelData.name
                meta: modelData.source
                cursorOn: root.cursorActive && root.focusSection === "presets" && root.idx("presets") === index
                onHovered: function (h) { if (h) root.setCursor("presets", index) }
                onClicked: root.presetPlay(modelData.number)
              }
            }

            Text {
              visible: !(root.snap && root.snap.presets && root.snap.presets.length)
              textFormat: Text.PlainText
              text: "No presets — add them in the WiiM Home app"
              color: root.fg
              opacity: 0.5
              font.family: root.ff
              font.pixelSize: Style.font.caption
            }
          }

          // ---------- Source ----------
          Column {
            width: parent.width
            spacing: Style.space(4)

            PanelSectionHeader {
              text: "SOURCE"
              foreground: root.fg
              fontFamily: root.ff
            }

            ButtonGroup {
              width: parent.width
              options: Model.sourceOptions(root.snap ? root.snap.sources : [])
              value: root.online ? root.snap.player.source : ""
              foreground: root.fg
              fontFamily: root.ff
              cursorIndex: root.cursorActive && root.focusSection === "source"
                ? root.idx("source") : -1
              onChanged: function (v) { root.sourceSet(v) }
              onHovered: function (i, h) { if (h) root.setCursor("source", i) }
            }
          }

          // ---------- EQ ----------
          Column {
            width: parent.width
            spacing: Style.space(4)

            PanelSectionHeader {
              text: "EQUALIZER"
              foreground: root.fg
              fontFamily: root.ff
            }

            Row {
              width: parent.width
              spacing: Style.space(8)

              ToggleSwitch {
                anchors.verticalCenter: parent.verticalCenter
                checked: root.online && root.snap.eq.stat === "On"
                interactive: root.online
                foreground: root.fg
                onToggled: { checked ? root.eqSet(root.eqShown === "__off" ? "Flat" : root.eqShown)
                                     : root.eqSet("__off") }
              }

              Dropdown {
                id: eqDropdown
                width: Math.max(120, parent.width - parent.children[0].implicitWidth
                                - parent.spacing * 2 - eqHint.implicitWidth)
                label: ""
                showLabel: false
                value: root.eqCurrent()
                options: Model.eqOptions(root.snap ? root.snap.eq.list : [])
                foreground: root.fg
                background: Color.popups.background
                fontFamily: root.ff
                hasCursor: root.cursorActive && root.focusSection === "eq"
                onChanged: function (v) { root.eqSet(v) }
                onHovered: function (h) { if (h) root.setCursor("eq", 0) }
              }

              Text {
                id: eqHint
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: "h/l cycle"
                color: root.fg
                opacity: 0.45
                font.family: root.ff
                font.pixelSize: Style.font.caption
              }
            }
          }

          // ---------- Sleep ----------
          Column {
            width: parent.width
            spacing: Style.space(4)

            Row {
              width: parent.width
              spacing: Style.space(8)

              PanelSectionHeader {
                text: "SLEEP"
                foreground: root.fg
                fontFamily: root.ff
                anchors.verticalCenter: parent.verticalCenter
              }

              Item {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - parent.children[0].implicitWidth
                        - sleepCountdown.implicitWidth - parent.spacing * 2)
                height: 1
              }

              Text {
                id: sleepCountdown
                anchors.verticalCenter: parent.verticalCenter
                visible: root.sleepLeft > 0
                textFormat: Text.PlainText
                text: Model.ICON.timer + " " + Model.fmtClock(root.sleepLeft)
                color: root.fg
                opacity: 0.75
                font.family: root.ff
                font.pixelSize: Style.font.bodySmall
              }
            }

            ButtonGroup {
              width: parent.width
              options: Model.sleepOptions()
              value: root.online ? String(root.snap.sleep.sec) : "0"
              foreground: root.fg
              fontFamily: root.ff
              cursorIndex: root.cursorActive && root.focusSection === "sleep"
                ? root.idx("sleep") : -1
              onChanged: function (v) { root.sleepSet(Number(v)) }
              onHovered: function (i, h) { if (h) root.setCursor("sleep", i) }
            }
          }

          PanelSeparator { foreground: root.fg }

          // ---------- Library ----------
          Column {
            width: parent.width
            spacing: Style.space(4)

            Row {
              width: parent.width
              spacing: Style.space(8)

              PanelSectionHeader {
                text: "LIBRARY"
                foreground: root.fg
                fontFamily: root.ff
                anchors.verticalCenter: parent.verticalCenter
              }

              Item {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - parent.children[0].implicitWidth
                        - crumbText.implicitWidth - parent.spacing * 2)
                height: 1
              }

              Text {
                id: crumbText
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: Model.libraryCrumb(root.libPath)
                color: root.fg
                opacity: 0.55
                font.family: root.ff
                font.pixelSize: Style.font.caption
                elide: Text.ElideLeft
                width: Math.min(implicitWidth, Style.space(200))
              }
            }

            Repeater {
              model: root.libRows
              delegate: ListRow {
                required property var modelData
                required property int index
                glyph: modelData.kind === "dir" ? Model.ICON.folder : Model.ICON.music
                name: modelData.name
                meta: modelData.meta
                cursorOn: root.cursorActive && root.focusSection === "library" && root.idx("library") === index
                onHovered: function (h) { if (h) root.setCursor("library", index) }
                onClicked: root.libraryActivate(index)
              }
            }

            Text {
              visible: root.libLoaded && root.libRows.length === 0
              textFormat: Text.PlainText
              text: "Empty — drop files into " + root.musicDir + " (or set musicDir in settings)"
              color: root.fg
              opacity: 0.5
              font.family: root.ff
              font.pixelSize: Style.font.caption
              elide: Text.ElideMiddle
              width: parent.width
            }

            Text {
              visible: !root.libLoaded
              textFormat: Text.PlainText
              text: "…"
              color: root.fg
              opacity: 0.4
              font.family: root.ff
              font.pixelSize: Style.font.caption
            }
          }

          // ---------- Device ----------
          Column {
            width: parent.width
            spacing: Style.spacing.labelGap

            PanelSectionHeader {
              text: "DEVICE"
              foreground: root.fg
              fontFamily: root.ff
            }

            InfoPair {
              label: "Speaker"
              value: root.online && root.snap.device ? root.snap.device.name : "—"
            }
            InfoPair {
              label: "Model"
              value: root.online && root.snap.device
                ? root.snap.device.model + (root.snap.output.hardware ? " · " + root.snap.output.hardware : "")
                : "—"
            }
            InfoPair {
              label: "Address"
              value: root.deviceIp + (root.online ? "" : "  (offline)")
            }
            InfoPair {
              label: "Queue"
              value: root.online && root.snap.player.queueCount > 0
                ? (root.snap.player.queueIndex + 1) + " / " + root.snap.player.queueCount
                : "—"
            }

            Text {
              width: parent.width
              visible: root.lastError !== ""
              text: root.lastError
              color: Color.urgent
              opacity: 0.9
              font.family: root.ff
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }

            Button {
              width: parent.width
              text: root.online ? "Refresh now" : "Retry connection"
              bordered: true
              foreground: root.fg
              fontFamily: root.ff
              hasCursor: root.cursorActive && root.focusSection === "device"
              onClicked: root.refresh()
              onHovered: function (h) { if (h) root.setCursor("device", 0) }
            }
          }

          PanelSeparator { foreground: root.fg }

          // ---------- key hints (TUI-style) ----------
          Column {
            width: parent.width
            spacing: Style.space(1)

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: "␣ play   , . skip   + − vol   m mute   1-9 preset"
              color: root.fg
              opacity: 0.45
              font.family: root.ff
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: root.focusSection === "library"
                ? "j k browse   ⏎ open/play   u up   ⇥ section   esc close"
                : "s source   e eq   t sleep   r refresh   ⇥ section   esc close"
              color: root.fg
              opacity: 0.45
              font.family: root.ff
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }
        }
      }
    }
  }

  function setCursor(sec, i) {
    cursorActive = true
    focusSection = sec
    setIdx(sec, i)
  }

  function transportClusterWidth() {
    // three transport buttons + two gaps between them
    return Style.space(44) * 2 + Style.space(64) + Style.space(12)
  }

  // ---- inline components -----------------------------------------------------

  // Album art tile: remote art when the stream provides it, else a disc mark.
  Component {
    id: artTile
    BorderSurface {
      width: Style.space(56)
      height: Style.space(56)
      radius: Style.spacing.labelGap
      color: Style.normalFillFor(root.fg, Color.accent)
      borderSpec: Border.controlSpec("normal", root.fg, Color.accent)

      Image {
        anchors.fill: parent
        anchors.margins: Style.space(2)
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        source: root.online && root.snap.meta ? root.snap.meta.artUrl : ""
        visible: source !== "" && root.online
      }

      Text {
        anchors.centerIn: parent
        visible: !(root.online && root.snap.meta && root.snap.meta.artUrl)
        text: root.hasTrack ? Model.ICON.nowplaying : Model.ICON.speaker
        color: root.fg
        opacity: root.hasTrack ? 0.9 : 0.5
        font.family: root.ff
        font.pixelSize: Style.font.display
      }
    }
  }

  // Bar-sized equalizer mark: three bars, alive while playing.
  component EqMark: Item {
    id: mark
    property real size: Style.bar.iconCanvas
    property color ink: root.fg
    property bool animating: false

    width: size
    height: size

    property real bw: Math.max(2, Math.round(size * 0.16))
    property real gap: Math.max(2, Math.round(size * 0.14))
    property real totalW: bw * 3 + gap * 2
    property real h0: animating ? size * 0.55 : size * 0.40
    property real h1: animating ? size * 0.85 : size * 0.62
    property real h2: animating ? size * 0.50 : size * 0.40

    Timer {
      interval: 260
      repeat: true
      running: mark.animating
      onTriggered: {
        mark.h0 = mark.size * (0.30 + Math.random() * 0.40)
        mark.h1 = mark.size * (0.55 + Math.random() * 0.40)
        mark.h2 = mark.size * (0.30 + Math.random() * 0.40)
      }
    }

    Repeater {
      model: 3
      delegate: Rectangle {
        required property int index
        width: mark.bw
        radius: Math.max(1, mark.bw / 2)
        color: mark.ink
        x: (mark.width - mark.totalW) / 2 + index * (mark.bw + mark.gap)
        y: mark.height - height
        height: index === 0 ? mark.h0 : index === 1 ? mark.h1 : mark.h2

        Behavior on height {
          enabled: mark.animating
          NumberAnimation { duration: 240; easing.type: Easing.OutCubic }
        }
        Behavior on color { ColorAnimation { duration: 200 } }
      }
    }
  }

  // Transport icon button (prev/play/next).
  component TransportButton: Button {
    property string glyph: ""
    property string label: ""
    property bool wide: false
    property bool cursorOn: false
    width: wide ? Style.space(64) : Style.space(44)
    height: root.controlH
    iconText: glyph
    tooltipText: label
    bordered: true
    foreground: root.fg
    fontFamily: root.ff
    hasCursor: cursorOn
  }

  // Preset / library row: glyph · name · dim meta, cursor-painted.
  component ListRow: Rectangle {
    property string glyph: ""
    property bool glyphWide: true
    property string name: ""
    property string meta: ""
    property bool cursorOn: false
    signal hovered(bool isHovered)
    signal clicked()

    width: panelColumn.width
    height: Style.space(24)
    radius: 0
    color: cursorOn ? Style.selectedFillFor(root.fg, Color.accent) : "transparent"

    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(4)
      anchors.rightMargin: Style.space(4)
      spacing: Style.space(8)

      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: glyphWide ? Style.space(16) : Style.space(12)
        textFormat: Text.PlainText
        text: glyph
        color: root.fg
        opacity: 0.75
        font.family: root.ff
        font.pixelSize: Style.font.bodySmall
        horizontalAlignment: Text.AlignHCenter
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(40, parent.width - parent.children[0].width
                - parent.children[2].width - parent.spacing * 2)
        textFormat: Text.PlainText
        text: name
        color: root.fg
        font.family: root.ff
        font.pixelSize: Style.font.bodySmall
        elide: Text.ElideRight
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, Style.space(110))
        textFormat: Text.PlainText
        text: meta
        color: root.fg
        opacity: 0.45
        font.family: root.ff
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignRight
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: parent.clicked()
      onEntered: parent.hovered(true)
      onExited: parent.hovered(false)
    }
  }

  component InfoPair: Row {
    property string label: ""
    property string value: ""

    width: parent.width
    spacing: Style.space(8)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: label
      color: root.fg
      opacity: 0.6
      font.family: root.ff
      font.pixelSize: Style.font.bodySmall
    }
    Item {
      anchors.verticalCenter: parent.verticalCenter
      width: Math.max(0, parent.width - parent.children[0].implicitWidth
              - parent.children[2].implicitWidth - parent.spacing * 2)
      height: 1
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: value
      color: root.fg
      font.family: root.ff
      font.pixelSize: Style.font.bodySmall
      elide: Text.ElideRight
    }
  }
}
