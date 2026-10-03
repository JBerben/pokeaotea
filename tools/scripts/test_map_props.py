#!/usr/bin/env python3
# ABOUTME: Tests for map_props.py, which lists, adds, moves and removes the props placed in a map's land data.
# ABOUTME: Retail land data is the oracle; edits run on a copy of the map sources in a temp dir.

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import map_props as mp  # noqa: E402

LAND_DATA_DIR = REPO / 'res' / 'field' / 'maps' / 'data'
TWINLEAF = 'MAP_HEADER_TWINLEAF_TOWN'
SANDGEM_MART = 'MAP_HEADER_SANDGEM_TOWN_MART'
FX32_ONE = 4096


class LandDataTest(unittest.TestCase):
    def test_every_retail_land_data_file_writes_back_unchanged(self):
        paths = sorted(LAND_DATA_DIR.glob('map_data_*.bin'))
        self.assertTrue(paths)
        for path in paths:
            data = path.read_bytes()
            with self.subTest(path=path.name):
                self.assertEqual(mp.write_land_data(mp.read_land_data(data)), data)

    def test_bytes_after_the_last_whole_prop_are_kept(self):
        # Retail map_data_506 ends its props section with a stray CRLF, which the loader ignores.
        land = mp.read_land_data((LAND_DATA_DIR / 'map_data_506.bin').read_bytes())

        self.assertEqual(len(land.props), 3)
        self.assertEqual(land.props_trailer, b'\r\n')

    def test_reads_twinleaf_props(self):
        land = mp.read_land_data((LAND_DATA_DIR / 'map_data_000.bin').read_bytes())

        self.assertEqual(len(land.props), 8)
        house = land.props[0]
        self.assertEqual(house.model_id, 23)
        self.assertEqual(house.position, (-5.5 * mp.TILE, 1 * mp.TILE, -6 * mp.TILE))
        self.assertEqual(house.scale, (FX32_ONE, FX32_ONE, FX32_ONE))

    def test_ground_height_under_a_twinleaf_house_is_where_retail_put_it(self):
        land = mp.read_land_data((LAND_DATA_DIR / 'map_data_000.bin').read_bytes())
        house = land.props[0]

        self.assertEqual(mp.ground_heights(land.bdhc, house.position[0], house.position[2]), [house.position[1]])


class CoordinatesTest(unittest.TestCase):
    def test_block_offsets_are_measured_from_the_block_centre_in_tile_centre_units(self):
        # A block's origin is its centre (LandDataManager_CalculateRenderingPosition), and a tile is 16 units.
        self.assertEqual(mp.tile_to_offset(106, 96), -5.5 * mp.TILE)
        self.assertEqual(mp.offset_to_tile(-5.5 * mp.TILE, 96), 106)
        self.assertEqual(mp.tile_to_offset(873.5, 864), -6 * mp.TILE)


class MapPropsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative in ['include/data/map_headers.h', 'res/field/props/models/map_prop_models.order']:
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, self.root / relative)
        for relative in ['res/field/matrices', 'res/field/area_data', 'res/field/props/model_sets']:
            shutil.copytree(REPO / relative, self.root / relative)
        (self.root / 'res/field/maps/data').mkdir(parents=True)
        for name in ('map_data_000.bin', 'map_data_190.bin'):
            shutil.copyfile(LAND_DATA_DIR / name, self.root / 'res/field/maps/data' / name)
        self.maps = mp.MapContext(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def land(self, name='000'):
        return mp.read_land_data((self.root / f'res/field/maps/data/map_data_{name}.bin').read_bytes())

    def errors(self, function, *args, **kwargs):
        with self.assertRaises(mp.MapPropError) as raised:
            function(self.maps, *args, **kwargs)
        return raised.exception.errors


class ListTest(MapPropsTestCase):
    def test_lists_props_in_world_tiles(self):
        rows = mp.list_props(self.maps, TWINLEAF)

        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0], mp.PropRow('000:0', 'prop_model_023.nsbmd', 106, 1.0, 873.5, 1.0))

    def test_unknown_header_is_an_error(self):
        self.assertEqual(self.errors(mp.list_props, 'MAP_HEADER_NOWHERE'),
                         ['no MAP_HEADER_NOWHERE in include/data/map_headers.h'])


