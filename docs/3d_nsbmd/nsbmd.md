I have everything I need. Here is the picture.

## Why your build crashed

The title screen loads three separate files from `titledemo.narc` and binds them together in `TitleScreen_Load3DGfx` (`src/applications/title_screen.c:522`):

- `giratina.nsbmd`, the model **with its textures embedded**. The code calls `NNS_G3dGetTex` on the model file itself, so a separate NSBTX would be ignored here.
- `giratina.nsbca`, the skeletal animation.
- `giratina.nsbta`, the texture scroll animation.

The skeletal animation is the killer. NitroSystem binds an NSBCA to a model **by node index**, not by name. The original model has 27 nodes (`world_root` plus 26 `joint*` bones), and the NSBCA carries a curve for each one. The binder allocates a map sized to the model's node count, then writes one entry per animation node. An OBJ has no skeleton, so a model rebuilt from one has a single node. The binder writes 27 entries into a 1-entry buffer. The size assert that would catch this is compiled out of the ROM by `SDK_FINALROM`, and `GF_ASSERT` only shows an error screen if the comm system is initialised, which it is not on the title screen. So the ARM9 corrupts its heap and wanders off, while the ARM7 keeps playing music. That matches your symptom exactly.

The NSBTA is more forgiving. It binds by **material name** and skips names it cannot find. The originals are `lambert1` and `lambert2`.

## How content actually gets into the ROM

You do not need to unpack anything. The pipeline is:

1. `res/graphics/title_screen/giratina.nsbmd`, `.nsbca`, `.nsbta` are plain files in the source tree.
2. `res/graphics/title_screen/meson.build` copies them into `titledemo.narc` in the order given by `titledemo.order`.
3. That NARC is listed in `platinum.us/filesys.csv`, so `nitrorom` packs it into the ROM.
4. The generated header `build/res/graphics/title_screen/titledemo.naix` gives the C code the member indices (`giratina_nsbmd` and friends).

So the whole loop is: overwrite the three files, run `make`, done. The bless step records the new hashes automatically.

## A workflow that will work

Keep the rig. Round-trip the original with its skeleton instead of flattening it to an OBJ.

1. Convert the original to something Blender understands with rigging intact. apicula can turn `giratina.nsbmd` plus `giratina.nsbca` into glTF or COLLADA with bones and the animation attached.
2. Edit the mesh in Blender on top of that armature. Every vertex may belong to only one vertex group, because the DS has no weighted skinning. Keep the material names `lambert1` and `lambert2` if you want to reuse the original texture animation.
3. Export with the NNS Blender plugin. It writes IMD for the model and ICA for the armature animation, and it wants textures as NITRO TGA, which NitroPaint can produce.
4. Convert with `g3dcvtr`, the NitroSystem command line converter, to `.nsbmd` and `.nsbca`. Make sure the textures end up embedded in the NSBMD rather than split into an NSBTX. This tool is not in the repo; it ships with the NitroSystem SDK tools and the DS hacking wikis cover where to get it.
5. Replace **both** the `.nsbmd` and the `.nsbca`. Since they come from the same Blender scene, the node indices line up by construction. That is the point of exporting your own ICA rather than reusing the shipped NSBCA.
6. Before building the ROM, open the new NSBMD in apicula's viewer. If apicula cannot render it, the game will not either.

Budgets that matter for this scene, from the title screen code:

| Resource            | Budget                                                        |
| ------------------- | ------------------------------------------------------------- |
| Title screen heap   | 256 KB, shared with the portal and face models and all 2D art |
| Texture VRAM        | 128 KB                                                        |
| Palette VRAM        | 64 KB                                                         |
| Original model file | 55 KB, 2 textures, 3 materials, one mesh                      |

Texture sizes must be powers of two and in a NITRO format such as 16 or 256 colour paletted. A Blender-style 1024x1024 RGBA texture will not fit.

**A useful intermediate milestone.** If you want to prove the model displays before the animation is right, I can add a small change to `TitleScreen_Load3DGfx` that skips the NSBCA when the model's node count does not match, and logs the model's node and material counts through `EmulatorLog` under `make debug`. That turns the black screen into a readable message in melonDS. Say the word and I will do it.

Sources:
- [nns-blender-plugin](https://github.com/jellees/nns-blender-plugin)
- [apicula](https://github.com/scurest/apicula)
- [DSHack: NNS Blender Plugins](https://wiki.dshack.org/Wiki.jsp?page=NNS+Blender+Plugins)
- [DSHack: custom characters with Blender](https://wiki.dshack.org/Wiki.jsp?page=How+to+create+custom+characters+with+just+Blender+and+some+plugin)
- [GBAtemp: nsbmd editing tutorial](https://gbatemp.net/threads/tutorial-nsbmd-editing.130362/)