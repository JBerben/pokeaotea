# Map texture animations

Animated ground tiles like the sea, beaches, flowers, swamp water, street lamps and
warp panels are not stored in the map, the map texture set, or the area data. They
all come from one global archive, `data/fldtanime.narc`, and are tied to maps
**by texture name only**. A map texture set that contains a texture named `sea`
gets the sea animation on every map that uses that set, whatever area data or map
it belongs to.

Map editors such as Pokémon DS Map Studio never touch this archive, which is why
they cannot show or export these animations.

## How it works at runtime

The code lives in `src/overlay005/texture_resource_manager.c`.

1. When a map loads, `fieldmap.c` hands the area's map texture set to
   `TextureResourceManager_LoadTexture`.
2. For each animation in the table, the game looks up its texture name in that
   texture set. If the set has no texture by that name, the animation is skipped.
   The first 16 matches (`MAX_TEXTURE_KEYS`) each get a slot, in table order.
3. Once per game frame (about 30 per second in the overworld),
   `TextureResourceManager_Free` advances each slot. Despite the name, this is the
   per-frame update. When the current step's `hold` runs out, it copies the
   *texels* of the next step's frame over the base texture in VRAM.

Some consequences:

- **Palettes are never swapped.** Every frame is drawn with the base texture's
  palette from the map texture set. The palettes stored in the frames NSBTX are
  ignored.
- **The byte count comes from the base texture.** Frames need the same format
  and size as the base texture, or the copy will write garbage or only part of
  the texture.
- **Step 0 is not uploaded when the map loads.** Until the first step change, the
  map texture set's own texture is on screen, so make it identical to step 0's
  frame.
- **A step is on screen for `hold + 1` game frames.**

## Source layout

The archive is built from `res/field/texture_animations/` by
`tools/scripts/make_texture_animations.py`:

```
res/field/texture_animations/
├── texture_animations.json   # the animation table, in archive order
├── frames/<name>.nsbtx       # one NSBTX of frames per animation
└── meson.build               # lists every frames file
```

```json
{
    "animations": [
        {
            "texture": "sea",
            "frames": "sea.nsbtx",
            "sequence": [
                { "frame": 0, "hold": 9 },
                { "frame": 1, "hold": 9 }
            ]
        }
    ]
}
```

- `texture`: the texture name to match in map texture sets. 1-16 ASCII characters,
  unique.
- `frames`: file name under `frames/`.
- `sequence`: 1-17 steps that loop forever. `frame` is the **index** of a texture
  inside the frames NSBTX (not its name). `hold` is 0-255.

The packer refuses to build (and lists every problem) if a name is invalid or
duplicated, a step points past the last texture, a hold does not fit in a byte,
the textures in one frames file differ in format or size, a frames file uses 4x4
compressed or direct colour, or `meson.build` and the JSON disagree about which
frames files exist.

## Adding an animation

1. **Base texture.** In your map editor, give the tiles a material whose texture
   has a new, unique name (e.g. `wf_fall.1`) in the map texture set. Use a palette
   format (4, 16 or 256 colour, A3I5 or A5I3) at 16x16 or 32x32. Export the map
   texture set as usual.
2. **Frames.** Make an NSBTX (NitroPaint works well) holding every frame as a
   separate texture with the same size and format as the base texture, all indexed
   against the base texture's palette. Frame 0 should match the base texture.
   Save it as `res/field/texture_animations/frames/wf_fall_1.nsbtx`.
3. **Register it.** Add an entry to the end of `texture_animations.json` and add the
   file to the `files(...)` list in `res/field/texture_animations/meson.build`.
4. `make`. The new archive changes `filesys.sha1`, which the release build
   re-blesses.

Stick to 16x16 and 32x32. `CalcTextureDataSize` in `src/billboard_vram_transfer.c`
works out a dimension as `field << 4`, which is only right for 16 and 32 pixels. It
gives 0 bytes for 8px and too few for 64px. Some retail animations are 64px
(`azt_wall02.1`, `wtk_kabe1`-`3`).

## Viewing existing animations

The frames are ordinary NSBTX files. Open any file in
`res/field/texture_animations/frames/` in NitroPaint, or export it to PNGs with
[apicula](https://github.com/scurest/apicula) (`apicula convert sea.nsbtx`). The
timing for each is in `texture_animations.json`.

`tools/scripts/migration/texture_animations.py` converts a prebuilt
`fldtanime.narc` into this layout. It was used to extract the retail archive.
