# mapedit

`mapedit` is a terminal UI over the map scripts in `tools/scripts/`. It shows a
map's tiles, props and events, and lets you place, move and remove props and
register new ones without remembering command-line arguments.

```bash
uv run --project tools/mapedit mapedit
```

The first run creates `tools/mapedit/.venv` and installs Textual into it. uv is
the only thing you need installed ([install instructions](https://docs.astral.sh/uv/)).

## Screens

**Map browser.** Type to filter the map headers (words match in any order, so
`twinleaf rival 1f` works), then Enter to open the highlighted one. While the
search box has focus it takes every letter you type; press Down or Tab to move to
the list, where the browser's own keys work:

| Key | Action |
| --- | --- |
| Enter | open the highlighted map |
| `n` | new map: the `new_map.py` form (scripts, text, events, optionally the header) |
| `w` | check every warp (`check_warps.py`), optionally listing one-way warps |
| `f` | free flags and variables (`find_free_state.py`), with a box to check one name |
| `x` | the highlighted map's matrix |
| `/` | back to the search box |
| Esc | quit |

mapedit uses no Ctrl shortcuts: terminals inside editors such as VS Code keep
keys like Ctrl+N, Ctrl+F and Ctrl+O for themselves.

A new header copies its geometry from a template. The default template is a
single-room map, so the new map owns its block and opens straight away. A header
copied from an overworld map shares that map's matrix, whose cells each name their
own header, so it has no block of its own - tick "own matrix" to copy the
template's blocks into a matrix of the new map's own (`new_map.py --own-matrix`).

**Map view.** The left side is one 32x32 block of the map. Each tile shows its
kind, or what stands on it:

| Symbol | Meaning | Symbol | Meaning |
| --- | --- | --- | --- |
| `.` | walkable | `P` | prop |
| `#` | blocked | `W` | warp |
| `~` | water | `N` | NPC (object event) |
| `D` | door | `S` | sign (bg event) |
| `+` | other tile behavior | `T` | trigger (coord event) |

The right side describes the tile under the cursor and lists the block's props.

| Key | Action |
| --- | --- |
| arrows, mouse click | move the cursor (when the grid has focus; Tab switches to the props table) |
| `[` `]` | previous / next block of a multi-block map |
| `a` | add a prop at the cursor (the model list is the area's model set) |
| `m` | move the selected prop to the cursor |
| `d` | delete the selected prop |
| `r` | register a new prop (the `new_prop.py` form) |
| `i` | map info: entry table, what references each entry, events, text, flags and variables used (`map_info.py`) |
| `w` | check this map's warps |
| `f` | free flags and variables |
| `x` | the map's matrix |
| `p` | show or hide a rendered preview of the block (the cursor tile is outlined on the top view) |
| `v` | switch the preview between top-down and angled |
| `t` | play the block's texture animations live (ground tiles, waterfalls); `t` again stops. Blocks with nothing animated say so |

**Matrix editor.** A grid of the matrix's cells: each shows its land data number,
coloured by the header that owns it (`--` is no block). The side panel shows the
cell's header, land data, altitude and how many other cells share that land data.
`h`, `l` and `a` set the cell's header, land data and altitude; `u` gives the cell
its own copy of its land data; Enter opens the map that owns the cell. See
[maps/matrices.md](maps/matrices.md).
| Esc | back to the browser |

## Rendering maps and models

`mapedit-render` draws maps and models to PNG with a small software renderer
(`tools/mapedit/mapedit/render/`), so you can see a map - or have an AI agent look
at one - without building the ROM:

```bash
uv run --project tools/mapedit mapedit-render map MAP_HEADER_TWINLEAF_TOWN -o twinleaf.png
uv run --project tools/mapedit mapedit-render map MAP_HEADER_TWINLEAF_TOWN --view angled -o twinleaf_3d.png
uv run --project tools/mapedit mapedit-render map MAP_HEADER_TWINLEAF_TOWN --markers -o events.png
uv run --project tools/mapedit mapedit-render model waterfall.nsbmd --area-set 012 -o waterfall.png --json
```

- `map` renders every block of a map header at its matrix position and altitude:
  the land data's map model, textured from the area's map texture set, and each
  placed prop, textured only from the area's prop texture set - the same binding
  the game does, so a prop whose textures are missing from the area renders
  white here too. `--json` lists those missing textures.
- `--view top` (the default for maps) is orthographic with north up and frames the
  blocks exactly, so each block's 32 tiles span `size / blocks across` pixels;
  `--markers` dots warps (red), NPCs (cyan), signs (yellow) and triggers (green).
  `--view angled` is a perspective view from the south.
- `--animate` writes an animated GIF of the map's texture animations instead:
  the field's ground tiles (sea, beaches, flowers, lamps) and the props'
  self-playing NSBTA/NSBTP animations (waterfalls, signs), at the game's 30 frames a
  second. `--frames N` sets how many game frames to render and `--step K` renders
  every K-th one. Door, honey tree and bicycle slope animations only play when
  triggered in the game, so they stay still.
- `model` renders one model. By default its own embedded textures fill in for
  anything the given sets lack (handy before a prop is registered);
  `--no-embedded` renders it the way the game would.

The map view's preview (`p`) uses the same renderer. It rasterises the block once
and then only re-textures the animated surfaces each frame, so playback runs in
real time at the game's speed with no loop seams. How it is drawn depends on the
terminal:

- **Sixel** or the **Kitty graphics protocol** give real pixels, at the pane's
  full resolution. mapedit asks the terminal what it supports at start-up (via
  [textual-image](https://github.com/lnqs/textual-image)).
- Otherwise it uses **half blocks**: two pixels per character cell, which works in
  any true-colour terminal.

Force a mode with `mapedit --graphics sixel|kitty|halfblock` (default `auto`) if
detection gets it wrong. Terminals that can show Sixel include Windows Terminal
(1.22+), WezTerm, foot and VS Code's terminal (with
`terminal.integrated.enableImages` turned on); Kitty and Ghostty use the Kitty
protocol.

Not modelled yet: the DS lighting model, fog, toon shading, and joint (NSBCA)
animations. Geometry and textures are checked against retail data: every
model's triangle counts and bounds against its header, and every texture against
`nitrobtx`'s dump.

## How it writes

mapedit never edits files itself. Every change is built by the same code as the
command-line tools (`map_props.py`, `new_prop.py`, `new_map.py`), shown to you first, including
warnings such as shared land data, and only written when you press Apply. Anything
the scripts refuse, the UI shows as an error. See [maps/props.md](maps/props.md)
for what the checks mean.

## Development

The app lives in `tools/mapedit/` (`mapedit/maps.py` is the data layer;
`mapedit/app.py`, `mapedit/register.py` and `mapedit/reports.py` are the screens).
The reports call the scripts' data functions (`map_info.summarize`,
`check_warps.check_warps`, `find_free_state.free_summary`), so the screens and the
command lines always agree. They read the checkout mapedit runs from. Tests drive the real app
with Textual's pilot against a temporary copy of the repo files:

```bash
uv run --project tools/mapedit python -m unittest discover -s tools/mapedit/tests -t tools/mapedit
```

`meson test` runs them too when uv is installed.
