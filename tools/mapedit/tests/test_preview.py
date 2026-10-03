# ABOUTME: Tests for mapedit's image display: the half-block ImageView widget and the map view's render preview pane.
# ABOUTME: Covers fitting images to the widget, the preview toggle, top/angled switching and texture animation playback.

import io
import unittest
import unittest.mock

import numpy as np

from mapedit import image_view
from mapedit.image_view import UPPER_HALF, ImageView, fit, to_text
from mapedit.app import MapEditApp, MapScreen

from .base import MapEditTestCase

SIZE = (150, 48)


class HalfBlockTest(unittest.TestCase):
    def test_each_cell_shows_two_pixels(self):
        image = np.zeros((2, 1, 4), dtype=np.uint8)
        image[0] = [255, 0, 0, 255]
        image[1] = [0, 0, 255, 255]

        text = to_text(image)

        self.assertEqual(text.plain, UPPER_HALF + '\n')
        style = text.spans[0].style
        self.assertEqual(style.color.triplet, (255, 0, 0))
        self.assertEqual(style.bgcolor.triplet, (0, 0, 255))

    def test_transparent_pixels_show_the_background(self):
        image = np.zeros((2, 1, 4), dtype=np.uint8)

        style = to_text(image, background=(10, 20, 30)).spans[0].style

        self.assertEqual(style.color.triplet, (10, 20, 30))

    def test_fit_keeps_the_aspect_ratio_within_the_cells(self):
        image = np.zeros((100, 200, 4), dtype=np.uint8)

        self.assertEqual(fit(image, 40, 40).shape[:2], (20, 40))     # 40 columns, 20 pixel rows = 10 text rows
        self.assertEqual(fit(image, 100, 5).shape[:2], (10, 20))     # height-limited: 5 rows = 10 pixels


class PreviewTest(MapEditTestCase):
    RENDER = True

    async def open_preview(self, pilot, query='twinleaf town'):
        await self.open_map(pilot, query)
        await pilot.press('p')
        await self.app.workers.wait_for_complete()
        await pilot.pause()
        return self.app.screen.query_one('#render-preview', ImageView)

    async def test_p_shows_a_render_of_the_block(self):
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot)

            self.assertTrue(preview.display)
            self.assertIsNotNone(preview.image)
            self.assertGreater(len(np.unique(preview.image[..., :3].reshape(-1, 3), axis=0)), 50)

    async def test_p_again_hides_it(self):
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot)

            await pilot.press('p')
            await pilot.pause()

            self.assertFalse(preview.display)

    async def test_v_switches_between_top_and_angled(self):
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot)
            top = preview.image

            await pilot.press('v')
            await self.app.workers.wait_for_complete()
            await pilot.pause()

            self.assertEqual(self.app.screen.preview_view, 'angled')
            self.assertFalse(np.array_equal(top, preview.image))

    async def test_t_plays_the_waterfalls_in_real_time(self):
        for block in ('063', '064', '065'):
            self.sandbox.copy(f'res/field/maps/data/map_data_{block}.bin')
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot, 'route 210 north')

            await pilot.press('t')
            await pilot.pause()
            self.assertTrue(self.app.screen.playing)
            first = preview.image.copy()
            await pilot.pause(0.3)

            self.assertFalse(np.array_equal(first, preview.image))
            await pilot.press('t')
            await pilot.pause()
            self.assertFalse(self.app.screen.playing)

    async def test_t_on_a_block_without_animations_says_so(self):
        async with self.app.run_test(size=SIZE) as pilot:
            await self.open_preview(pilot)

            await pilot.press('t')
            await pilot.pause()

            self.assertFalse(self.app.screen.playing)
            messages = [notification.message for notification in self.app._notifications]
            self.assertTrue(any('no texture animations' in m for m in messages), messages)

    async def test_the_cursor_tile_is_outlined_on_the_top_view(self):
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot)
            before = preview.shown().copy()

            await pilot.press('right')
            await pilot.pause()

            self.assertFalse(np.array_equal(before, preview.shown()))

    async def test_adding_a_prop_refreshes_the_preview(self):
        async with self.app.run_test(size=SIZE) as pilot:
            preview = await self.open_preview(pilot)
            before = preview.image
            screen = self.app.screen
            assert isinstance(screen, MapScreen)

            screen.grid.cursor = (100, 880)
            await pilot.press('a')
            await pilot.pause()
            from textual.widgets import Select
            self.app.screen.query_one('#model', Select).value = 'prop_model_022_nsbmd'
            await pilot.click('#preview')
            await pilot.pause()
            await pilot.click('#apply')
            await self.app.workers.wait_for_complete()
            await pilot.pause()

            self.assertFalse(np.array_equal(before, preview.image))


class GraphicsModeTest(MapEditTestCase):
    RENDER = True

    def test_auto_falls_back_to_half_blocks_without_terminal_graphics(self):
        # Tests do not run in a terminal, so detection finds no Sixel or Kitty support.
        self.assertEqual(image_view.choose_mode('auto'), 'halfblock')
        self.assertEqual(image_view.choose_mode('sixel'), 'sixel')

    def test_unknown_modes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "graphics mode must be one of auto, sixel, kitty, halfblock"):
            image_view.choose_mode('vga')

    async def test_pixel_modes_hand_sized_images_to_the_graphics_widget(self):
        for mode, widget_type in (('sixel', image_view.SixelImage), ('kitty', image_view.TGPImage)):
            self.app = MapEditApp(self.sandbox.root, graphics=mode)
            # The Kitty backend uploads images by writing straight to the real stdout; capture that.
            terminal = io.StringIO()
            with unittest.mock.patch('sys.__stdout__', terminal):
                async with self.app.run_test(size=SIZE) as pilot:
                    await self.open_map(pilot)
                    await pilot.press('p')
                    await self.app.workers.wait_for_complete()
                    await pilot.pause()

                    preview = self.app.screen.query_one('#render-preview', ImageView)
                    backend = preview.query_one(widget_type)
                    with self.subTest(mode=mode):
                        self.assertEqual(preview.mode, mode)
                        self.assertIsNotNone(backend.image)
                        columns, rows = preview.size
                        cell_width, cell_height = image_view.cell_size()
                        self.assertLessEqual(backend.image.width, columns * cell_width)
                        self.assertLessEqual(backend.image.height, rows * cell_height)
            if mode == 'kitty':
                self.assertIn('\x1b_G', terminal.getvalue())      # a Kitty graphics transmission
