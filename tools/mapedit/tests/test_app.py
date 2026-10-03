# ABOUTME: End-to-end tests for the mapedit TUI, driven through Textual's pilot against a sandbox copy of the repo.
# ABOUTME: Covers browsing to a map, the tile grid and cursor, and adding, moving and removing props with confirmation.

import unittest

from textual.widgets import DataTable, Input, Select, Static

from mapedit.app import AddPropScreen, BlockGrid, BrowserScreen, ConfirmScreen, MapScreen

from .base import MapEditTestCase

TWINLEAF = 'MAP_HEADER_TWINLEAF_TOWN'
SIZE = (150, 48)


class AppTestCase(MapEditTestCase):
    async def open_twinleaf(self, pilot):
        await pilot.click('#search')
        await pilot.press(*'twinleaf town', 'enter')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, MapScreen)

    def grid(self) -> BlockGrid:
        return self.app.screen.query_one(BlockGrid)

    def info(self) -> str:
        return str(self.app.screen.query_one('#tile-info', Static).render())

    async def move_cursor_to(self, pilot, x, z):
        grid = self.grid()
        grid.cursor = (x, z)
        await pilot.pause()


class BrowserTest(AppTestCase):
    LAND_DATA = ('000', '184')
    async def test_starts_on_the_browser_listing_every_map(self):
        async with self.app.run_test(size=SIZE):
            self.assertIsInstance(self.app.screen, BrowserScreen)
            self.assertGreater(self.app.screen.query_one('#maps').option_count, 500)

    async def test_search_narrows_the_list_and_enter_opens_the_first_match(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.click('#search')
            await pilot.press(*'twinleaf rival 1f')
            await pilot.pause()
            self.assertEqual(self.app.screen.query_one('#maps').option_count, 1)

            await pilot.press('enter')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertEqual(self.app.screen.view.header, 'MAP_HEADER_TWINLEAF_TOWN_RIVAL_HOUSE_1F')

    async def test_letters_typed_in_the_search_box_search(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.click('#search')
            await pilot.press(*'new')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, BrowserScreen)
            self.assertEqual(self.app.screen.query_one('#search', Input).value, 'new')

    async def test_down_moves_to_the_list_and_slash_back_to_search(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.press('down')
            await pilot.pause()
            self.assertEqual(self.app.focused.id, 'maps')

            await pilot.press('slash')
            await pilot.pause()
            self.assertEqual(self.app.focused.id, 'search')

    async def test_search_box_stays_on_screen_while_browsing_the_list(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await pilot.press('down', *['down'] * 60)
            await pilot.pause()

            self.assertTrue(self.app.screen.query_one('#search', Input).region.y < SIZE[1])
            await pilot.click('#search')

    async def test_browser_actions_are_listed_in_the_footer_without_ctrl(self):
        async with self.app.run_test(size=SIZE) as pilot:
            keys = {binding.key for binding in BrowserScreen.BINDINGS}

            self.assertTrue({'n', 'w', 'f', 'x'} <= keys)
            self.assertFalse([key for key in keys if key.startswith('ctrl+')])

    async def test_escape_returns_to_the_browser(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)

            await pilot.press('escape')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, BrowserScreen)


class GridTest(AppTestCase):
    async def test_grid_shows_tile_kinds_with_markers_on_top(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            grid = self.grid()

            self.assertEqual(grid.symbol_at(106, 874), 'P')   # a house
            self.assertEqual(grid.symbol_at(105, 875), 'W')   # the rival's door warp (the rival NPC stands there too)
            self.assertEqual(grid.symbol_at(119, 878), 'N')

    async def test_cursor_starts_in_the_block_centre_and_moves_with_the_arrows(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            self.assertEqual(self.grid().cursor, (112, 880))

            await pilot.press('right', 'right', 'up')
            await pilot.pause()

            self.assertEqual(self.grid().cursor, (114, 879))
            self.assertIn('(114, 879)', self.info())

    async def test_cursor_stays_inside_the_block(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            await self.move_cursor_to(pilot, 127, 864)

            await pilot.press('right', 'up')
            await pilot.pause()

            self.assertEqual(self.grid().cursor, (127, 864))

    async def test_info_panel_describes_the_tile_and_whats_on_it(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            await self.move_cursor_to(pilot, 105, 875)

            info = self.info()

            self.assertIn('TILE_BEHAVIOR_DOOR', info)
            self.assertIn('MAP_HEADER_TWINLEAF_TOWN_RIVAL_HOUSE_1F', info)

    async def test_props_table_lists_the_blocks_props(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)

            table = self.app.screen.query_one('#props', DataTable)

            self.assertEqual(table.row_count, 8)
            self.assertEqual(table.get_row_at(0)[:2], ['000:0', 'prop_model_023.nsbmd'])


class AddPropTest(AppTestCase):
    async def open_add(self, pilot, x=112, z=880):
        await self.open_twinleaf(pilot)
        await self.move_cursor_to(pilot, x, z)
        await pilot.press('a')
        await pilot.pause()
        self.assertIsInstance(self.app.screen, AddPropScreen)

    async def test_offers_only_the_areas_model_set(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_add(pilot)

            options = self.app.screen.models

            self.assertIn('prop_model_022_nsbmd', options)
            self.assertNotIn('regular_ship_nsbmd', options)

    async def test_preview_then_apply_writes_the_prop_at_the_cursor(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_add(pilot)
            self.app.screen.query_one('#model', Select).value = 'prop_model_022_nsbmd'

            await pilot.click('#preview')
            await pilot.pause()
            preview = str(self.app.screen.query_one('#preview-text', Static).render())
            self.assertIn('add 000:8 prop_model_022.nsbmd at x 112', preview)
            self.assertIn('(ground)', preview)
            self.assertEqual(len(self.sandbox.land().props), 8)

            await pilot.click('#apply')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            props = self.sandbox.land().props
            self.assertEqual(len(props), 9)
            self.assertEqual(props[8].model_id, 22)
            self.assertEqual(self.app.screen.query_one('#props', DataTable).row_count, 9)

    async def test_apply_without_preview_is_not_possible(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_add(pilot)

            self.assertTrue(self.app.screen.query_one('#apply').disabled)

    async def test_invalid_numbers_are_reported(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_add(pilot)
            self.app.screen.query_one('#model', Select).value = 'prop_model_022_nsbmd'
            self.app.screen.query_one('#scale', Input).value = 'big'

            await pilot.click('#preview')
            await pilot.pause()

            self.assertIn('scale must be a number', str(self.app.screen.query_one('#preview-text', Static).render()))
            self.assertTrue(self.app.screen.query_one('#apply').disabled)

    async def test_cancel_writes_nothing(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_add(pilot)
            self.app.screen.query_one('#model', Select).value = 'prop_model_022_nsbmd'
            await pilot.click('#preview')

            await pilot.press('escape')
            await pilot.pause()

            self.assertIsInstance(self.app.screen, MapScreen)
            self.assertEqual(len(self.sandbox.land().props), 8)


class MoveAndRemoveTest(AppTestCase):
    async def select_prop(self, pilot, row):
        table = self.app.screen.query_one('#props', DataTable)
        table.move_cursor(row=row)
        await pilot.pause()

    async def test_move_puts_the_selected_prop_at_the_cursor_after_confirming(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            await self.select_prop(pilot, 0)
            await self.move_cursor_to(pilot, 110, 880)

            await pilot.press('m')
            await pilot.pause()
            self.assertIsInstance(self.app.screen, ConfirmScreen)
            self.assertIn('move 000:0 to x 110', str(self.app.screen.query_one('#summary', Static).render()))

            await pilot.click('#apply')
            await pilot.pause()

            moved = self.sandbox.land().props[0]
            self.assertEqual((moved.position[0], moved.position[2]), (-1.5 * 16 * 4096, 0.5 * 16 * 4096))

    async def test_delete_removes_the_selected_prop_after_confirming(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            await self.select_prop(pilot, 1)

            await pilot.press('d')
            await pilot.pause()
            self.assertIn('remove 000:1', str(self.app.screen.query_one('#summary', Static).render()))
            await pilot.click('#apply')
            await pilot.pause()

            self.assertEqual(len(self.sandbox.land().props), 7)
            self.assertEqual(self.app.screen.query_one('#props', DataTable).row_count, 7)

    async def test_cancelling_a_confirmation_writes_nothing(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_twinleaf(pilot)
            await self.select_prop(pilot, 1)
            await pilot.press('d')
            await pilot.pause()

            await pilot.click('#cancel')
            await pilot.pause()

            self.assertEqual(len(self.sandbox.land().props), 8)


if __name__ == '__main__':
    unittest.main()
