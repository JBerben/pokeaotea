# Replacing 3D Models

This page walks through replacing a 3D model that ships in the ROM, using the
Giratina on the title screen as the worked example. It covers how model files
reach the ROM, what the game expects when it binds a model to its animations,
why a naive replacement crashes, and a workflow that works. For the rendering
APIs themselves see [3D Graphics](3d_rendering.md).

## Table of Contents

<!--toc:start-->
- [How a model gets into the ROM](#how-a-model-gets-into-the-rom)
- [What the title screen loads](#what-the-title-screen-loads)
- [How animations bind to a model](#how-animations-bind-to-a-model)
- [Why an OBJ round-trip crashes](#why-an-obj-round-trip-crashes)
- [A workflow that works](#a-workflow-that-works)
- [Budgets](#budgets)
- [Debugging a black screen](#debugging-a-black-screen)
<!--toc:end-->

## How a model gets into the ROM

Model files are plain files in the source tree. You do not need to unpack a
NARC to replace one. For the title screen:

1. `res/graphics/title_screen/giratina.nsbmd`, `giratina.nsbca`, and
   `giratina.nsbta` sit next to the 2D assets for the same screen.
2. `res/graphics/title_screen/meson.build` copies them, along with the
   converted 2D graphics, into `titledemo.narc`. The member order is fixed by
   `titledemo.order`.
3. `platinum.us/filesys.csv` maps `titledemo.narc` to `/demo/title/titledemo.narc`
   in the NitroFS, and `nitrorom` packs it.
4. The build also emits `build/res/graphics/title_screen/titledemo.naix`, a
   header of member indices. C code refers to members by name
   (`giratina_nsbmd`, `giratina_nsbca`, ...), so reordering `titledemo.order`
   does not break the code.

The loop is therefore: overwrite the file, run `make`. The bless step records
the new hashes (see [Checksums and Blessing](checksums_and_blessing.md)).

Other models follow the same pattern. Find the `.nsbmd` under `res/`, look at
the `meson.build` beside it to see which NARC it lands in, and check
`filesys.csv` for where that NARC is mounted.

## What the title screen loads

`TitleScreen_Load3DGfx` in `src/applications/title_screen.c` reads three
members from `titledemo.narc` and binds them:

| File               | Contents                              | Bound by                                |
| ------------------ | ------------------------------------- | --------------------------------------- |
| `giratina.nsbmd`   | Model **with textures embedded**      | `Easy3D_InitRenderObjFromResource`      |
| `giratina.nsbca`   | Joint (skeletal) animation            | `NNS_G3dAnmObjInit`, mapped by node index |
| `giratina.nsbta`   | Texture SRT animation                 | `NNS_G3dAnmObjInit`, mapped by material name |

The code obtains the texture block with `NNS_G3dGetTex` on the model file
itself. A separate `.nsbtx` is not consulted for this model, so the replacement
must embed its textures.

The shipped model has:

- 27 nodes: `world_root` plus `joint1` through `joint23` with a few `_1`/`_2`
  variants.
- 3 materials: `lambert1`, `lambert2`, `lambert3`.
- 2 textures (`gira01`, `gira02`) with matching palettes.
- One mesh (`polySurface189`).
- A file size of about 55 KB.

## How animations bind to a model

The rules come from NitroSystem (`subprojects/NitroSystem-*/libraries/g3d/src/anm/`).

**Joint animations (`.nsbca`) bind by node index.** Each curve in the
animation carries the index of the node it drives. The binder allocates a map
sized to the *model's* node count, then writes one entry per *animation* node.
Names are not consulted. The animation and the model must therefore describe
the same skeleton in the same order. A model with a different node count or
order will animate the wrong bones at best.

**Texture animations (`.nsbta`) bind by material name.** Each entry is looked
up in the model's material dictionary. Names that do not exist are skipped.
This one is forgiving: keep the material names `lambert1` and `lambert2` and
the original texture scroll keeps working.

**Asserts do not protect you.** The size check in the joint binder is an
`NNS_G3D_ASSERT`, which is compiled out of the ROM by `SDK_FINALROM`. The
game's own `GF_ASSERT` only shows an error screen once the comm system is
initialised, which on the title screen it is not. A mismatch corrupts memory
silently.

## Why an OBJ round-trip crashes

The symptom is a black screen after the intro with the music still playing.
The ARM7 keeps running audio while the ARM9 has wandered off.

An OBJ has no skeleton. A model rebuilt from one has a single node. When the
title screen binds the original 27-node `giratina.nsbca` to it, the binder
writes 27 map entries into a buffer sized for 1. With the assert compiled out,
the heap is corrupted and the game hangs. Textures exported separately, or in
a format the DS cannot use, make things worse but are not the first cause.

## A workflow that works

Keep the rig. Round-trip the original with its skeleton instead of flattening
it to an OBJ, and export your **own** animation so the node order matches by
construction.

1. Convert `giratina.nsbmd` plus `giratina.nsbca` to glTF or COLLADA with
   [apicula]. Rigging and the animation come across.
2. Edit the mesh in Blender on top of that armature. Every vertex may belong
   to exactly one vertex group: the DS has no weighted skinning. Keep material
   names `lambert1` and `lambert2` if you intend to reuse the shipped `.nsbta`.
3. Export with the [NNS Blender plugin]. It writes an `.imd` for the model and
   an `.ica` for the armature animation. Textures must be NITRO TGA, which
   NitroPaint can produce; other formats are ignored by the exporter.
4. Convert with `g3dcvtr`, the NitroSystem command line converter, to
   `.nsbmd` and `.nsbca`. Make sure the textures end up embedded in the
   `.nsbmd` rather than split into an `.nsbtx`. `g3dcvtr` is not part of this
   repository; it ships with the NitroSystem SDK tools.
5. Replace **both** `giratina.nsbmd` and `giratina.nsbca`. Replace
   `giratina.nsbta` too if you exported an `.ita`, otherwise keep the original.
6. Open the new `.nsbmd` in apicula's viewer before building. If apicula cannot
   render it, the game will not either.
7. `make`, then test in an emulator.

[apicula]: https://github.com/scurest/apicula
[NNS Blender plugin]: https://github.com/jellees/nns-blender-plugin

## Budgets

From the title screen code:

| Resource            | Budget                                                       |
| ------------------- | ------------------------------------------------------------ |
| Title screen heap   | 256 KB (`0x40000`), shared with the portal and face models and all 2D art |
| Texture VRAM        | 128 KB (`TEXTURE_VRAM_SIZE_128K`)                            |
| Palette VRAM        | 64 KB (`PALETTE_VRAM_SIZE_64K`)                              |

Texture dimensions must be powers of two, and the format must be one the DS
understands (paletted 4, 16, or 256 colour, A3I5, A5I3, 4x4 compressed, or
direct 16-bit). A 1024x1024 RGBA texture straight out of Blender will not fit.
Keep the polygon count in the same ballpark as the original; the DS renders a
few thousand polygons per frame in total.

Other scenes set up their own 3D state with different sizes. Look for the
`G3DPipeline_Init` or `Easy3D_Init` call in the application you are targeting.

## Debugging a black screen

- Build with `make debug` and add `EmulatorLog` calls after each load to print
  the model's node and material counts (`model->info.numNode`,
  `model->info.numMat`) and compare them with what the animation expects. See
  [Logging](logging.md).
- To prove a model displays before the animation is right, temporarily skip
  the `.nsbca` binding in the loader and leave the animation state disabled.
- GDB with the overlay-aware `binutils-gdb-nds` fork (see `INSTALL.md`) will
  show exactly where the ARM9 stopped.
