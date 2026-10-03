# ABOUTME: Tests for mapedit.maps, the plain-data layer the TUI draws from (headers, block tiles, events, props).
# ABOUTME: Reads the real repo; Twinleaf Town is the reference map.

import unittest

from mapedit import maps

TWINLEAF = 'MAP_HEADER_TWINLEAF_TOWN'


class HeadersTest(unittest.TestCase):
    def setUp(self):
        self.repo = maps.MapRepository(maps.REPO)

    def test_lists_every_map_header(self):
        headers = self.repo.headers()

        self.assertIn(TWINLEAF, headers)
        self.assertEqual(headers, sorted(headers))

    def test_search_matches_words_in_any_order(self):
        self.assertEqual(self.repo.search('twinleaf rival 1f'), ['MAP_HEADER_TWINLEAF_TOWN_RIVAL_HOUSE_1F'])

    def test_empty_search_lists_everything(self):
        self.assertEqual(self.repo.search(''), self.repo.headers())


class MapViewTest(unittest.TestCase):
    def setUp(self):
        self.view = maps.MapRepository(maps.REPO).load(TWINLEAF)

    def test_has_the_headers_blocks_and_area(self):
        self.assertEqual([block.land_data for block in self.view.blocks], ['000'])
        self.assertEqual(self.view.area, 'area_data_075')
        self.assertEqual(self.view.model_set, 'prop_model_set_000')
        self.assertIn('honey_tree_nsbmd', self.view.models)

    def test_block_tiles_are_a_32_by_32_grid_in_world_coordinates(self):
        block = self.view.blocks[0]
        tiles = self.view.tiles(block)

        self.assertEqual((len(tiles), len(tiles[0])), (32, 32))
        door = self.view.tile_at(block, 105, 875)
        self.assertEqual(door.kind, maps.TILE_DOOR)
        self.assertEqual(door.behavior_name, 'TILE_BEHAVIOR_DOOR')

    def test_events_in_a_block_carry_world_coordinates(self):
        events = self.view.events(self.view.blocks[0])

        self.assertIn(maps.Marker('warp', 105, 875, 'MAP_HEADER_TWINLEAF_TOWN_RIVAL_HOUSE_1F'), events)
        self.assertIn(maps.Marker('npc', 119, 878, 'LOCALID_POKEMON_BREEDER_F'), events)
        # Twinleaf has 9 object events, but its arrow signpost (z 856) stands in the block to the north.
        self.assertEqual(len([e for e in events if e.kind == 'npc']), 8)
        self.assertNotIn('LOCALID_ARROW_SIGNPOST', [e.label for e in events])

    def test_props_in_a_block_come_from_the_land_data(self):
        props = self.view.props(self.view.blocks[0])

        self.assertEqual(len(props), 8)
        self.assertEqual((props[0].prop_id, props[0].model, props[0].x, props[0].z), ('000:0', 'prop_model_023.nsbmd', 106, 873.5))

    def test_markers_at_a_tile_include_props_on_it(self):
        block = self.view.blocks[0]

        here = self.view.markers_at(block, 106, 874)

        self.assertIn('000:0', [m.label for m in here if m.kind == 'prop'])


if __name__ == '__main__':
    unittest.main()
