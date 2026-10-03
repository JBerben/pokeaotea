# ABOUTME: End-to-end tests for the register-prop form, which wraps new_prop.py inside mapedit.
# ABOUTME: Uses the retail waterfall (prop_model_305 + prop_animation_018) as the prop being registered.

import unittest

from textual.widgets import Checkbox, Input, Static

from mapedit.app import AddPropScreen, MapScreen
from mapedit.register import RegisterPropScreen

from .base import MapEditTestCase
from .sandbox import REPO

WATERFALL_MODEL = REPO / 'res/field/props/models/prop_model_305.nsbmd'
WATERFALL_ANIMATION = REPO / 'res/field/props/animations/prop_animation_018.nsbta'
SIZE = (150, 48)


class RegisterPropTest(MapEditTestCase):
    async def open_form(self, pilot):
        await pilot.click('#search')
        await pilot.press(*'twinleaf town', 'enter')
        await pilot.pause()
        await pilot.press('r')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, RegisterPropScreen)

    def fill(self, **values):
        for field, value in values.items():
            self.app.screen.query_one(f'#{field}', Input).value = value

    def preview_text(self) -> str:
        return str(self.app.screen.query_one('#preview-text', Static).render())

    async def test_model_set_defaults_to_the_current_maps(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)

            self.assertEqual(self.app.screen.query_one('#model-sets', Input).value, '000')

    async def test_preview_shows_the_plan_and_apply_registers_the_prop(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='test_waterfall', model=str(WATERFALL_MODEL), animations=str(WATERFALL_ANIMATION))

            await pilot.click('#preview')
            await pilot.pause()
            self.assertIn('create  res/field/props/models/test_waterfall.nsbmd', self.preview_text())
            self.assertIn('prop_texture_set_000.nsbtx', self.preview_text())
            self.assertFalse(self.sandbox.path('res/field/props/models/test_waterfall.nsbmd').exists())

            await pilot.click('#apply')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertTrue(self.sandbox.path('res/field/props/models/test_waterfall.nsbmd').exists())
            self.assertTrue(self.sandbox.path('res/field/props/animations/test_waterfall_0.nsbta').exists())

    async def test_registered_prop_can_be_placed_straight_away(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='test_waterfall', model=str(WATERFALL_MODEL))
            await pilot.click('#preview')
            await pilot.click('#apply')
            await pilot.pause()

            await pilot.press('a')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, AddPropScreen)
            self.assertIn('test_waterfall_nsbmd', self.app.screen.models)

    async def test_flags_are_passed_through(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='test_waterfall', model=str(WATERFALL_MODEL), animations=str(WATERFALL_ANIMATION))
            self.app.screen.query_one('#deferred-loading', Checkbox).value = True
            await pilot.click('#preview')
            await pilot.click('#apply')
            await pilot.pause()

            lists = self.sandbox.path('res/field/props/animations/prop_animation_lists.json').read_text()
            self.assertIn('"test_waterfall_nsbmd": {"animations": ["test_waterfall_0_nsbta"], "deferredLoading": true}', lists)

    async def test_problems_are_listed_and_apply_stays_disabled(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='Bad Name', model=str(WATERFALL_MODEL), **{'model-sets': '999'})

            await pilot.click('#preview')
            await pilot.pause()

            self.assertIn("error: name 'Bad Name' must be lower snake_case", self.preview_text())
            self.assertIn("error: model set '999'", self.preview_text())
            self.assertTrue(self.app.screen.query_one('#apply').disabled)

    async def test_missing_files_are_reported_not_raised(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='test_waterfall', model='/nowhere/waterfall.nsbmd')

            await pilot.click('#preview')
            await pilot.pause()

            self.assertIn('error: /nowhere/waterfall.nsbmd does not exist', self.preview_text())

    async def test_editing_a_field_after_preview_requires_a_new_preview(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.fill(name='test_waterfall', model=str(WATERFALL_MODEL))
            await pilot.click('#preview')
            await pilot.pause()
            self.assertFalse(self.app.screen.query_one('#apply').disabled)

            self.fill(name='other_waterfall')
            await pilot.pause()

            self.assertTrue(self.app.screen.query_one('#apply').disabled)


if __name__ == '__main__':
    unittest.main()
