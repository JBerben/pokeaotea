# ABOUTME: mapedit's report and scaffolding screens: map info, warp check, free flags/variables, and the new-map form.
# ABOUTME: Reports are read-only views of map_info, check_warps and find_free_state; new maps go through new_map.build_plan.

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from .app import ChangeDialog

# tools/scripts is on sys.path via mapedit.maps, which app imports.
import check_warps  # noqa: E402
import find_free_state  # noqa: E402
import map_info  # noqa: E402
import new_map  # noqa: E402

FREE_STATE_LIMIT = 30


class ReportScreen(ModalScreen):
    """A full-size read-only report that Esc closes.

    The report scripts read the checkout mapedit runs from, not MapEditApp's root;
    they never write, so that only matters to tests.
    """

    BINDINGS = [Binding('escape', 'close', 'Close')]

    DEFAULT_CSS = """
    ReportScreen { align: center middle; }
    ReportScreen > Vertical { width: 95%; height: 95%; border: round $primary; background: $surface; padding: 0 1; }
    ReportScreen VerticalScroll { height: 1fr; }
    ReportScreen Horizontal { height: auto; }
    """

    def action_close(self):
        self.dismiss(None)


class MapInfoScreen(ReportScreen):
    def __init__(self, header: str):
        super().__init__()
        self.header = header

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f'Map info: {self.header}  (Esc to close)')
            with VerticalScroll():
                yield Static(self.report(), id='report')

    def report(self) -> str:
        stem = map_info.script_stem_for_header(self.header)
        if stem is None:
            return f'{self.header} has no scripts file'
        try:
            return map_info.format_summary(map_info.summarize(stem), state=True)
        except map_info.MapInfoError as error:
            return f'{self.header}: {error}'


class WarpsScreen(ReportScreen):
    def __init__(self, events: str | None = None):
        super().__init__()
        self.events = events

    def compose(self) -> ComposeResult:
        scope = self.events or 'every map'
        with Vertical():
            with Horizontal():
                yield Label(f'Warp check: {scope}  (Esc to close)  ')
                yield Checkbox('List one-way warps', id='one-way')
            with VerticalScroll():
                yield Static(self.report(False), id='report')

    def report(self, one_way: bool) -> str:
        report = check_warps.check_warps([self.events] if self.events else None, one_way)
        lines = [f'{report.total} warp(s) checked, {len(report.findings)} finding(s)']
        if report.findings:
            lines += [''] + report.findings
        if one_way and report.one_way:
            lines += ['', f'one-way warps ({len(report.one_way)}) - legal, listed for review:']
            lines += [f'  {entry}' for entry in report.one_way]
        return '\n'.join(lines)

    def on_checkbox_changed(self, event: Checkbox.Changed):
        self.query_one('#report', Static).update(self.report(event.value))


class FreeStateScreen(ReportScreen):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label('Free flags and variables  (Esc to close)')
            yield Input(placeholder='Check a name, e.g. FLAG_UNUSED_0x0094, then Enter', id='check')
            yield Static('', id='check-result')
            with VerticalScroll():
                yield Static('Scanning the sources for flag and variable names…', id='report')

    def on_mount(self):
        self.state = None
        self.run_worker(find_free_state.scan, thread=True, name='scan')

    def on_worker_state_changed(self, event):
        if event.worker.name == 'scan' and event.worker.is_finished:
            self.state = event.worker.result
            self.query_one('#report', Static).update(self.report())

    def report(self) -> str:
        lines = []
        for summary in find_free_state.free_summary(self.state):
            lines.append(f'{summary.label}: {summary.defined} defined, {summary.reserved} in reserved ranges, '
                         f'{summary.in_use} of the remaining {summary.general} in use')
            lines.append(f'  {len(summary.free)} free to claim; first {min(FREE_STATE_LIMIT, len(summary.free))}:')
            lines += [f'    {entry.name:<52} line {entry.line}' for entry in summary.free[:FREE_STATE_LIMIT]]
            lines.append('')
        lines.append('reserved ranges - do not hand-claim names inside these:')
        for reserved in find_free_state.reserved_ranges(self.state):
            lines.append(f'  {reserved.first} .. {reserved.last}  ({reserved.count} entries)')
            lines.append(f'    {reserved.reason}')
        lines += ['', 'Claim a name by renaming it in place in generated/vars_flags.txt. Never insert or',
                  'reorder entries - position is the numeric value, and save data depends on it.']
        return '\n'.join(lines)

    def on_input_submitted(self, event: Input.Submitted):
        result = self.query_one('#check-result', Static)
        if self.state is None:
            result.update('Still scanning; try again in a moment.')
            return
        result.update(find_free_state.check_name(self.state, event.value.strip()).message)


class NewMapScreen(ChangeDialog):
    def __init__(self, root):
        super().__init__()
        self.root = root
        self.plan = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label('New map (new_map.py): scripts, text and events, wired into the build')
            yield Input(placeholder='Name, lower snake_case, e.g. route_231', id='name')
            yield Input(placeholder='Label for the placeholder message (blank: the name)', id='label')
            yield Checkbox('Also add the map header, copying geometry from the template', id='header')
            yield Input(value=new_map.DEFAULT_TEMPLATE, placeholder='Template header', id='template')
            with Horizontal():
                yield Button('Preview', id='preview')
                yield Button('Apply', id='apply', variant='primary', disabled=True)
                yield Button('Cancel', id='cancel')
            with VerticalScroll(classes='preview'):
                yield Static('Fill in the map, then Preview.', id='preview-text')

    def on_input_changed(self):
        self.invalidate()

    def on_checkbox_changed(self):
        self.invalidate()

    def invalidate(self):
        self.plan = None
        if self.is_mounted:
            self.query_one('#apply', Button).disabled = True

    def value(self, field: str) -> str:
        return self.query_one(f'#{field}', Input).value.strip()

    def on_button_pressed(self, event: Button.Pressed):
        preview = self.query_one('#preview-text', Static)
        if event.button.id == 'preview':
            name = self.value('name')
            try:
                self.plan = new_map.build_plan(name, self.value('label') or name.replace('_', ' '),
                                               self.query_one('#header', Checkbox).value,
                                               self.value('template'), root=self.root)
            except new_map.NewMapError as error:
                self.plan = None
                preview.update(f'error: {error}')
                self.query_one('#apply', Button).disabled = True
                return
            preview.update('\n'.join(self.plan.lines()))
            self.query_one('#apply', Button).disabled = False
        elif event.button.id == 'apply' and self.plan is not None:
            self.plan.apply()
            self.dismiss(True)
        else:
            super().on_button_pressed(event)
