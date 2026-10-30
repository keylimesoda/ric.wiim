import QtQuick
import Quickshell.Io

// One daemon per shell, shared by all monitor widgets.
Item {
  id: root
  property var shell: null
  property var manifest: null
  property string bin: ""
  property string deviceIp: ""
  property string musicDir: ""
  property int pollMs: 500
  property bool enabled: false
  property bool ready: false
  property string helloLine: ""
  property string stateLine: ""
  property int sequence: 0
  property int backoffMs: 1000
  signal lineReceived(string line)
  signal stopped()

  function configure(path, ip, dir, interval, fixture) {
    var changed = bin !== path || deviceIp !== ip || musicDir !== dir || pollMs !== interval || enabled === fixture
    bin = path; deviceIp = ip; musicDir = dir; pollMs = interval; enabled = !fixture
    if (changed) configureTimer.restart()
  }
  function send(cmd, args) {
    if (!daemon.running || !ready) return -1
    sequence += 1
    daemon.write(JSON.stringify({id: sequence, cmd: cmd, args: args || {}}) + "\n")
    return sequence
  }
  Timer {
    id: configureTimer; interval: 100
    onTriggered: {
      retry.stop(); root.ready = false; root.helloLine = ""; root.stateLine = ""
      if (daemon.running) daemon.running = false
      if (root.enabled && root.bin) Qt.callLater(function() { daemon.running = true })
    }
  }
  Process {
    id: daemon
    command: (root.deviceIp ? [root.bin, "--ip", root.deviceIp] : [root.bin]).concat(
      ["daemon", "--dir", root.musicDir, "--interval", String(root.pollMs / 1000)])
    stdinEnabled: true
    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function(data) {
        try {
          var obj = JSON.parse(data)
          if (obj.event === "hello") { root.ready = true; root.helloLine = data; root.backoffMs = 1000 }
          else if (obj.event === "state") root.stateLine = data
        } catch (e) { return }
        root.lineReceived(data)
      }
    }
    stderr: SplitParser { splitMarker: "\n"; onRead: function(data) { console.warn("wiim: " + data.slice(0, 500)) } }
    onExited: {
      root.ready = false; root.helloLine = ""; root.stateLine = ""; root.stopped()
      if (root.enabled && !configureTimer.running) retry.restart()
    }
  }
  Timer {
    id: retry; interval: root.backoffMs
    onTriggered: { root.backoffMs = Math.min(30000, root.backoffMs * 2); if (root.enabled) daemon.running = true }
  }
}
