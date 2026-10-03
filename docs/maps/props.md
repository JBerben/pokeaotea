# Map props

Map props are the 3D models placed on top of a map: buildings, doors, signs, trees,
the honey tree, bicycle slopes, gym puzzles. This page covers where their pieces live
in this repository and what has to line up for a prop to show up, textured and
animated. For the binary formats, see
[file_format_specifications.md](file_format_specifications.md).

## The pieces

A prop's **model ID** is its line number (from 0) in
`res/field/props/models/map_prop_models.order`. Everything below is keyed by that
order, and model sets and the per-model tables name models the way the generated
`.naix` does: the file name with the dot replaced, e.g. `honey_tree_nsbmd`.

| Piece | Source | Built into |
| --- | --- | --- |
| Model | `res/field/props/models/*.nsbmd`, listed in `meson.build` and `map_prop_models.order` | `fielddata/build_model/build_model.narc` |
| Area model list | `res/field/props/model_sets/prop_model_set_NNN.json` | `fielddata/areadata/area_build_model/area_build.narc` |
| Area textures | `res/field/props/texture_sets/prop_texture_set_NNN.nsbtx` | `fielddata/areadata/area_build_model/areabm_texset.narc` |
| Animations | `res/field/props/animations/*.nsbta/.nsbtp/.nsbca`, listed in `prop_animations.order` | `arc/bm_anime.narc` |
| Animation lists | `res/field/props/animations/prop_animation_lists.json` | `arc/bm_anime_list.narc` |
| Draw lists | derived from the models, plus `res/field/props/models/draw_order_overrides.json` | `fielddata/build_model/build_model_matshp.dat` |
| Placement | the `mapProps` section of `res/field/maps/data/map_data_NNN.bin` | `fielddata/land_data/land_data.narc` |

Area data (`res/field/area_data/area_data_NNN.json`) picks one model set and,
with the same ID, one texture set (`mapPropSet`).

The animation lists and draw lists are built by `tools/scripts/make_prop_tables.py`,
which validates everything first and lists every problem it finds.

## Adding a prop

`tools/scripts/new_prop.py` registers a model, its animations and its textures in
one step, and writes nothing unless every step can be done:

```bash
python3 tools/scripts/new_prop.py route_201_waterfall \
    --model waterfall.nsbmd --animation waterfall.nsbta \
    --model-set 12 --dry-run
```

It copies the model to `models/<name>.nsbmd` and each animation to
`animations/<name>_<i>.<ext>` (index = order given, the extension from the file's
magic), registers them in the `meson.build` and `.order` files, writes the
animation list entry, adds the model to each `--model-set`, and appends its
textures to the matching prop texture sets. The `--deferred-loading`,
`--deferred-add-to-render-obj` and `--bicycle-slope` flags set the animation list
flags described below; an ambient animation such as a waterfall needs none of them.

Textures come from `--textures` (an NSBTX) or, by default, from the textures
embedded in the model. The tool checks that the source holds every texture and
palette the model's materials bind. Appending never rewrites what is already in a
texture set: new textures and palettes go after the existing data, and one whose
name is already in the set is shared if identical, or rejected if not, since the
game would bind the existing one. 4x4 compressed textures are not supported.

The draw list needs no edit. Placing the prop on a map is the next step.

## Placing props on a map

`tools/scripts/map_props.py` edits the `mapProps` section of a map's land data:

```bash
python3 tools/scripts/map_props.py list MAP_HEADER_TWINLEAF_TOWN
python3 tools/scripts/map_props.py add MAP_HEADER_TWINLEAF_TOWN route_201_waterfall --x 112 --z 880 --dry-run
python3 tools/scripts/map_props.py move MAP_HEADER_TWINLEAF_TOWN 000:8 --y 2.5
python3 tools/scripts/map_props.py remove MAP_HEADER_TWINLEAF_TOWN 000:8
```

- **Coordinates** are world tiles, the same ones events and `check_tile.py` use. A
  whole number is the centre of that tile; fractions are allowed (retail buildings
  often sit on half tiles). Internally a prop's position is an offset from the
  centre of its 32x32 block (`LandDataManager_CalculateRenderingPosition`).
