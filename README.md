# WiiM Controller

[![Built for Omarchy: Plugin](https://raw.githubusercontent.com/tcballard/omarchy-badges/75975e5b5bf75e7ede3764bcd2950046f7abfe2c/badges/v1/omarchy-plugin.svg)](https://github.com/tcballard/omarchy-badges)

Your WiiM speakers, right in the [Omarchy](https://omarchy.org) bar:
now playing, transport, seek, volume, presets, input sources, EQ, a
sleep timer, and your local music library. No cloud, no vendor app —
the bundled CLI speaks the player's local API directly.

![The panel, with music playing](docs/screenshots/fixture-panel.png)

## Why

The WiiM Home app is phone-first, and the remote API is raw HTTP/XML.
If you already live in the bar, you deserve the same control there:
a chip that shows what's happening, a panel you drive entirely from
the keyboard, and a CLI for scripts and keybindings. Same philosophy
as its sibling, [ric.dd8c](https://github.com/keylimesoda/ric.dd8c) —
here for WiiM / Linkplay players.

## What you get

- **Bar chip** — a little equalizer mark: dim = idle, faint = paused,
  dancing = playing, speaker glyph = offline. Optionally shows
  `Title · Artist`, gliding when the text is long.
- **Keyboard-first panel** — transport, seek, volume, presets, sources
  (Wi-Fi · Bluetooth · Optical · Line-in · TV), EQ, sleep timer with
  countdown, local library browser, device info.
- **Local library streaming** — browse folders of FLAC/MP3 and hit
  `Enter`; the built-in HTTP server hands the player a direct URL.
  No import, no database.
- **Desktop audio out** *(experimental)* — one toggle makes the WiiM
  your computer's audio output: lossless live WAV, roughly 10 seconds
  behind (music only). See [Desktop audio out](#desktop-audio-out-experimental).
- **CLI + IPC** — drive it from scripts, keybindings or dotfiles.
- **Stdlib only** — the daemon is pure Python 3, no pip dependencies.

![Idle, against a real WiiM Pro Receiver](docs/screenshots/live-panel.png)

## Bar chip

- **Click** — open/close the panel
- **Middle-click** — play/pause
- **Scroll** — volume ±`volStep` (hidden automatically on fixed-level
  digital outputs)

## Panel keys

- `Tab` / `j` `k` — sections · `h` `l` — adjust within section
- `Enter` — activate focused control · `Space` — play/pause
- `,` `.` previous/next · `+` `-` volume · `m` mute · `1`–`9` `0` presets
- `s` cycle source · `e` EQ on/off · `t` sleep timer · `r` refresh
- `u` library up · `Esc` close (popups first)

## Summon without the bar

```
omarchy-shell ric.wiim toggle        # bind to a key if you like
```

IPC for scripts:

```
omarchy-shell ric.wiim playPause
omarchy-shell ric.wiim preset 3
omarchy-shell ric.wiim volSet 40
```

## Smart media keys

Route the keyboard's play/pause/skip keys through the built-in router —
WiiM when it's the active source, MPRIS players otherwise. In
`~/.config/hypr/bindings.lua`:

```lua
hl.unbind("XF86AudioPlay");  hl.unbind("XF86AudioPause")
hl.unbind("XF86AudioNext");  hl.unbind("XF86AudioPrev")
o.bind("XF86AudioPlay",  "Play/pause (WiiM smart)", "wiim media playPause", { locked = true })
o.bind("XF86AudioPause", "Play/pause (WiiM smart)", "wiim media playPause", { locked = true })
o.bind("XF86AudioNext",  "Next (WiiM smart)",       "wiim media next",      { locked = true })
o.bind("XF86AudioPrev",  "Previous (WiiM smart)",   "wiim media previous",  { locked = true })
```

## CLI (same engine the widget uses)

```
bin/wiim discover                 # find players via mDNS
bin/wiim status                   # full snapshot (JSON)
bin/wiim play | pause | next | previous | stop
bin/wiim vol 40                   # absolute % (clamped)
bin/wiim mute on|off
bin/wiim preset 3                 # a preset saved in WiiM Home
bin/wiim source optical           # wifi | bluetooth | optical | linein | tv
bin/wiim eq jazz                  # built-in EQ, or: eq off
bin/wiim sleep 1800               # sleep timer, -1 = off
bin/wiim play-url URL             # stream any direct URL
bin/wiim library [PATH]           # browse the local music dir
bin/wiim localout                 # stream desktop audio to the player
bin/wiim firewall                 # print the firewall rule for inbound audio
```

## Desktop audio out (experimental)

Flip **Play PC audio through WiiM** in the panel's Device section (or run
`bin/wiim localout` in a terminal) and your computer's audio output
becomes the WiiM: a PipeWire sink is created and made the default, its
monitor is streamed as an endless **lossless 44.1 kHz/16-bit WAV**, and
the player is pointed at it. Toggle it off (or Ctrl-C) and everything
is undone — old default output restored, sink removed, stream stopped.
Requires `pactl` and `parec` (PulseAudio utilities, also used with
PipeWire). Applications move to the new output only
after capture produces PCM and the WiiM connects. A capture or connection
failure leaves their routing alone and shows an error in the panel.

- The switch turns on immediately to acknowledge your request. A spinner
  and status distinguish **Checking**, **Connecting**, **Buffering**, and
  **Streaming**. Local tool/firewall checks normally finish in under a
  second and time out after three seconds; connecting to the player is a
  separate step. Known missing prerequisites appear before playback starts.
- Closing the panel leaves startup running. The bar shows pending/setup
  status, and a single actionable notification offers **Continue setup**
  when attention is needed. Reopening takes you to the setup section.
- Toggle off to cancel startup or restore the previous audio output.
  Canceling authentication returns the switch to off. If you turn audio
  off during an already-authorized package operation, it may finish, but
  audio will stay off. Failures offer **Retry audio** and **Dismiss**.
- **Expect roughly 10 seconds of delay** (observed on a WiiM Pro; it can
  vary by device). Playback, pause, and other PC audio changes are delayed.
  Intended for music; unsuitable for video, calls, or interactive sound.
- **Missing tools:** enabling desktop audio checks for `pactl` and `parec`.
  On Omarchy/Arch, the panel offers **Install audio tools (libpulse)…**.
  Clicking it shows an in-panel confirmation, then Omarchy’s native Polkit
  authentication dialog. The fixed `libpulse` package is installed by the
  system package manager; results appear in the panel. Canceling leaves
  desktop audio off. Successful installation automatically continues the
  original request; no second toggle is needed.
- **Network access:** this mode runs an HTTP server on the PC; the WiiM
  connects to it to fetch sound. If your PC firewall blocks inbound LAN
  connections, allow TCP 7402 from the WiiM's IP only. No router port
  forwarding is needed. After a failed connection, the panel offers
  **Allow this WiiM through firewall…** when UFW is available. It shows an
  in-panel explanation of the player-specific rule, followed by Omarchy’s
  native Polkit authentication dialog. Results and cancellation stay in the
  panel. The rule is restricted to that player and your audio port. UFW
  configured as inactive or an existing matching rule makes no changes.
  The plugin never enables UFW or opens a console window.
  Successful authorization automatically continues startup. For other
  firewalls, configure the equivalent rule manually and select Retry.
  For UFW, replace `PLAYER_IP` with the speaker's address:

  ```bash
  sudo ufw allow from PLAYER_IP to any port 7402 proto tcp
  ```

  Remove that exception when no longer needed:

  ```bash
  sudo ufw delete allow from PLAYER_IP to any port 7402 proto tcp
  ```

  Use your configured `localoutPort` if changed. Local-library playback
  separately uses TCP 7401. `bin/wiim firewall` prints a broader example
  covering both ports; prefer a player-specific rule for desktop audio.
- Starting playback elsewhere on the player (Tidal, a preset) simply
  takes over; flip the toggle off and on again to return.

## Settings (shell.json layout entry)

| key | default | meaning |
|---|---|---|
| `deviceIp` | `""` | pin a player; `""` = mDNS discovery |
| `musicDir` | `~/Music` | local library root served to the player |
| `volStep` | `5` | scroll / key volume step |
| `pollMs` | `500` | status poll rate (deeper state every 15 s) |
| `barText` | `true` | show now-playing text in the bar |
| `localoutPort` | `7402` | TCP port the player pulls desktop audio from |
| `fixture` | `false` | demo data, no device |

## Tidal, radio, Bluetooth

The player handles streaming services — this widget tells it what to
do. Save a favorite Tidal album/station/mix as a **preset** once in the
WiiM Home app, and from then on it's one keypress (`1`–`9`) from the
bar. Tidal Connect still works too: start playback in the Tidal app and
the panel picks up metadata, transport, and media keys from there.

## Safety

The CLI never sends firmware, factory-reset, or shutdown verbs — the
sleep timer is the only timer it touches, and `setShutdown:0` is never
sent. Volume is clamped to the device's advertised range. Every write
is an explicit command; polling is read-only.

## Good to know

- **Digital outputs are fixed-volume.** Optical/coax out passes a
  fixed line level — the player accepts volume commands but ignores
  them (hardware, not a bug). The panel notices and shows
  *"fixed level — control at the amp"* instead of a dead slider.
  Mute still works.
- **Local streaming needs the player to reach your PC.** Open the
  inbound ports once: `bin/wiim firewall` prints the ufw rule (a
  default-deny firewall, not your router, is the usual blocker). Some
  access points additionally enable *client isolation*, which no
  firewall rule can undo — library playback and desktop audio out
  stall there, and the panel says so. Radio presets and Tidal are
  unaffected either way.

## Requirements

- Omarchy 4 with Quattro shell-plugin support.
- Python 3 (stdlib only; no pip dependencies).
- Optional desktop audio: `pactl` and `parec` (`libpulse` on Arch); the
  panel offers installation if missing. Normal player controls do not need them.
- A WiiM / Linkplay player on the same LAN (mDNS for discovery;
  `wiim discover` lists what it finds).

## Installation

```bash
omarchy plugin add https://github.com/keylimesoda/ric.wiim.git --enable
```

For a local checkout:

```bash
omarchy plugin add "$(pwd)" --enable
```

To remove:

```bash
omarchy plugin remove ric.wiim
```

## Tests

```bash
python3 -m unittest discover -s tests   # CLI + fake-player protocol tests
node tests/test_model.js                # view-model tests
```

Try it risk-free: set `"fixture": true` and the panel runs on
deterministic demo data — no player required.

## Credits & trademark note

This is an unofficial community plugin; the local control protocol was
documented from the vendor's own app traffic (see `docs/`). Not
affiliated with Linkplay Computing. WiiM is a trademark of its
respective owner.

MIT licensed — see [LICENSE](LICENSE). Design decisions live in
[DESIGN.md](DESIGN.md).