class AddTest(MapPropsTestCase):
    def test_appends_a_prop_on_the_ground_of_the_chosen_tile(self):
        change = mp.add_prop(self.maps, TWINLEAF, 'prop_model_022', 106, 873.5)
        change.apply()

        land = self.land()
        self.assertEqual(len(land.props), 9)
        added = land.props[8]
        self.assertEqual(added.model_id, 22)
        self.assertEqual(added.position, (-5.5 * mp.TILE, 1 * mp.TILE, -6 * mp.TILE))
        self.assertEqual(added.rotation, (0, 0, 0))
        self.assertEqual(added.scale, (FX32_ONE, FX32_ONE, FX32_ONE))
        self.assertEqual(change.prop_id, '000:8')

    def test_everything_but_the_props_section_is_unchanged(self):
        before = self.land()

        mp.add_prop(self.maps, TWINLEAF, 'prop_model_022', 106, 873.5).apply()

        after = self.land()
        self.assertEqual((after.terrain, after.model, after.bdhc), (before.terrain, before.model, before.bdhc))
        self.assertEqual(after.props[:8], before.props)

    def test_explicit_height_and_scale_are_used(self):
        mp.add_prop(self.maps, TWINLEAF, 'prop_model_022_nsbmd', 100, 870, y=2.5, scale=1.5).apply()

        added = self.land().props[8]
        self.assertEqual(added.position[1], 2.5 * mp.TILE)
        self.assertEqual(added.scale, (int(1.5 * FX32_ONE),) * 3)

    def test_nothing_is_written_until_apply(self):
        before = (self.root / 'res/field/maps/data/map_data_000.bin').read_bytes()

        mp.add_prop(self.maps, TWINLEAF, 'prop_model_022.nsbmd', 106, 873.5)

        self.assertEqual((self.root / 'res/field/maps/data/map_data_000.bin').read_bytes(), before)

    def test_model_must_exist(self):
        self.assertEqual(self.errors(mp.add_prop, TWINLEAF, 'waterfall', 106, 873.5),
                         ["no model 'waterfall' in map_prop_models.order"])

    def test_model_must_be_in_the_areas_model_set(self):
        errors = self.errors(mp.add_prop, TWINLEAF, 'regular_ship', 106, 873.5)

        self.assertEqual(len(errors), 1)
        self.assertRegex(errors[0], r"^regular_ship\.nsbmd is not in prop_model_set_\d{3}, the model set of area_data_075; "
                                    r"the game would draw the dummy box\. Add it with new_prop\.py --model-set \d{3}")

    def test_tile_must_be_in_the_headers_blocks(self):
        errors = self.errors(mp.add_prop, TWINLEAF, 'prop_model_022', 10, 10)

        self.assertEqual(errors, ['tile (10, 10) is not in a block of MAP_HEADER_TWINLEAF_TOWN; '
                                  'its blocks cover x 96..127, z 864..895'])

    def test_a_block_holds_at_most_32_props(self):
        for _ in range(32 - 8):
            mp.add_prop(self.maps, TWINLEAF, 'prop_model_022', 106, 873.5).apply()

        self.assertEqual(self.errors(mp.add_prop, TWINLEAF, 'prop_model_022', 106, 873.5),
                         ['map_data_000 already has 32 props, the most a block can load (MAX_LOADED_MAP_PROPS)'])

    def test_shared_land_data_is_reported(self):
        change = mp.add_prop(self.maps, SANDGEM_MART, self.mart_model(), 4, 4)

        self.assertTrue(any('MAP_HEADER_JUBILIFE_CITY_MART' in warning for warning in change.warnings), change.warnings)

    def mart_model(self):
        order = (self.root / 'res/field/props/models/map_prop_models.order').read_text().split()
        return order[self.land('190').props[0].model_id]


class MoveTest(MapPropsTestCase):
    def test_moves_a_prop_keeping_its_height(self):
        before = self.land().props[0]

        mp.move_prop(self.maps, TWINLEAF, '000:0', x=110, z=880).apply()

        moved = self.land().props[0]
        self.assertEqual(moved.position, (mp.tile_to_offset(110, 96), before.position[1], mp.tile_to_offset(880, 864)))
        self.assertEqual(moved.model_id, before.model_id)

    def test_changes_height_only(self):
        before = self.land().props[0]

        mp.move_prop(self.maps, TWINLEAF, '000:0', y=3).apply()

        self.assertEqual(self.land().props[0].position, (before.position[0], 3 * mp.TILE, before.position[2]))

    def test_cannot_move_into_another_block(self):
        self.assertEqual(self.errors(mp.move_prop, TWINLEAF, '000:0', x=130, z=880),
                         ['tile (130, 880) is outside map_data_000 (x 96..127, z 864..895); remove the prop and add it in the other block'])

    def test_prop_id_must_exist(self):
        self.assertEqual(self.errors(mp.move_prop, TWINLEAF, '000:8', x=100, z=870),
                         ['no prop 000:8; map_data_000 has props 000:0 to 000:7'])

    def test_prop_must_belong_to_the_header(self):
        self.assertEqual(self.errors(mp.move_prop, TWINLEAF, '190:0', x=100, z=870),
                         ['map_data_190 is not a block of MAP_HEADER_TWINLEAF_TOWN'])


class RemoveTest(MapPropsTestCase):
    def test_removes_the_prop_and_later_ones_move_up(self):
        before = self.land().props

        mp.remove_prop(self.maps, TWINLEAF, '000:1').apply()

        self.assertEqual(self.land().props, before[:1] + before[2:])


class CommandLineTest(MapPropsTestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / 'map_props.py'), '--root', str(self.root), *args],
                              capture_output=True, text=True)

    def test_list(self):
        result = self.run_cli('list', TWINLEAF)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('000:0  prop_model_023.nsbmd', result.stdout)

    def test_add_dry_run_writes_nothing(self):
        before = (self.root / 'res/field/maps/data/map_data_000.bin').read_bytes()

        result = self.run_cli('add', TWINLEAF, 'prop_model_022', '--x', '106', '--z', '873.5', '--dry-run')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nothing written (--dry-run).', result.stdout)
        self.assertEqual((self.root / 'res/field/maps/data/map_data_000.bin').read_bytes(), before)

    def test_add_reports_the_new_id_and_height(self):
        result = self.run_cli('add', TWINLEAF, 'prop_model_022', '--x', '106', '--z', '873.5')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('000:8', result.stdout)
        self.assertIn('y 1 (ground)', result.stdout)
        self.assertEqual(len(self.land().props), 9)

    def test_errors_exit_1(self):
        result = self.run_cli('add', TWINLEAF, 'waterfall', '--x', '106', '--z', '873.5')

        self.assertEqual(result.returncode, 1)
        self.assertIn("no model 'waterfall'", result.stderr)


if __name__ == '__main__':
    unittest.main()
