# ABOUTME: The mapedit Textual app: browse map headers, view a block's tile grid with props and events, and edit props.
# ABOUTME: Every write is a map_props Change shown for confirmation first; the app never edits repo files itself.

import argparse
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from . import maps

MARKER_PRIORITY = ['prop', 'warp', 'npc', 'sign', 'trigger']
MARKER_SYMBOLS = {'prop': 'P', 'warp': 'W', 'npc': 'N', 'sign': 'S', 'trigger': 'T'}
MARKER_STYLES = {'prop': 'bold magenta', 'warp': 'bold red', 'npc': 'bold cyan', 'sign': 'bold yellow', 'trigger': 'bold green'}
TILE_STYLES = {
    maps.TILE_WALKABLE: 'grey50',
    maps.TILE_BLOCKED: 'grey30',
    maps.TILE_WATER: 'blue',
    maps.TILE_DOOR: 'yellow',
    maps.TILE_SPECIAL: 'green',
}
LEGEND = ('. walkable  # blocked  ~ water  D door  + special    '
          'P prop  W warp  N npc  S sign  T trigger')


def format_number(value: float) -> str:
    return maps.map_props.format_number(value)


class BlockGrid(Widget):
    """A block's 32x32 tiles, two columns per tile, with markers drawn over the tiles they stand on."""

    DEFAULT_CSS = """
    BlockGrid { width: 66; height: 34; border: round $primary; }
    BlockGrid:focus { border: round $accent; }
    """

    can_focus = True

    BINDINGS = [
        Binding('up', 'cursor(0, -1)', 'Up', show=False),
        Binding('down', 'cursor(0, 1)', 'Down', show=False),
        Binding('left', 'cursor(-1, 0)', 'Left', show=False),
        Binding('right', 'cursor(1, 0)', 'Right', show=False),
    ]

    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    class CursorMoved(Message):
        """Posted whenever the cursor moves to another tile."""

    def __init__(self, view: maps.MapView, block, **kwargs):
        super().__init__(**kwargs)
        self.view = view
        self.load_block(block)

    def load_block(self, block):
        self.block = block
        self.tiles = self.view.tiles(block)
        self.refresh_markers()
        self.cursor = (block.base_x + maps.BLOCK_TILES // 2, block.base_z + maps.BLOCK_TILES // 2)

    def refresh_markers(self):
        self.markers = {}
        for marker in self.view.markers(self.block):
            self.markers.setdefault((maps.tile_of(marker.x), maps.tile_of(marker.z)), []).append(marker)
        self.refresh()

    def top_marker(self, x: int, z: int):
        here = self.markers.get((x, z), [])
        return min(here, key=lambda m: MARKER_PRIORITY.index(m.kind)) if here else None

    def symbol_at(self, x: int, z: int) -> str:
        marker = self.top_marker(x, z)
        if marker is not None:
            return MARKER_SYMBOLS[marker.kind]
        return maps.TILE_SYMBOLS[self.tile(x, z).kind]

    def tile(self, x: int, z: int) -> maps.Tile:
        return self.tiles[z - self.block.base_z][x - self.block.base_x]

    def clamp(self, x: int, z: int) -> tuple[int, int]:
        last = maps.BLOCK_TILES - 1
        return (min(max(x, self.block.base_x), self.block.base_x + last),
                min(max(z, self.block.base_z), self.block.base_z + last))

    def validate_cursor(self, cursor: tuple[int, int]) -> tuple[int, int]:
        return self.clamp(*cursor)

    def watch_cursor(self):
        self.refresh()
        self.post_message(self.CursorMoved())

    def render(self) -> Text:
        text = Text()
        for row in self.tiles:
            for tile in row:
                marker = self.top_marker(tile.x, tile.z)
                style = MARKER_STYLES[marker.kind] if marker else TILE_STYLES[tile.kind]
                if (tile.x, tile.z) == self.cursor:
                    style += ' reverse'
                text.append(self.symbol_at(tile.x, tile.z) + ' ', style=style)
            text.append('\n')
        return text

    def action_cursor(self, dx: int, dz: int):
        x, z = self.cursor
        self.cursor = (x + dx, z + dz)

    def on_click(self, event: Click):
        self.cursor = (self.block.base_x + event.x // 2, self.block.base_z + event.y)


class BrowserScreen(Screen):
    BINDINGS = [Binding('escape', 'app.quit', 'Quit')]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder='Search map headers, e.g. "twinleaf town"', id='search')
        yield OptionList(id='maps')
        yield Footer()

    def on_mount(self):
        self.show(self.app.repository.headers())
        self.query_one('#search', Input).focus()

    def show(self, headers: list[str]):
        options = self.query_one('#maps', OptionList)
        options.clear_options()
        options.add_options([Option(header, id=header) for header in headers])
        if headers:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed):
        self.show(self.app.repository.search(event.value))

    def on_input_submitted(self, event: Input.Submitted):
        options = self.query_one('#maps', OptionList)
        if options.highlighted is not None:
            self.app.open_map(options.get_option_at_index(options.highlighted).id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.app.open_map(event.option.id)


class MapScreen(Screen):
    BINDINGS = [
        Binding('escape', 'back', 'Maps'),
        Binding('left_square_bracket', 'block(-1)', 'Prev block'),
        Binding('right_square_bracket', 'block(1)', 'Next block'),
        Binding('a', 'add', 'Add prop'),
        Binding('m', 'move', 'Move prop here'),
        Binding('d', 'delete', 'Delete prop'),
        Binding('r', 'register', 'Register prop'),
    ]

    DEFAULT_CSS = """
    #side { width: 1fr; padding: 0 1; }
    #tile-info { height: auto; margin-bottom: 1; }
    #props { height: 1fr; }
    #legend { height: 1; color: $text-muted; }
    """

    def __init__(self, view: maps.MapView):
        super().__init__()
        self.view = view
        self.block_index = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield BlockGrid(self.view, self.view.blocks[0], id='grid')
            with Vertical(id='side'):
                yield Static(id='block-info')
                yield Static(id='tile-info')
                yield DataTable(id='props', cursor_type='row', zebra_stripes=True)
        yield Static(LEGEND, id='legend')
        yield Footer()

    def on_mount(self):
        self.title = self.view.header
        table = self.query_one('#props', DataTable)
        table.add_columns('id', 'model', 'x', 'y', 'z', 'scale')
        self.refresh_block()
        self.grid.focus()

    @property
    def grid(self) -> BlockGrid:
        return self.query_one(BlockGrid)

    def refresh_block(self):
        block = self.grid.block
        self.query_one('#block-info', Static).update(
            f'{block.name}  (block {self.block_index + 1} of {len(self.view.blocks)}, {block.extent()})\n'
            f'{self.view.area} → {self.view.model_set} ({len(self.view.models)} models)')
        self.grid.refresh_markers()
        table = self.query_one('#props', DataTable)
        selected = table.cursor_row
        table.clear()
        for row in self.view.props(block):
            table.add_row(row.prop_id, row.model, format_number(row.x), format_number(row.y),
                          format_number(row.z), format_number(row.scale), key=row.prop_id)
        if table.row_count:
            table.move_cursor(row=min(selected, table.row_count - 1))
        self.describe_cursor()

    def on_block_grid_cursor_moved(self, message: 'BlockGrid.CursorMoved'):
        self.describe_cursor()

    def describe_cursor(self):
        grid = self.grid
        x, z = grid.cursor
        tile = grid.tile(x, z)
        lines = [f'tile ({x}, {z})  {tile.kind}{"  collision" if tile.collision else ""}', f'  {tile.behavior_name}']
        for marker in grid.markers.get((x, z), []):
            lines.append(f'  {marker.kind}: {marker.label}')
        self.query_one('#tile-info', Static).update('\n'.join(lines))

    def action_block(self, step: int):
        if len(self.view.blocks) < 2:
            return
        self.block_index = (self.block_index + step) % len(self.view.blocks)
        self.grid.load_block(self.view.blocks[self.block_index])
        self.refresh_block()

    def action_back(self):
        self.app.pop_screen()

    def selected_prop(self) -> str | None:
        table = self.query_one('#props', DataTable)
        if not table.row_count:
            self.notify('This block has no props.', severity='warning')
            return None
        return table.get_row_at(table.cursor_row)[0]

    def action_add(self):
        x, z = self.grid.cursor
        self.app.push_screen(AddPropScreen(self.view, x, z), self.after_change)

    def action_move(self):
        prop_id = self.selected_prop()
        if prop_id is None:
            return
        x, z = self.grid.cursor
        self.confirm(lambda: maps.map_props.move_prop(self.view.context, self.view.header, prop_id, x=x, z=z))

    def action_delete(self):
        prop_id = self.selected_prop()
        if prop_id is None:
            return
        self.confirm(lambda: maps.map_props.remove_prop(self.view.context, self.view.header, prop_id))

    def action_register(self):
        from .register import RegisterPropScreen
        self.app.push_screen(RegisterPropScreen(self.view), self.after_register)

    def confirm(self, make_change):
        try:
            change = make_change()
        except maps.map_props.MapPropError as error:
            self.notify('\n'.join(error.errors), severity='error', timeout=10)
            return
        self.app.push_screen(ConfirmScreen(change), self.after_change)

    def after_change(self, applied: bool | None):
        if applied:
            self.refresh_block()

    def after_register(self, applied: bool | None):
        if applied:
            self.view = self.app.repository.load(self.view.header)
            self.grid.view = self.view
            self.refresh_block()


class ChangeDialog(ModalScreen[bool]):
    """Shared layout for dialogs that preview a change before applying it."""

    BINDINGS = [Binding('escape', 'cancel', 'Cancel')]

    DEFAULT_CSS = """
    ChangeDialog { align: center middle; }
    ChangeDialog > Vertical { width: 90; height: auto; max-height: 90%; border: round $primary; background: $surface; padding: 1 2; }
    ChangeDialog Horizontal { height: auto; margin-top: 1; }
    ChangeDialog Button { margin-right: 2; }
    ChangeDialog Input, ChangeDialog Select { margin-bottom: 1; }
    ChangeDialog .preview { height: auto; max-height: 10; margin-top: 1; }
    """

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'cancel':
            self.dismiss(False)


class ConfirmScreen(ChangeDialog):
    def __init__(self, change):
        super().__init__()
        self.change = change

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label('Apply this change?')
            with VerticalScroll(classes='preview'):
                yield Static(describe_change(self.change), id='summary')
            with Horizontal():
                yield Button('Apply', id='apply', variant='primary')
                yield Button('Cancel', id='cancel')

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'apply':
            self.change.apply()
            self.dismiss(True)
        else:
            super().on_button_pressed(event)


def describe_change(change) -> str:
    lines = [change.summary, f'  in {change.path.name}']
    lines += [f'  warning: {warning}' for warning in change.warnings]
    return '\n'.join(lines)


class AddPropScreen(ChangeDialog):
    def __init__(self, view: maps.MapView, x: int, z: int):
        super().__init__()
        self.view = view
        self.x, self.z = x, z
        self.models = list(view.models)
        self.change = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f'Add a prop at tile ({self.x}, {self.z}) — models in {self.view.model_set}')
            yield Select([(model, model) for model in self.models], prompt='Model', id='model')
            yield Input(placeholder='Height in tiles (blank: ground)', id='y')
            yield Input(value='1', placeholder='Scale', id='scale')
            with Horizontal():
                yield Button('Preview', id='preview')
                yield Button('Apply', id='apply', variant='primary', disabled=True)
                yield Button('Cancel', id='cancel')
            with VerticalScroll(classes='preview'):
                yield Static('Choose a model, then Preview.', id='preview-text')

    def on_select_changed(self):
        self.invalidate()

    def on_input_changed(self):
        self.invalidate()

    def invalidate(self):
        self.change = None
        if self.is_mounted:
            self.query_one('#apply', Button).disabled = True

    def build_change(self):
        model = self.query_one('#model', Select).value
        if model == Select.NULL:
            raise maps.map_props.MapPropError(['choose a model'])
        errors = []
        y_text = self.query_one('#y', Input).value.strip()
        scale_text = self.query_one('#scale', Input).value.strip()
        y = scale = None
        try:
            y = float(y_text) if y_text else None
        except ValueError:
            errors.append('height must be a number, or blank for the ground')
        try:
            scale = float(scale_text)
        except ValueError:
            errors.append('scale must be a number')
        if errors:
            raise maps.map_props.MapPropError(errors)
        return maps.map_props.add_prop(self.view.context, self.view.header, model, self.x, self.z, y, scale)

    def on_button_pressed(self, event: Button.Pressed):
        preview = self.query_one('#preview-text', Static)
        if event.button.id == 'preview':
            try:
                self.change = self.build_change()
            except maps.map_props.MapPropError as error:
                self.change = None
                preview.update('\n'.join(f'error: {message}' for message in error.errors))
                self.query_one('#apply', Button).disabled = True
                return
            preview.update(describe_change(self.change))
            self.query_one('#apply', Button).disabled = False
        elif event.button.id == 'apply' and self.change is not None:
            self.change.apply()
            self.dismiss(True)
        else:
            super().on_button_pressed(event)


class MapEditApp(App):
    TITLE = 'mapedit'

    def __init__(self, root: Path = maps.REPO):
        super().__init__()
        self.repository = maps.MapRepository(root)

    def on_mount(self):
        self.push_screen(BrowserScreen())

    def open_map(self, header: str):
        try:
            view = self.repository.load(header)
        except (maps.map_props.MapPropError, KeyError, FileNotFoundError) as error:
            self.notify(f'cannot open {header}: {error}', severity='error')
            return
        if not view.blocks:
            self.notify(f'{header} has no land data blocks', severity='warning')
            return
        self.push_screen(MapScreen(view))


def main():
    parser = argparse.ArgumentParser(description='Terminal UI for browsing maps and placing map props.')
    parser.add_argument('--root', type=Path, default=maps.REPO, help='repository root (default: this checkout)')
    args = parser.parse_args()
    MapEditApp(args.root).run()


if __name__ == '__main__':
    main()
