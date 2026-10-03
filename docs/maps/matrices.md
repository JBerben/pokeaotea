# Map matrices

A map matrix is a grid of 32x32-tile blocks. Each cell holds:

- **land data**: `MAP_NNN`, the block's `res/field/maps/data/map_data_NNN.bin`
  (collision, model, heights, props), or `MAP_NONE` for no block;
- **altitude** (optional): the block's base height, in half tiles;
- **header** (only in matrices with per-cell headers): the map that owns the cell.

The game picks the current map from the cell the player stands in
(`MapMatrix_GetMapHeaderIDAtCoords`). The overworld, `map_matrix_000`, has
per-cell headers: every town and route is the set of cells that name it. Most
other matrices have none and belong to whichever headers point at them through
`.mapMatrixID` - every Poké Mart shares one, for example.

## Editing

`tools/scripts/map_matrices.py` views and edits matrices; every edit is planned
first, `--dry-run` shows the plan, and `--json` gives machine-readable output.

```bash
python3 tools/scripts/map_matrices.py show MAP_HEADER_ETERNA_FOREST
python3 tools/scripts/map_matrices.py set map_matrix_000 --cell 27,3 --header MAP_HEADER_ROUTE_201 --dry-run
python3 tools/scripts/map_matrices.py set map_matrix_000 --rect 5,8:6,9 --altitude 2
python3 tools/scripts/map_matrices.py unshare map_matrix_122 --cell 0,0
python3 tools/scripts/map_matrices.py users MAP_177
```

Cells are `row,col` from the top left. The same edits are in mapedit's matrix
editor (`x` on a map or on a map in the browser's list).

- **Land data is often shared.** The overworld reuses filler blocks (sea,
  mountains) in dozens of cells, and interiors of the same kind share one file.
  Editing a shared file changes every cell that uses it; `set --land` warns, and
  `unshare` gives a cell its own copy (a new `map_data_NNN.bin`, registered in
  `meson.build`, `map_data.order` and `generated/maps.txt`).
- **The overworld cannot grow.** It is 30x30, the engine maximum
  (`MAP_MATRIX_MAX_WIDTH`/`HEIGHT`). New overworld areas take over existing
  cells: 432 are `MAP_NONE`, and 299 hold filler land data owned by
  `MAP_HEADER_EVERYWHERE`. A block must line up with its neighbours, because the
  game streams adjacent blocks as you walk.
- **Single-header matrices have no cell headers to set.** To give a map its own
  matrix, use `new_map.py --header --own-matrix` (see
  [the tooling docs](../scripting/tooling.md#new_mappy)).
- **Matrix numbers are stored in a u8.** A new matrix numbered a multiple of
  256 would read as 0, the overworld, to code such as
  `MapMatrix_RevealSpringPath`; the tools refuse to create one.
