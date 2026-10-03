#!/usr/bin/env python3
# ABOUTME: Views and edits map matrices (res/field/matrices) and adds land data files, as a library and a CLI.
# ABOUTME: Every operation builds a plan of file edits first; nothing is written until it is applied.

"""View and edit map matrices, and add land data.

    python3 tools/scripts/map_matrices.py show MAP_HEADER_ETERNA_FOREST
    python3 tools/scripts/map_matrices.py show map_matrix_000 --json
    python3 tools/scripts/map_matrices.py set map_matrix_000 --cell 27,3 --header MAP_HEADER_ROUTE_201 --dry-run
    python3 tools/scripts/map_matrices.py set map_matrix_000 --rect 5,8:6,9 --altitude 2
    python3 tools/scripts/map_matrices.py unshare map_matrix_122 --cell 0,0
    python3 tools/scripts/map_matrices.py users MAP_177

A matrix is a grid of blocks. Each cell names a land data file (MAP_NNN, or
MAP_NONE for no block), optionally an altitude, and - in matrices with per-cell
headers such as the overworld (map_matrix_000) - the map header that owns it.
The game picks the current map from that cell (MapMatrix_GetMapHeaderIDAtCoords).
A matrix without per-cell headers belongs to whichever headers point at it.

Cells are addressed as row,col from the top left. `unshare` copies a cell's land
data to a new file so it can be edited without changing every other cell (or
matrix) that uses the same file. Add --json for machine-readable output.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATRICES = Path('res/field/matrices')
LAND_DATA = Path('res/field/maps/data')
MAP_HEADERS_H = Path('include/data/map_headers.h')
MAP_HEADERS_TXT = Path('generated/map_headers.txt')
MAPS_TXT = Path('generated/maps.txt')

MAP_NONE = 'MAP_NONE'
MAX_SIDE = 30               # MAP_MATRIX_MAX_WIDTH / MAP_MATRIX_MAX_HEIGHT
MATRIX_ID_WRAP = 256        # MapMatrix.matrixID is a u8
MATRIX_LIST_ANCHOR = 'matrix_data_srcs = files('
LAND_DATA_LIST_ANCHOR = 'map_data_files = copy_gen.process(files('


class MatrixError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__('\n'.join(errors))
        self.errors = errors


@dataclass
class Matrix:
    id: str
    name: str
    headers: list
    altitudes: list
    maps: list

    @property
    def height(self) -> int:
        return len(self.maps)

    @property
    def width(self) -> int:
        return len(self.maps[0]) if self.maps else 0

    @property
    def single_header(self) -> bool:
        return not self.headers

    def contains(self, row: int, col: int) -> bool:
        return 0 <= row < self.height and 0 <= col < self.width


def format_matrix(matrix: Matrix) -> str:
    """The JSON layout every retail matrix uses: one row per line."""
    lines = ['{', f'    "name": {json.dumps(matrix.name)},']
    grids = [('headers', matrix.headers), ('altitudes', matrix.altitudes), ('maps', matrix.maps)]
    for index, (key, rows) in enumerate(grids):
        comma = ',' if index < len(grids) - 1 else ''
        if not rows:
            lines.append(f'    "{key}": []{comma}')
            continue
        lines.append(f'    "{key}": [')
        lines += [f'        {json.dumps(row)}' + (',' if i < len(rows) - 1 else '') for i, row in enumerate(rows)]
        lines.append(f'    ]{comma}')
    return '\n'.join(lines + ['}']) + '\n'


def parse_matrix(matrix_id: str, text: str) -> Matrix:
    data = json.loads(text)
    return Matrix(matrix_id, data['name'], data['headers'], data['altitudes'], data['maps'])


def read_matrix(root: Path, matrix_id: str) -> Matrix:
    path = root / MATRICES / f'{matrix_id}.json'
    if not path.exists():
        raise MatrixError([f'no matrix {matrix_id} in {MATRICES.as_posix()}'])
    return parse_matrix(matrix_id, path.read_text(encoding='utf-8'))


def matrix_ids(root: Path) -> list[str]:
    return (root / MATRICES / 'map_matrices.order').read_text(encoding='utf-8').split()


def header_matrices(root: Path) -> dict[str, str]:
    """map header -> the matrix it points at."""
    text = (root / MAP_HEADERS_H).read_text(encoding='utf-8')
    return dict(re.findall(r'\[(MAP_HEADER_\w+)\]\s*=\s*\{[^}]*?\.mapMatrixID\s*=\s*(\w+)', text))


def resolve_matrix(root: Path, name: str) -> str:
    if name.startswith('MAP_HEADER_'):
        matrix_id = header_matrices(root).get(name)
        if matrix_id is None:
            raise MatrixError([f'no {name} in {MAP_HEADERS_H.as_posix()}'])
        return matrix_id
    return name


def owners(root: Path, matrix_id: str) -> list[str]:
    return sorted(header for header, matrix in header_matrices(root).items() if matrix == matrix_id)


def describe_matrix(root: Path, matrix_id: str) -> dict:
    matrix = read_matrix(root, matrix_id)
    cells = []
    for row in range(matrix.height):
        for col in range(matrix.width):
            cells.append({
                'row': row,
                'col': col,
                'header': matrix.headers[row][col] if matrix.headers else None,
                'land': matrix.maps[row][col],
                'altitude': matrix.altitudes[row][col] if matrix.altitudes else None,
            })
    return {
        'id': matrix.id,
        'name': matrix.name,
        'width': matrix.width,
        'height': matrix.height,
        'single_header': matrix.single_header,
        'owners': owners(root, matrix_id),
        'cells': cells,
    }


def land_users(root: Path, land: str) -> list[tuple[str, int, int]]:
    users = []
    for matrix_id in matrix_ids(root):
        matrix = read_matrix(root, matrix_id)
        for row, maps in enumerate(matrix.maps):
            for col, value in enumerate(maps):
                if value == land:
                    users.append((matrix_id, row, col))
    return users


@dataclass
class FileEdit:
    path: Path          # relative to the repo root
    description: str
    content: bytes
    created: bool


class Workspace:
    """Pending edits to a repo, readable as if they were already applied."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.edits: dict[Path, FileEdit] = {}

    def read_bytes(self, relative: Path) -> bytes:
        relative = Path(relative)
        if relative in self.edits:
            return self.edits[relative].content
        return (self.root / relative).read_bytes()

    def read_text(self, relative: Path) -> str:
        return self.read_bytes(relative).decode('utf-8')

    def exists(self, relative: Path) -> bool:
        return Path(relative) in self.edits or (self.root / relative).exists()

    def write(self, relative: Path, content: bytes | str, description: str):
        relative = Path(relative)
        if isinstance(content, str):
            content = content.encode('utf-8')
        previous = self.edits.get(relative)
        created = previous.created if previous else not (self.root / relative).exists()
        if previous and previous.description != description:
            description = f'{previous.description}; {description}'
        self.edits[relative] = FileEdit(relative, description, content, created)

    def lines(self) -> list[str]:
        edits = sorted(self.edits.values(), key=lambda e: (not e.created, e.path.as_posix()))
        return [f"  {'create' if e.created else 'edit  '}  {e.path.as_posix()}  ({e.description})" for e in edits]

    def apply(self):
        for edit in self.edits.values():
            target = self.root / edit.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(edit.content)


