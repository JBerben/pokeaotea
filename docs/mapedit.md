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
`twinleaf rival 1f` works), then Enter to open the highlighted one.

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
| Esc | back to the browser |

## How it writes

mapedit never edits files itself. Every change is built by the same code as the
command-line tools (`map_props.py`, `new_prop.py`), shown to you first, including
warnings such as shared land data, and only written when you press Apply. Anything
the scripts refuse, the UI shows as an error. See [maps/props.md](maps/props.md)
for what the checks mean.

## Development

The app lives in `tools/mapedit/` (`mapedit/maps.py` is the data layer,
`mapedit/app.py` and `mapedit/register.py` the screens). Tests drive the real app
with Textual's pilot against a temporary copy of the repo files:

```bash
uv run --project tools/mapedit python -m unittest discover -s tools/mapedit/tests -t tools/mapedit
```

`meson test` runs them too when uv is installed.
