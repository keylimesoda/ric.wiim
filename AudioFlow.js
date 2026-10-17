// Pure local-audio transitions. Side effects are executed by the hosted QML.
function initial() {
  return { wanted: false, phase: "off", generation: 0, error: "", notice: "", setup: "", effects: [] }
}

function reduce(previous, event) {
  var s = Object.assign({}, previous, { effects: [] })
  function fail(message) {
    s.wanted = false; s.phase = "failed"; s.error = message; s.effects = ["attention"]
  }
  if (event.type === "enable") {
    s.generation++; s.wanted = true; s.phase = "checking"
    s.error = ""; s.notice = ""; s.setup = ""; s.effects = ["check"]
    return s
  }
  if (event.type === "disable" || event.type === "cancel-setup") {
    s.generation++; s.wanted = false; s.phase = "stopping"; s.error = ""
    s.notice = event.type === "cancel-setup" ? "Setup canceled." : ""
    s.setup = ""; s.effects = ["stop"]
    return s
  }
  if (event.type === "stopped") {
    if (!s.wanted) s.phase = "off"
    return s
  }
  if (event.generation !== s.generation || !s.wanted) return s
  if (event.type === "checked" && s.phase === "checking") {
    var c = event.check
    if (!c.ready) {
      if (!c.canInstall) fail("Audio tools are missing. Install pactl and parec using your package manager.")
      else { s.phase = "needs-tools"; s.setup = "tools"; s.effects = ["attention"] }
    } else if (c.firewall === "needs-rule" && c.canSetupFirewall) {
      s.phase = "needs-firewall"; s.setup = "firewall"; s.effects = ["attention"]
    } else { s.phase = "connecting"; s.effects = ["start"] }
  } else if (event.type === "authorize" && (s.phase === "needs-tools" || s.phase === "needs-firewall")) {
    s.phase = "authorizing"; s.effects = ["authorize"]
  } else if (event.type === "authorized" && s.phase === "authorizing") {
    if (event.result.ok) {
      s.phase = "checking"; s.notice = ""; s.error = ""; s.setup = ""; s.effects = ["check"]
    } else if (event.result.canceled) {
      s.generation++; s.wanted = false; s.phase = "off"; s.notice = "Setup canceled."; s.setup = ""
    } else fail(event.result.message || "Setup failed. Please retry.")
  } else if (event.type === "network-help") {
    if (event.canSetupFirewall) {
      s.phase = "needs-firewall"; s.setup = "firewall"; s.effects = ["attention"]
    } else fail("WiiM could not reach this PC. Check firewall access or LAN isolation.")
  } else if (event.type === "progress" && ["connecting", "buffering", "streaming"].indexOf(s.phase) >= 0) {
    if (["connecting", "buffering", "streaming"].indexOf(event.phase) >= 0) s.phase = event.phase
  } else if (event.type === "failed") fail(event.message || "Could not start local audio.")
  return s
}

function pending(s) { return ["checking", "authorizing", "connecting", "buffering", "stopping"].indexOf(s.phase) >= 0 }
function needsAttention(s) { return ["needs-tools", "needs-firewall", "failed"].indexOf(s.phase) >= 0 }
function statusText(s) {
  switch (s.phase) {
    case "checking": return "Checking audio setup…"
    case "needs-tools": return "Audio tools need to be installed."
    case "needs-firewall": return "Allow this WiiM to receive audio from this PC."
    case "authorizing": return "Complete authorization in Omarchy’s authentication dialog…"
    case "connecting": return "Connecting to WiiM…"
    case "buffering": return "WiiM is buffering audio — this can take about 10 seconds."
    case "streaming": return "Streaming local audio"
    case "stopping": return "Restoring the previous audio output…"
    case "failed": return s.error
    default: return s.notice
  }
}