@dataclass
class Change:
    workspace: Workspace
    summary: str
    warnings: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        return self.workspace.lines()

    def apply(self):
        self.workspace.apply()


def append_to_list(text: str, anchor: str, entry: str) -> str:
    """Adds `    'entry',` as the last item of the files() list opened by anchor, fixing a missing comma."""
    start = text.index(anchor)
    close = text.index('\n)', start)
    before = text[:close].rstrip()
    if not before.endswith((',', '(')):
        before += ','
    return before + f"\n    '{entry}'," + text[close:]


def map_names(workspace: Workspace) -> list[str]:
    return [line.split('=')[0].strip() for line in workspace.read_text(MAPS_TXT).splitlines() if line.strip()]


def known_headers(root: Path) -> set[str]:
    return {line.split('=')[0].strip() for line in (root / MAP_HEADERS_TXT).read_text(encoding='utf-8').splitlines()
            if line.strip().startswith('MAP_HEADER_')}


def add_land_data(workspace: Workspace, source: str) -> str:
    """Copies a land data file to a new one and registers it; returns the new MAP_NNN."""
    names = map_names(workspace)
    numbered = [name for name in names if name != MAP_NONE]
    order = workspace.read_text(LAND_DATA / 'map_data.order').split()
    if len(numbered) != len(order):
        raise MatrixError([f'{MAPS_TXT.as_posix()} lists {len(numbered)} land data files but map_data.order has {len(order)}'])

    number = len(numbered)
    new_name, new_file = f'MAP_{number:03}', f'map_data_{number:03}.bin'
    source_file = LAND_DATA / f'map_data_{source.removeprefix("MAP_")}.bin'

    workspace.write(LAND_DATA / new_file, workspace.read_bytes(source_file), f'copy of {source_file.name}')
    workspace.write(LAND_DATA / 'meson.build', append_to_list(workspace.read_text(LAND_DATA / 'meson.build'),
                                                              LAND_DATA_LIST_ANCHOR, new_file), f'add {new_file}')
    workspace.write(LAND_DATA / 'map_data.order', workspace.read_text(LAND_DATA / 'map_data.order').rstrip('\n')
                    + f'\n{new_file}\n', f'add {new_file}')
    maps_text = workspace.read_text(MAPS_TXT)
    workspace.write(MAPS_TXT, maps_text.replace(f'\n{MAP_NONE}', f'\n{new_name}\n{MAP_NONE}', 1), f'{new_name} before MAP_NONE')
    return new_name


