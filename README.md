# ric.wiim

**Your WiiM speakers, right in the [Omarchy](https://omarchy.org) bar.**

One tidy chip in the top bar, one panel for everything: play/pause, seek,
volume, presets, input sources, EQ, a sleep timer, and your local music
library. It speaks to WiiM / Linkplay players directly over your LAN — no
cloud, no companion app, no daemons to babysit. Everything is reachable by
keyboard in seconds.

![The panel, with music playing](docs/screenshots/fixture-panel.png)

*Left: the full panel while "Teardrop" plays (shown with demo data).
Right: the same panel against a real WiiM Pro Receiver, idle.*

## What you get

- **A bar chip that tells the story at a glance** — a little equalizer mark:
  dim when idle, bright when paused, dancing while playing, a speaker glyph
  when the player is offline. Optionally shows `Title · Artist`, gliding
  when the text is long.
- **A panel you never have to mouse through** — one cursor walks the
  sections with `⇥` / `j k` / `h l`; `⏎` activates, `␣` always plays or
  pauses, and number keys fire presets instantly.
- **Your local library, streamed to the player** — browse folders of
  FLAC/MP3 in the panel and hit `⏎`; the built-in HTTP server hands the
  player a direct URL. No import, no database.
- **Presets, sources, EQ, sleep timer** — whatever you set up in the WiiM
  Home app, you can fire from the bar from then on.
- **Smart media keys** — your keyboard's play/pause/skip keys go to the
  WiiM when it's the active source, and to any other music player
  otherwise.
- **A first-class CLI** — the same control from any terminal or script:
  `wiim play`, `wiim preset 3`, `wiim status`. The panel is just one
  client of it.

## Install

Requires Omarchy 4.0.0.alpha ("Quattro") — the hosted Quickshell shell.

```sh
git clone https://github.com/keylimesoda/omarchy-wiim \
  ~/.config/omarchy/plugins/ric.wiim
```

Add the widget to your bar in `~/.config/omarchy/shell.json` — for example
in `bar.layout.center`, next to your other widgets:

```json
{ "id": "ric.wiim" }
```

Restart the shell (`omarchy-restart-shell`) and the chip appears. That's
it — the widget finds your WiiM player on the LAN automatically. If you
have several players (or a flaky mDNS setup), pin one:

```json
{ "id": "ric.wiim", "deviceIp": "192.168.1.50" }
```

### Optional: the CLI on your PATH

The widget works without this, but the CLI is handy on its own:

```sh
ln -s ~/.config/omarchy/plugins/ric.wiim/bin/wiim ~/.local/bin/wiim
wiim discover            # list players on your network
wiim config set ip 192.168.1.50   # pin one (optional)
```

No dependencies beyond Python 3 — `bin/wiim` is a single stdlib-only file.

## Using it

| gesture            | what happens                          |
|--------------------|----------------------------------------|
| left-click the chip| open the panel                         |
| middle-click       | play / pause                           |
| scroll wheel       | volume up / down                       |

### Keyboard, inside the panel

`⇥` / `⇧⇥` move between sections, `j` / `k` move within a list,
`h` / `l` adjust sliders and chips, `⏎` activates the focused section.
Then there are direct keys that never move the cursor:

| key           | action                     |
|---------------|----------------------------|
| `␣`           | play / pause               |
| `,` `.`       | previous / next            |
| `+` `=` / `-` `_` | volume up / down       |
| `m`           | mute                       |
| `1`–`9`, `0`  | preset 1–9, 10             |
| `s`           | next input source          |
| `e`           | EQ on / off                |
| `t`           | cycle sleep timer          |
| `u`           | library: up one folder     |
| `r`           | refresh                    |
| `esc`         | close (popups first)       |

Want a hotkey for the panel itself? Add this to
`~/.config/hypr/bindings.lua` and `hyprctl reload`:

```lua
o.bind("SUPER + M", nil, "omarchy-shell ric.wiim toggle")
```

### Smart media keys

If you use the keyboard's play/pause/skip keys, route them through the
built-in router — WiiM when it's the active source, MPRIS players
otherwise. In `~/.config/hypr/bindings.lua`:

```lua
hl.unbind("XF86AudioPlay");  hl.unbind("XF86AudioPause")
hl.unbind("XF86AudioNext");  hl.unbind("XF86AudioPrev")
o.bind("XF86AudioPlay",  "Play/pause (WiiM smart)", "wiim media playPause", { locked = true })
o.bind("XF86AudioPause", "Play/pause (WiiM smart)", "wiim media playPause", { locked = true })
o.bind("XF86AudioNext",  "Next (WiiM smart)",       "wiim media next",      { locked = true })
o.bind("XF86AudioPrev",  "Previous (WiiM smart)",   "wiim media previous",  { locked = true })
```

## Settings

All optional, set per entry in `shell.json`:

| key        | default    | meaning                                          |
|------------|------------|--------------------------------------------------|
| `deviceIp` | *(empty)*  | pin a player; empty = auto-discover at startup   |
| `musicDir` | `~/Music`  | local library root served to the player          |
| `volStep`  | `5`        | volume step for `+`/`−` and the wheel            |
| `pollMs`   | `500`      | status poll rate (deeper state every 15 s)       |
| `barText`  | `true`     | show `Title · Artist` next to the bar mark       |
| `fixture`  | `false`    | demo mode: fictional data, no player touched     |

## Tidal, radio, Bluetooth

The player itself handles streaming services — this widget tells it what
to do. The smoothest setup: save your favorite Tidal album/station/mix as
a **preset** once in the WiiM Home app, and from then on it's a single
keypress (`1`–`9`) from the bar. Tidal Connect still works too: start
playback from the Tidal app and the panel picks up the metadata,
transport, and media keys from there.

## Good to know

- **Digital outputs are fixed-volume.** Optical/coax out passes a fixed
  line level — the player accepts volume commands but ignores them (this
  is hardware, not a bug). The panel notices and says *"fixed level —
  control at the amp"* instead of showing a dead slider. Mute still works.
- **Local streaming needs the player to reach your PC.** Some access
  points enable *client isolation*, which blocks device↔PC traffic on the
  Wi-Fi. If playback of library files stalls, the panel tells you exactly
  that. Normal home networks are fine; radio presets and Tidal are
  unaffected either way.
- **Sleep timer only.** The CLI never touches the player's shutdown
  timer — it can only set or clear the sleep timer.

## CLI reference

```
wiim [--ip IP] <command>

discover                     list players (mDNS)
status [--fast]              JSON snapshot
play | pause | play-pause | stop | next | previous
vol [N]                      get/set volume          mute [0|1]
preset N                     play a saved preset
source <wifi|bluetooth|optical|linein|…>
eq <name|off>                built-in EQ             seek N (ms)
loop <none|all|one|shuffle>  sleep [SEC]             library [PATH]
play-url URL [TITLE]         stream any URL
serve / daemon               HTTP server / watch+command loop
media [--prefer auto|wiim|mpris] ACTION              media-key router
config show|set KEY VAL      ~/.config/wiim/config.json
```

## Development

```sh
python3 -m unittest discover -s tests   # CLI + fake-player protocol tests
node tests/test_model.js                # view-model tests
```

Try it risk-free: set `"fixture": true` in the widget's settings and the
panel runs on deterministic demo data — no player required. For GUI
development, [omabox](https://github.com/riovai/omabox) gives you a
throwaway sandboxed desktop: `omabox up --plugin ~/Work/wiim`.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Linkplay Computing.
WiiM is a trademark of its respective owner.
