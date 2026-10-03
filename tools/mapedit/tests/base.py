# ABOUTME: Base class for mapedit's UI tests: an async test case with a sandbox repo and the app pointed at it.
# ABOUTME: Turns off asyncio debug mode, whose 100 ms slow-callback reports fire on every land data read.

import asyncio
import unittest

from mapedit.app import MapEditApp

from .sandbox import Sandbox


class MapEditTestCase(unittest.IsolatedAsyncioTestCase):
    LAND_DATA = ('000',)
    MAP_SOURCES = False
    RENDER = False

    def setUp(self):
        self.sandbox = Sandbox(land_data=self.LAND_DATA, map_sources=self.MAP_SOURCES, render=self.RENDER)
        self.app = MapEditApp(self.sandbox.root)

    async def asyncSetUp(self):
        # IsolatedAsyncioTestCase runs the loop in debug mode, which logs any step over 100 ms.
        # Opening a map reads its land data and legitimately takes about that long.
        asyncio.get_running_loop().set_debug(False)

    def tearDown(self):
        self.sandbox.cleanup()

    async def open_map(self, pilot, query='twinleaf town'):
        await pilot.click('#search')
        await pilot.press(*query, 'enter')
        await pilot.pause()
