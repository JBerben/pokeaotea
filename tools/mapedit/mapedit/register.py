# ABOUTME: The register-prop form: collects new_prop.py's arguments, previews its plan, and applies it on confirmation.
# ABOUTME: All validation and writing is new_prop.build_plan's; this screen only gathers input and shows the result.

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Checkbox, Input, Label, Static

from . import maps
from .app import ChangeDialog

import new_prop  # noqa: E402  (tools/scripts is on sys.path via mapedit.maps)


class RegisterPropScreen(ChangeDialog):
    def __init__(self, view: maps.MapView):
        super().__init__()
        self.view = view
        self.plan = None

    def compose(self) -> ComposeResult:
        set_id = self.view.model_set.removeprefix('prop_model_set_')
        with Vertical():
            yield Label('Register a new prop (new_prop.py)')
            yield Input(placeholder='Name, lower snake_case, e.g. route_201_waterfall', id='name')
            yield Input(placeholder='Model: path to the .nsbmd', id='model')
            yield Input(placeholder='Textures: path to an .nsbtx (blank: the ones embedded in the model)', id='textures')
            yield Input(placeholder='Animations: paths, comma separated, in index order (blank: none)', id='animations')
            yield Input(value=set_id, placeholder='Model sets, comma separated, e.g. 000, 012', id='model-sets')
            with Horizontal():
                yield Checkbox('Deferred loading', id='deferred-loading')
                yield Checkbox('Deferred add to render obj', id='deferred-add-to-render-obj')
                yield Checkbox('Bicycle slope', id='bicycle-slope')
            with Horizontal():
                yield Button('Preview', id='preview')
                yield Button('Apply', id='apply', variant='primary', disabled=True)
                yield Button('Cancel', id='cancel')
            with VerticalScroll(classes='preview'):
                yield Static('Fill in the prop, then Preview.', id='preview-text')

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

    def paths(self, field: str) -> list[Path]:
        return [Path(part.strip()).expanduser() for part in self.value(field).split(',') if part.strip()]

    def build_plan(self):
        model = Path(self.value('model')).expanduser() if self.value('model') else None
        textures = Path(self.value('textures')).expanduser() if self.value('textures') else None
        animations = self.paths('animations')

        errors = []
        if model is None:
            errors.append('choose a model')
        missing = [path for path in [model, textures, *animations] if path is not None and not path.is_file()]
        errors += [f'{path} does not exist' for path in missing]
        if errors:
            raise new_prop.PropError(errors)

        request = new_prop.PropRequest(
            name=self.value('name'),
            model=model,
            textures=textures,
            animations=animations,
            deferred_loading=self.query_one('#deferred-loading', Checkbox).value,
            deferred_add_to_render_obj=self.query_one('#deferred-add-to-render-obj', Checkbox).value,
            bicycle_slope=self.query_one('#bicycle-slope', Checkbox).value,
            model_sets=[part.strip() for part in self.value('model-sets').split(',') if part.strip()],
        )
        return new_prop.build_plan(self.view.repository.root, request)

    def on_button_pressed(self, event: Button.Pressed):
        preview = self.query_one('#preview-text', Static)
        if event.button.id == 'preview':
            try:
                self.plan = self.build_plan()
            except new_prop.PropError as error:
                self.plan = None
                preview.update('\n'.join(f'error: {message}' for message in error.errors))
                self.query_one('#apply', Button).disabled = True
                return
            notes = ''.join(f'\nnote: {note}' for note in self.plan.notes)
            preview.update(self.plan.describe() + notes)
            self.query_one('#apply', Button).disabled = False
        elif event.button.id == 'apply' and self.plan is not None:
            self.plan.apply()
            self.dismiss(True)
        else:
            super().on_button_pressed(event)