def check_next_matrix_id(workspace: Workspace) -> int:
    number = len(workspace.read_text(MATRICES / 'map_matrices.order').split())
    if number % MATRIX_ID_WRAP == 0:
        raise MatrixError([f'the next matrix would be number {number}, which the game stores in a u8 as 0 - the overworld '
                           '(see MapMatrix_RevealSpringPath); add a placeholder matrix first'])
    return number


def add_matrix(workspace: Workspace, matrix: Matrix) -> str:
    """Registers a new matrix; returns its id."""
    order = workspace.read_text(MATRICES / 'map_matrices.order').split()
    number = check_next_matrix_id(workspace)
    matrix_id = f'map_matrix_{number:03}'
    matrix.id = matrix_id
    workspace.write(MATRICES / f'{matrix_id}.json', format_matrix(matrix), f'{matrix.width}x{matrix.height} matrix')
    workspace.write(MATRICES / 'meson.build', append_to_list(workspace.read_text(MATRICES / 'meson.build'),
                                                            MATRIX_LIST_ANCHOR, f'{matrix_id}.json'), f'add {matrix_id}.json')
    workspace.write(MATRICES / 'map_matrices.order', '\n'.join(order + [matrix_id]) + '\n', f'add {matrix_id}')
    return matrix_id


def template_cells(root: Path, header: str) -> tuple[Matrix, list[tuple[int, int]]]:
    """The template header's matrix and the cells it owns (with land data)."""
    matrix = read_matrix(root, resolve_matrix(root, header))
    cells = [(row, col) for row in range(matrix.height) for col in range(matrix.width)
             if matrix.maps[row][col] != MAP_NONE and (matrix.single_header or matrix.headers[row][col] == header)]
    if not cells:
        raise MatrixError([f'{header} owns no blocks in {matrix.id}'])
    return matrix, cells


def matrix_from_template(workspace: Workspace, header: str) -> str:
    """A single-header matrix copying the blocks the template header owns, each into a new land data file."""
    template, cells = template_cells(workspace.root, header)
    top, left = min(r for r, _ in cells), min(c for _, c in cells)
    bottom, right = max(r for r, _ in cells), max(c for _, c in cells)

    # Check the matrix id first, so a refusal does not leave land data half-planned.
    check_next_matrix_id(workspace)

    maps = []
    for row in range(top, bottom + 1):
        maps.append([add_land_data(workspace, template.maps[row][col]) if (row, col) in cells else MAP_NONE
                     for col in range(left, right + 1)])
    altitudes = []
    if template.altitudes:
        altitudes = [[template.altitudes[row][col] for col in range(left, right + 1)] for row in range(top, bottom + 1)]

    return add_matrix(workspace, Matrix('', template.name, [], altitudes, maps))


