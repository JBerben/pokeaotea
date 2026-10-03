# ABOUTME: mapedit's matrix editor: a scrolling grid of a map matrix's cells, with header, land data and altitude edits.
# ABOUTME: All edits are map_matrices.py plans, previewed before they are applied.

import zlib

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Input, Label, Static

from .app import ChangeDialog, ConfirmScreen

# tools/scripts is on sys.path via mapedit.maps, which app imports.
import map_matrices  # noqa: E402

CELL_WIDTH = 5
HEADER_COLOURS = ['red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'bright_red', 'bright_green',
                  'bright_yellow', 'bright_blue', 'bright_magenta', 'bright_cyan', 'orange1', 'purple', 'turquoise2']


def header_colour(header: str | None) -> str:
    if header is None:
        return 'white'
    return HEADER_COLOURS[zlib.crc32(header.encode()) % len(HEADER_COLOURS)]


class MatrixGrid(Widget):
    """One line per matrix row, CELL_WIDTH columns per cell: the land data number, coloured by owning header."""

    can_focus = True
    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    BINDINGS = [
        Binding('up', 'cursor(-1, 0)', 'Up', show=False),
        Binding('down', 'cursor(1, 0)', 'Down', show=False),
        Binding('left', 'cursor(0, -1)', 'Left', show=False),
        Binding('right', 'cursor(0, 1)', 'Right', show=False),
    ]

    class CursorMoved(Message):
        """Posted whenever the cursor moves to another cell."""

    def __init__(self, info: dict, **kwargs):
        super().__init__(**kwargs)
        self.load(info)

    def load(self, info: dict):
        self.info = info
        self.cells = {(c['row'], c['col']): c for c in info['cells']}
        self.styles.width = info['width'] * CELL_WIDTH
        self.styles.height = info['height']
        self.refresh()

    def cell(self, row: int, col: int) -> dict:
        return self.cells[(row, col)]

    def validate_cursor(self, cursor: tuple[int, int]) -> tuple[int, int]:
        row, col = cursor
        return (min(max(row, 0), self.info['height'] - 1), min(max(col, 0), self.info['width'] - 1))

    def watch_cursor(self):
        self.refresh()
        row, col = self.cursor
        self.scroll_visible_region(row, col)
        self.post_message(self.CursorMoved())

    def scroll_visible_region(self, row: int, col: int):
        if self.parent is not None and self.is_mounted:
            from textual.geometry import Region
            self.parent.scroll_to_region(Region(col * CELL_WIDTH, row, CELL_WIDTH, 1), animate=False)

    def action_cursor(self, d_row: int, d_col: int):
        row, col = self.cursor
        self.cursor = (row + d_row, col + d_col)

    def render(self) -> Text:
        text = Text()
        for row in range(self.info['height']):
            for col in range(self.info['width']):
                cell = self.cell(row, col)
                if cell['land'] == map_matrices.MAP_NONE:
                    label, style = ' -- ', 'grey37'
                else:
                    label, style = cell['land'].removeprefix('MAP_').rjust(4), header_colour(cell['header'])
                if (row, col) == self.cursor:
                    style += ' reverse'
                text.append(label + ' ', style=style)
            text.append('\n')
        return text

    def on_click(self, event):
        self.cursor = (event.y, event.x // CELL_WIDTH)


class MatrixScreen(Screen):
    BINDINGS = [
        Binding('escape', 'back', 'Back'),
        Binding('h', 'set("header")', 'Header'),
        Binding('l', 'set("land")', 'Land data'),
        Binding('a', 'set("altitude")', 'Altitude'),
        Binding('u', 'unshare', 'Unshare'),
        Binding('enter', 'open_map', 'Open map'),
    ]

    DEFAULT_CSS = """
    #grid-scroll { width: 2fr; border: round $primary; }
    #side { width: 1fr; padding: 0 1; }
    """

    def __init__(self, matrix_id: str, cursor: tuple[int, int] = (0, 0)):
        super().__init__()
        self.matrix_id = matrix_id
        self.start_cursor = cursor
        self.changed = False

    @property
    def root(self):
        return self.app.repository.root

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with ScrollableContainer(id='grid-scroll'):
                yield MatrixGrid(map_matrices.describe_matrix(self.root, self.matrix_id), id='grid')
            with Vertical(id='side'):
                yield Static(id='cell-info')
                yield Static(id='matrix-info')
        yield Footer()

    def on_mount(self):
        self.title = self.matrix_id
        grid = self.query_one(MatrixGrid)
        grid.cursor = self.start_cursor
        grid.focus()
        self.describe()

    def describe(self):
        grid = self.query_one(MatrixGrid)
        info = grid.info
        if info['single_header']:
            kind = f"single-header, owned by {', '.join(info['owners']) or 'no header'}"
        else:
            # The overworld matrix is pointed at by ~150 headers; listing them would bury the cell details.
            kind = f"per-cell headers; {len(info['owners'])} map header(s) point at this matrix"
        self.query_one('#matrix-info', Static).update(
            f"\n{info['id']}  {info['width']}x{info['height']}  name {info['name']!r}\n{kind}")

        row, col = grid.cursor
        cell = grid.cell(row, col)
        lines = [f'cell {row},{col}']
        lines.append(f"  header   {cell['header'] or '(the matrix owner)'}")
        lines.append(f"  land     {cell['land']}")
        lines.append(f"  altitude {cell['altitude'] if cell['altitude'] is not None else '(none)'}")
        if cell['land'] != map_matrices.MAP_NONE:
            users = map_matrices.land_users(self.root, cell['land'])
            others = len(users) - 1
            lines.append(f"  {cell['land']} is also used by {others} other cell(s)" if others else
                         f"  {cell['land']} is used only here")
        self.query_one('#cell-info', Static).update('\n'.join(lines))

    def on_matrix_grid_cursor_moved(self):
        if self.is_mounted:
            self.describe()

    def reload(self):
        grid = self.query_one(MatrixGrid)
        grid.load(map_matrices.describe_matrix(self.root, self.matrix_id))
        self.describe()

    def action_set(self, field: str):
        row, col = self.query_one(MatrixGrid).cursor
        self.app.push_screen(MatrixValueScreen(self.root, self.matrix_id, row, col, field), self.after_change)

    def action_unshare(self):
        row, col = self.query_one(MatrixGrid).cursor
        try:
            change = map_matrices.unshare_cell(self.root, self.matrix_id, row, col)
        except map_matrices.MatrixError as error:
            self.notify('\n'.join(error.errors), severity='error', timeout=10)
            return
        self.app.push_screen(ConfirmScreen(change), self.after_change)

    def after_change(self, applied: bool | None):
        if applied:
            self.changed = True
            self.app.reload_repository()
            self.reload()

    def action_open_map(self):
        grid = self.query_one(MatrixGrid)
        cell = grid.cell(*grid.cursor)
        header = cell['header'] or (grid.info['owners'][0] if grid.info['owners'] else None)
        if header is None or cell['land'] == map_matrices.MAP_NONE:
            self.notify('This cell has no map to open.', severity='warning')
            return
        self.app.open_map(header)

    def action_back(self):
        self.dismiss(self.changed)


class MatrixValueScreen(ChangeDialog):
    PROMPTS = {
        'header': 'Header for the cell, e.g. MAP_HEADER_ROUTE_201',
        'land': 'Land data for the cell, e.g. MAP_177, or MAP_NONE for no block',
        'altitude': 'Altitude, 0-255',
    }

    def __init__(self, root, matrix_id: str, row: int, col: int, field: str):
        super().__init__()
        self.root, self.matrix_id, self.row, self.col, self.field = root, matrix_id, row, col, field
        self.change = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f'Set the {self.field} of cell {self.row},{self.col} in {self.matrix_id}')
            yield Input(placeholder=self.PROMPTS[self.field], id='value')
            with Horizontal():
                yield Button('Preview', id='preview')
                yield Button('Apply', id='apply', variant='primary', disabled=True)
                yield Button('Cancel', id='cancel')
            with VerticalScroll(classes='preview'):
                yield Static('Enter a value, then Preview.', id='preview-text')

    def on_input_changed(self):
        self.change = None
        if self.is_mounted:
            self.query_one('#apply', Button).disabled = True

    def build_change(self):
        value = self.query_one('#value', Input).value.strip()
        arguments = {}
        if self.field == 'altitude':
            try:
                arguments['altitude'] = int(value)
            except ValueError:
                raise map_matrices.MatrixError(['altitude must be a whole number'])
        else:
            arguments[self.field] = value
        return map_matrices.set_cells(self.root, self.matrix_id, [(self.row, self.col)], **arguments)

    def on_button_pressed(self, event: Button.Pressed):
        preview = self.query_one('#preview-text', Static)
        if event.button.id == 'preview':
            try:
                self.change = self.build_change()
            except map_matrices.MatrixError as error:
                self.change = None
                preview.update('\n'.join(f'error: {message}' for message in error.errors))
                self.query_one('#apply', Button).disabled = True
                return
            lines = [self.change.summary] + self.change.lines() + [f'  warning: {w}' for w in self.change.warnings]
            preview.update('\n'.join(lines))
            self.query_one('#apply', Button).disabled = False
        elif event.button.id == 'apply' and self.change is not None:
            self.change.apply()
            self.dismiss(True)
        else:
            super().on_button_pressed(event)