- **Height** is in tiles (16 units) above the block's base. `add` defaults it to the
  BDHC ground at that point, computed as the game does, and asks for `--y` when there
  is no ground there or several layers (a bridge). About 60% of retail props sit
  exactly on the ground; cliff-top and wall-mounted props do not.
- **Prop ids** are `<land data>:<index>`, as `list` prints them. Removing a prop moves
  the later ones in that block up one index.
- **Rotation is ignored** for placed props: `MapPropManager_Render` draws them
  unrotated, and every retail prop has a rotation of 0. Rotate the model itself. Scale
  is applied (`--scale`).
- **The model must be in the area's model set**, or the game silently draws the dummy
  box instead; `add` refuses and names the set to add it to.
- **Land data can be shared.** Every Poké Mart, for example, uses the same land data
  file, so a prop added to one appears in all of them. The tool lists every other map
  that an edit affects.

### A worked reference: the retail waterfalls

Retail Platinum already has waterfall props, `prop_model_305` to `prop_model_310`.
They use the textures `taki` (waterfall), `taki_top` and `kemuri` (mist), and all
play `prop_animation_018.nsbta`, a texture coordinate (scroll) animation, with no
animation flags. They are in model sets 005, 006, 009, 012, 049 and 065 to 067.
Converting one with apicula is a good way to see how the materials and the scroll
are set up before building your own.

## Textures come from the area, not the model

`AreaDataManager_Load` (`src/overlay005/area_data.c`) binds every prop model of an
area to that area's **prop texture set**. Textures embedded in the NSBMD are ignored.
Binding is by texture and palette name, and a name that is missing from the texture
set is not an error: the prop just renders untextured (white). So a prop's textures
must be in the texture set of every area whose model set includes it.

## Animation lists

`prop_animation_lists.json` has one entry per *animated* model; every model not
listed gets the "no animations" entry.

```json
{
    "honey_tree_nsbmd": {"animations": ["prop_animation_001_nsbca", "prop_animation_002_nsbca", "prop_animation_003_nsbca"], "deferredAddToRenderObj": true}
}
```

| Field | Meaning |
| --- | --- |
| `animations` | 1 to 4 names from `prop_animations.order`. Index in this list is the animation index scripts and field code use. |
| `deferredLoading` | Optional. Do not load the animations with the area; field code loads them on demand (doors). |
| `deferredAddToRenderObj` | Optional. Load the animations but do not attach them when the prop is placed; field code starts them (honey tree shaking). |
| `bicycleSlope` | Optional. Load the animation paused, to be played once (muddy bicycle slopes). |

With no flags, the animations are loaded with the area and loop forever. That is
what an ambient animation such as a waterfall wants.

NSBTA (texture coordinate) and NSBTP (texture pattern) animations bind to the
model by **material name**, so the material names in the animation must match the
model's. NSBCA (joint) animations bind by node index, so they must come from the
same source scene as the model.

## Draw lists

An unanimated prop is drawn one (material, shape) pair at a time from its draw
list, which the builder derives from the model's own render commands, sorted by
material ID so that each material is sent once. Animated props have an empty draw
list, which makes the renderer draw the whole model so the animations apply. You
never need to edit draw lists for a new model.

`draw_order_overrides.json` replaces the derived order for a model, using material
and shape names. It must list exactly the draws the model has. Retail uses it for
three Twinleaf houses, which draw their door last:

```json
{
    "prop_model_022_nsbmd": [
        {"material": "h_kage", "shape": "polygon2"},
        {"material": "light", "shape": "polygon1"},
        {"material": "t1_h01", "shape": "polygon0"},
        {"material": "door1", "shape": "polygon3"}
    ]
}
```

## Limits

- 768 models in total (`MAX_MAP_PROP_MODEL_FILES`): the area loader keeps model
  files in an array indexed by model ID.
- 32 props placed per map (`MAX_LOADED_MAP_PROPS`).
- 4 animations per model, 16 animations loaded at once across the area
  (`MAP_PROP_ANIMATION_MANAGER_MAX_ANIMATIONS`).

## Migrating an edited ROM's tables

If you had hand-edited `bm_anime_list.narc` or `build_model_matshp.dat` from a ROM,
`tools/scripts/migration/prop_tables.py` turns them into the JSON sources above. It
refuses to write anything unless the JSON rebuilds the input byte for byte.
