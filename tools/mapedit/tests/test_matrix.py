# ABOUTME: End-to-end tests for mapedit's matrix editor: the cell grid, and setting headers, land data and altitudes.
# ABOUTME: Edits go through map_matrices.py and land in the sandbox copy of res/field/matrices.

import json

from textual.widgets import Input, Static

from mapedit.app import BrowserScreen, ConfirmScreen, MapScreen
from mapedit.matrix import MatrixGrid, MatrixScreen, MatrixValueScreen

from .base import MapEditTestCase

SIZE = (150, 48)


class MatrixTestCase(MapEditTestCase):
    LAND_DATA = ('000', '177', '180')

    def matrix(self, matrix_id='map_matrix_000'):
        return json.loads(self.sandbox.path(f'res/field/matrices/{matrix_id}.json').read_text())

    def info(self) -> str:
        return str(self.app.screen.query_one('#cell-info', Static).render())

    async def open_twinleaf_matrix(self, pilot):
        await self.open_map(pilot)
        await pilot.press('x')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, MatrixScreen)

    async def set_value(self, pilot, key, value):
        await pilot.press(key)
        await pilot.pause()
        self.assertIsInstance(self.app.screen, MatrixValueScreen)
        self.app.screen.query_one('#value', Input).value = value
        await pilot.click('#preview')
        await pilot.pause()

    def preview(self) -> str:
        return str(self.app.screen.query_one('#preview-text', Static).render())


class MatrixViewTest(MatrixTestCase):
    async def test_opens_on_the_maps_own_cell(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            self.assertEqual(self.app.screen.query_one(MatrixGrid).cursor, (27, 3))
            self.assertIn('MAP_HEADER_TWINLEAF_TOWN', self.info())
            self.assertIn('MAP_000', self.info())

    async def test_cursor_moves_and_describes_cells(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await pilot.press('up')
            await pilot.pause()

            self.assertEqual(self.app.screen.query_one(MatrixGrid).cursor, (26, 3))
            self.assertIn('cell 26,3', self.info())

    async def test_browser_opens_the_highlighted_maps_matrix(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.click('#search')
            await pilot.press(*'twinleaf town')
            await pilot.press('down', 'x')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MatrixScreen)
            self.assertEqual(self.app.screen.matrix_id, 'map_matrix_000')

    async def test_enter_opens_the_map_that_owns_the_cell(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await pilot.press('enter')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertEqual(self.app.screen.view.header, 'MAP_HEADER_TWINLEAF_TOWN')


class MatrixEditTest(MatrixTestCase):
    async def test_altitude_is_previewed_then_applied(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await self.set_value(pilot, 'a', '2')
            self.assertIn('set altitude 2 on cell 27,3 of map_matrix_000', self.preview())
            self.assertEqual(self.matrix()['altitudes'][27][3], 0)

            await pilot.click('#apply')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MatrixScreen)
            self.assertEqual(self.matrix()['altitudes'][27][3], 2)
            self.assertIn('altitude 2', self.info())

    async def test_shared_land_data_is_warned_about(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await self.set_value(pilot, 'l', 'MAP_177')

            self.assertIn('MAP_177 is also used by', self.preview())

    async def test_header_is_set(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await self.set_value(pilot, 'h', 'MAP_HEADER_ROUTE_201')
            await pilot.click('#apply')
            await pilot.pause()

            self.assertEqual(self.matrix()['headers'][27][3], 'MAP_HEADER_ROUTE_201')

    async def test_invalid_values_are_errors(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await self.set_value(pilot, 'a', 'high')
            self.assertIn('error: altitude must be a whole number', self.preview())

            self.app.screen.query_one('#value', Input).value = '300'
            # A Textual Button ignores clicks for active_effect_duration (0.2 s) after a press.
            await pilot.pause(0.25)
            await pilot.click('#preview')
            await pilot.pause()
            self.assertIn('error: altitude 300 is outside 0-255', self.preview())
            self.assertTrue(self.app.screen.query_one('#apply').disabled)

    async def test_single_header_matrices_have_no_cell_headers(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_map(pilot, 'twinleaf town northeast house')
            await pilot.press('x')
            await pilot.pause()

            await self.set_value(pilot, 'h', 'MAP_HEADER_ROUTE_201')

            self.assertIn('is a single-header matrix', self.preview())

    async def test_unshare_gives_the_cell_its_own_land_data(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)

            await pilot.press('u')
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertIn('create  res/field/maps/data/map_data_666.bin', str(self.app.screen.query_one('#summary', Static).render()))
            await pilot.click('#apply')
            await pilot.pause()

            self.assertEqual(self.matrix()['maps'][27][3], 'MAP_666')
            self.assertTrue(self.sandbox.path('res/field/maps/data/map_data_666.bin').exists())
            self.assertIn('MAP_666', self.info())

    async def test_map_view_reflects_matrix_changes_on_return(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf_matrix(pilot)
            await pilot.press('u')
            await pilot.pause()
            await pilot.click('#apply')
            await pilot.pause()

            await pilot.press('escape')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertEqual([block.land_data for block in self.app.screen.view.blocks], ['666'])