def parse_cell(text: str) -> tuple[int, int]:
    match = re.fullmatch(r'\s*(\d+)\s*,\s*(\d+)\s*', text)
    if not match:
        raise MatrixError([f'cell {text!r} must be row,col'])
    return int(match.group(1)), int(match.group(2))


def parse_rect(text: str) -> list[tuple[int, int]]:
    if ':' not in text:
        raise MatrixError([f'rect {text!r} must be row,col:row,col'])
    (r1, c1), (r2, c2) = (parse_cell(part) for part in text.split(':', 1))
    return [(r, c) for r in range(min(r1, r2), max(r1, r2) + 1) for c in range(min(c1, c2), max(c1, c2) + 1)]


def set_cells(root: Path, matrix_id: str, cells: list[tuple[int, int]], header: str | None = None,
              land: str | None = None, altitude: int | None = None) -> Change:
    root = Path(root)
    matrix = read_matrix(root, matrix_id)
    if header is None and land is None and altitude is None:
        raise MatrixError(['nothing to set: give a header, land data or altitude'])

    errors = [f'cell ({r}, {c}) is outside {matrix_id} ({matrix.height} rows x {matrix.width} columns)'
              for r, c in cells if not matrix.contains(r, c)]
    if header is not None:
        if matrix.single_header:
            owned = ', '.join(owners(root, matrix_id)) or 'no header'
            errors.append(f'{matrix_id} is a single-header matrix (every cell belongs to {owned}); '
                          'it has no per-cell headers to set')
        elif header not in known_headers(root):
            errors.append(f'no {header} in {MAP_HEADERS_TXT.as_posix()}')
    workspace = Workspace(root)
    if land is not None and land != MAP_NONE and land not in map_names(workspace):
        errors.append(f'no land data {land} in {MAPS_TXT.as_posix()}')
    if altitude is not None and not 0 <= altitude <= 255:
        errors.append(f'altitude {altitude} is outside 0-255')
    if errors:
        raise MatrixError(errors)

    if altitude is not None and not matrix.altitudes:
        matrix.altitudes = [[0] * matrix.width for _ in range(matrix.height)]
    for row, col in cells:
        if header is not None:
            matrix.headers[row][col] = header
        if land is not None:
            matrix.maps[row][col] = land
        if altitude is not None:
            matrix.altitudes[row][col] = altitude

    parts = [f'{name} {value}' for name, value in (('header', header), ('land', land), ('altitude', altitude)) if value is not None]
    where = f'cell {cells[0][0]},{cells[0][1]}' if len(cells) == 1 else f'{len(cells)} cells'
    summary = f'set {", ".join(parts)} on {where} of {matrix_id}'
    workspace.write(MATRICES / f'{matrix_id}.json', format_matrix(matrix), summary)

    warnings = []
    if land is not None and land != MAP_NONE:
        others = [user for user in land_users(root, land) if not (user[0] == matrix_id and (user[1], user[2]) in cells)]
        if others:
            warnings.append(f'{land} is also used by {len(others)} other cell(s); editing that land data changes them all '
                            '(unshare a cell to give it its own copy)')
    return Change(workspace, summary, warnings)


def unshare_cell(root: Path, matrix_id: str, row: int, col: int) -> Change:
    root = Path(root)
    matrix = read_matrix(root, matrix_id)
    if not matrix.contains(row, col):
        raise MatrixError([f'cell ({row}, {col}) is outside {matrix_id} ({matrix.height} rows x {matrix.width} columns)'])
    source = matrix.maps[row][col]
    if source == MAP_NONE:
        raise MatrixError([f'cell ({row}, {col}) of {matrix_id} has no land data ({MAP_NONE}) to copy'])

    workspace = Workspace(root)
    new_land = add_land_data(workspace, source)
    matrix.maps[row][col] = new_land
    summary = f'give cell {row},{col} of {matrix_id} its own copy of {source} as {new_land}'
    workspace.write(MATRICES / f'{matrix_id}.json', format_matrix(matrix), summary)
    return Change(workspace, summary)


