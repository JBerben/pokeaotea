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
`twinleaf rival 1f` works), then Enter to open the highlighted one. The search box
takes plain letters, so the browser's own actions use Ctrl:

| Key | Action |
| --- | --- |
| Ctrl+N | new map: the `new_map.py` form (scripts, text, events, optionally the header) |
| Ctrl+T | check every warp (`check_warps.py`), optionally listing one-way warps |
| Ctrl+F | free flags and variables (`find_free_state.py`), with a box to check one name |
| Esc | quit |

A new header copies its geometry from a template. The default template is a
single-room map, so the new map owns its block and opens straight away. A header
copied from an overworld map shares that map's matrix, whose cells each name their
own header, so it has no block until you give it a matrix of its own; mapedit says
so when you try to open it.

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
| Esc | back to the browser |

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
