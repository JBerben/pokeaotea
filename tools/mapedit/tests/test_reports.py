# ABOUTME: End-to-end tests for mapedit's report and scaffolding screens: map info, warp check, free flags, new map.
# ABOUTME: Reports read the checkout (they are read-only); the new-map form writes into the sandbox.

from textual.widgets import Checkbox, Input, Static

from mapedit.app import BrowserScreen, MapScreen
from mapedit.reports import FreeStateScreen, MapInfoScreen, NewMapScreen, WarpsScreen

from .base import MapEditTestCase

SIZE = (150, 48)


def text_of(screen, selector='#report') -> str:
    return str(screen.query_one(selector, Static).render())


class MapInfoTest(MapEditTestCase):
    async def test_shows_the_map_info_report_for_the_open_map(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_map(pilot)

            await pilot.press('i')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapInfoScreen)
            report = text_of(self.app.screen)
            self.assertIn('MAP_HEADER_TWINLEAF_TOWN', report)
            self.assertIn('entry table', report)
            self.assertIn('flags used', report)

    async def test_escape_returns_to_the_map(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_map(pilot)
            await pilot.press('i')
            await pilot.pause()

            await pilot.press('escape')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)

    async def test_a_header_without_scripts_says_so(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.app.push_screen(MapInfoScreen('MAP_HEADER_NOWHERE'))
            await pilot.pause()

            self.assertIn('MAP_HEADER_NOWHERE has no scripts file', text_of(self.app.screen))


class WarpsTest(MapEditTestCase):
    async def test_checks_the_open_maps_warps(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_map(pilot)

            await pilot.press('w')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, WarpsScreen)
            self.assertIn('4 warp(s) checked, 0 finding(s)', text_of(self.app.screen))

    async def test_one_way_toggle_rechecks(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.press('ctrl+t')
            await pilot.pause()
            before = text_of(self.app.screen)

            self.app.screen.query_one('#one-way', Checkbox).value = True
            await pilot.pause()

            self.assertNotIn('one-way warps', before)
            self.assertIn('one-way warps', text_of(self.app.screen))

    async def test_browser_checks_every_map(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.press('ctrl+t')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, WarpsScreen)
            self.assertRegex(text_of(self.app.screen), r'\d{3,} warp\(s\) checked')


class FreeStateTest(MapEditTestCase):
    async def open_free_state(self, pilot):
        await pilot.press('ctrl+f')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, FreeStateScreen)
        await self.app.workers.wait_for_complete()
        await pilot.pause()

    async def test_lists_free_flags_and_variables(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_free_state(pilot)

            report = text_of(self.app.screen)
            self.assertIn('flags:', report)
            self.assertIn('variables:', report)
            self.assertIn('UNUSED', report)

    async def test_checks_a_name(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_free_state(pilot)

            await pilot.click('#check')
            await pilot.press(*'FLAG_NOPE', 'enter')
            await pilot.pause()

            self.assertIn('FLAG_NOPE is not in generated/vars_flags.txt', text_of(self.app.screen, '#check-result'))

    async def test_opens_from_the_map_view_too(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_map(pilot)

            await pilot.press('f')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, FreeStateScreen)


class NewMapTest(MapEditTestCase):
    MAP_SOURCES = True
    # map_data_180 is the house the default template (MAP_HEADER_TWINLEAF_TOWN_NORTHEAST_HOUSE) uses.
    LAND_DATA = ('000', '180')

    async def open_form(self, pilot):
        await pilot.press('ctrl+n')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, NewMapScreen)

    async def test_preview_then_apply_scaffolds_the_map_and_its_header(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.app.screen.query_one('#name', Input).value = 'my_new_town'
            self.app.screen.query_one('#header', Checkbox).value = True

            await pilot.click('#preview')
            await pilot.pause()
            self.assertIn('create  res/field/scripts/scripts_my_new_town.s', text_of(self.app.screen, '#preview-text'))
            self.assertFalse(self.sandbox.path('res/field/scripts/scripts_my_new_town.s').exists())

            await pilot.click('#apply')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, BrowserScreen)
            self.assertTrue(self.sandbox.path('res/field/scripts/scripts_my_new_town.s').exists())
            self.assertIn('[MAP_HEADER_MY_NEW_TOWN]', self.sandbox.path('include/data/map_headers.h').read_text())

    async def test_new_header_is_listed_and_opens(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.app.screen.query_one('#name', Input).value = 'my_new_town'
            self.app.screen.query_one('#header', Checkbox).value = True
            await pilot.click('#preview')
            await pilot.click('#apply')
            await pilot.pause()

            await self.open_map(pilot, 'my new town')

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertEqual(self.app.screen.view.header, 'MAP_HEADER_MY_NEW_TOWN')

    async def test_a_header_on_a_shared_overworld_matrix_explains_why_it_has_no_blocks(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.app.screen.query_one('#name', Input).value = 'my_new_town'
            self.app.screen.query_one('#header', Checkbox).value = True
            self.app.screen.query_one('#template', Input).value = 'MAP_HEADER_TWINLEAF_TOWN'
            await pilot.click('#preview')
            await pilot.click('#apply')
            await pilot.pause()

            await self.open_map(pilot, 'my new town')

            self.assertIsInstance(self.app.screen, BrowserScreen)
            messages = [notification.message for notification in self.app._notifications]
            self.assertTrue(any('map_matrix_000 names a header in every cell' in m for m in messages), messages)

    async def test_errors_are_shown_and_nothing_is_written(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_form(pilot)
            self.app.screen.query_one('#name', Input).value = 'twinleaf_town'

            await pilot.click('#preview')
            await pilot.pause()

            self.assertIn('error: these already exist', text_of(self.app.screen, '#preview-text'))
            self.assertTrue(self.app.screen.query_one('#apply').disabled)