def format_grid(info: dict) -> str:
    lines = [f"{info['id']}  ({info['width']}x{info['height']}, name {info['name']!r})"]
    if info['single_header']:
        lines.append(f"single-header matrix, owned by {', '.join(info['owners']) or 'no header'}")
    headers = sorted({c['header'] for c in info['cells'] if c['header']})
    keys = {header: chr(ord('A') + i) if i < 26 else chr(ord('a') + i - 26) if i < 52 else '?' for i, header in enumerate(headers)}
    lines.append('')
    lines.append('      ' + ''.join(f'{col:<11}' for col in range(info['width'])))
    for row in range(info['height']):
        cells = [c for c in info['cells'] if c['row'] == row]
        text = ''
        for cell in cells:
            land = '-' if cell['land'] == MAP_NONE else cell['land'].removeprefix('MAP_')
            key = keys.get(cell['header'], ' ') if cell['header'] else ' '
            altitude = '' if cell['altitude'] is None else f"^{cell['altitude']}"
            text += f'{key}{land:>4}{altitude:<6}'
        lines.append(f'{row:>4}  {text}')
    if keys:
        lines.append('')
        lines += [f'  {key} {header}' for header, key in keys.items()]
    return '\n'.join(lines)


def report_change(change: Change, applied: bool) -> dict:
    return {
        'summary': change.summary,
        'warnings': change.warnings,
        'files': [{'path': edit.path.as_posix(), 'action': 'create' if edit.created else 'edit'}
                  for edit in change.workspace.edits.values()],
        'applied': applied,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument('--root', type=Path, default=REPO, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest='command', required=True)

    show = commands.add_parser('show', help='show a matrix (by matrix id or map header)')
    show.add_argument('matrix')

    set_parser = commands.add_parser('set', help="set cells' header, land data and/or altitude")
    set_parser.add_argument('matrix')
    set_parser.add_argument('--cell', action='append', default=[], help='row,col; repeat for several')
    set_parser.add_argument('--rect', help='row,col:row,col, inclusive')
    set_parser.add_argument('--header')
    set_parser.add_argument('--land', help='MAP_NNN or MAP_NONE')
    set_parser.add_argument('--altitude', type=int)

    unshare = commands.add_parser('unshare', help="give a cell its own copy of its land data")
    unshare.add_argument('matrix')
    unshare.add_argument('--cell', required=True, help='row,col')

    users = commands.add_parser('users', help='list the cells that use a land data file')
    users.add_argument('land', help='MAP_NNN')

    for command in (show, set_parser, unshare, users):
        command.add_argument('--json', action='store_true', help='machine-readable output')
    for command in (set_parser, unshare):
        command.add_argument('--dry-run', action='store_true', help='show the plan and stop')

    args = parser.parse_args(argv)
    root = args.root

    def fail(errors: list[str]) -> int:
        if args.json:
            print(json.dumps({'errors': errors}))
        else:
            for message in errors:
                print(f'error: {message}', file=sys.stderr)
        return 1

    try:
        if args.command == 'show':
            info = describe_matrix(root, resolve_matrix(root, args.matrix))
            print(json.dumps(info) if args.json else format_grid(info))
            return 0
        if args.command == 'users':
            found = land_users(root, args.land)
            if args.json:
                print(json.dumps([{'matrix': m, 'row': r, 'col': c} for m, r, c in found]))
            else:
                print('\n'.join(f'{m} cell {r},{c}' for m, r, c in found) or f'{args.land} is not used by any matrix')
            return 0

        matrix_id = resolve_matrix(root, args.matrix)
        if args.command == 'set':
            cells = [parse_cell(cell) for cell in args.cell] + (parse_rect(args.rect) if args.rect else [])
            if not cells:
                return fail(['give at least one --cell or a --rect'])
            change = set_cells(root, matrix_id, cells, args.header, args.land, args.altitude)
        else:
            row, col = parse_cell(args.cell)
            change = unshare_cell(root, matrix_id, row, col)
    except MatrixError as error:
        return fail(error.errors)

    if not args.dry_run:
        change.apply()
    if args.json:
        print(json.dumps(report_change(change, not args.dry_run)))
    else:
        print(change.summary)
        print('\n'.join(change.lines()))
        for warning in change.warnings:
            print(f'  warning: {warning}')
        print('\nNothing written (--dry-run).' if args.dry_run else '\nDone.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
