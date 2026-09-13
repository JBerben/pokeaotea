# Editing map headers

[maps.md](maps.md) describes what a map header is. This page is the practical
companion: where the table lives, how header IDs are numbered, what each field
points at, and which file to open depending on what you want to change.
Twinleaf Town is used as the worked example.

## Where the table lives

The whole table is one C array in `include/data/map_headers.h`, compiled into
the ARM9 binary through `src/map_header.c`. It is not a resource file, so a
plain `make` picks up edits.

The struct is defined in `include/map_header.h`:

```c
typedef struct MapHeader {
    u8 areaDataArchiveID;
    u8 preloadedMapObjectsArchiveID;
    u16 mapMatrixID;
    u16 scriptsArchiveID;
    u16 initScriptsArchiveID;
    u16 msgArchiveID;
    u16 dayMusicID;
    u16 nightMusicID;
    u16 wildEncountersArchiveID;
    u16 eventsArchiveID;
    u16 mapLabelTextID : 8;
    u16 mapLabelWindowID : 8;
    u8 weather;
    u8 cameraType;
    u16 mapType : 7;
    u16 battleBG : 5;
    u16 isBikeAllowed : 1;
    u16 isRunningAllowed : 1;
    u16 isEscapeRopeAllowed : 1;
    u16 isFlyAllowed : 1;
} MapHeader;
```

## Header IDs

Header IDs are generated from `generated/map_headers.txt`. The file is a plain
list of names, zero-indexed, so the ID of a header is its line number minus
one. `MAP_HEADER_TWINLEAF_TOWN` is on line 412 and is therefore header 411.
Always refer to a header by its constant in C, scripts, and JSON; the number
only matters when reading save data or tool output.

## Worked example: Twinleaf Town

```c
[MAP_HEADER_TWINLEAF_TOWN] = {
    .areaDataArchiveID = area_data_006,
    .preloadedMapObjectsArchiveID = 0x0,
    .mapMatrixID = map_matrix_000,
    .scriptsArchiveID = scripts_twinleaf_town,
    .initScriptsArchiveID = scripts_init_twinleaf_town,
    .msgArchiveID = TEXT_BANK_TWINLEAF_TOWN,
    .dayMusicID = SEQ_TOWN01_D_sseq,
    .nightMusicID = SEQ_TOWN01_N_sseq,
    .wildEncountersArchiveID = encounters_twinleaf_town,
    .eventsArchiveID = events_twinleaf_town,
    .mapLabelTextID = LocationNames_Text_TwinleafTown,
    .mapLabelWindowID = MAP_LABEL_WINDOW_TOWN,
    .weather = OVERWORLD_WEATHER_CLEAR,
    .cameraType = CAMERA_TYPE_DEFAULT,
    .mapType = MAP_TYPE_TOWN_CITY,
    .battleBG = BACKGROUND_CITY,
    .isBikeAllowed = TRUE,
    .isRunningAllowed = TRUE,
    .isEscapeRopeAllowed = FALSE,
    .isFlyAllowed = TRUE,
},
```

Every value is a symbolic reference into a NARC (from a generated `.naix`
header), a text bank, or an enum. The includes at the top of
`include/data/map_headers.h` show where each namespace comes from.

## What to open for a given change

| To change                                   | Edit                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------- |
| Music, weather, camera, map type, battle background, bike/run/fly/rope flags | The header entry itself |
| Textures, map props, lighting               | `res/field/area_data/area_data_NNN.json` named by `areaDataArchiveID` (see [maps.md](maps.md)) |
| Position of the map in the overworld        | `res/field/matrices/map_matrix_NNN.json` named by `mapMatrixID`; the overworld is `map_matrix_000` |
| NPCs, warps, signs, triggers                | `res/field/events/events_<map>.json` named by `eventsArchiveID`       |
| Scripts                                     | `res/field/scripts/scripts_<map>.s` and `scripts_init_<map>.s`        |
| Dialogue text                               | The bank named by `msgArchiveID` under `res/text/`                    |
| Wild encounters                             | `res/field/encounters/`, member named by `wildEncountersArchiveID`    |
| Name shown in the map popup                 | The location names text bank (`mapLabelTextID`)                       |
| Frame style of the map popup                | `mapLabelWindowID`, an `enum MapLabelWindowID` value in `include/data/map_headers.h` |

## Adding a new map header

1. Append a name to `generated/map_headers.txt`. Appending keeps existing IDs
   stable; inserting in the middle renumbers everything after it, which
   breaks saves and any tool output that used raw numbers.
2. Add an entry to the array in `include/data/map_headers.h` using the new
   constant as the designator.
3. Create or reuse the resources it points to: area data, a matrix cell,
   events, scripts, a text bank, encounters.
4. Reference it from wherever the player can reach it: a warp in another map's
   events file, a matrix cell, or a spawn location.

## Renaming a header

The constant is referenced from C as well as data. Known C users include
`src/spawn_locations.c`, `src/location.c`, and `src/tv_segment.c`; data users
include the overworld matrix and the event files of any map that warps there.
Search for the constant across `src/`, `include/`, and `res/` before renaming.
Changing an entry's fields does not require touching any of those.
