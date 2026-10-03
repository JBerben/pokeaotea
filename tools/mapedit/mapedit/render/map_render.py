# ABOUTME: Renders a whole map: each block's map model and placed props, textured from the area's sets as the game does.
# ABOUTME: Also reports textures the area is missing (which the game would draw white) and can mark events on top views.

import json
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .. import maps
from . import animation
from . import model as nsbmd
from . import raster, scene

MAP_TEXTURE_SETS = 'res/field/maps/texture_sets'
PROP_MODELS = 'res/field/props/models'
PROP_TEXTURE_SETS = 'res/field/props/texture_sets'
TILE = 16          # world units per tile
ALTITUDE = 8       # world units per altitude step (MAP_OBJECT_TILE_SIZE / 2)
MARKER_COLOURS = {'warp': (230, 40, 40), 'npc': (40, 200, 230), 'sign': (240, 210, 40), 'trigger': (60, 220, 90)}


@dataclass
class RenderResult:
    image: np.ndarray
    blocks: list[str]
    props: int
    missing_textures: list[str] = field(default_factory=list)


def area_texture_sets(repository: maps.MapRepository, header: str, prop_texture_set: str | None = None):
    root = repository.root
    area = repository.context.header(header)['areaDataArchiveID']
    area_data = json.loads((root / 'res/field/area_data' / f'{area}.json').read_text(encoding='utf-8'))
    map_set = (root / MAP_TEXTURE_SETS / f"{area_data['mapTextureSet']}.nsbtx").read_bytes()
    model_set = prop_texture_set or area_data['mapPropSet']
    model_sets = (root / 'res/field/props/model_sets/prop_model_sets.order').read_text().split()
    texture_sets = [line.split('.')[0] for line in (root / PROP_TEXTURE_SETS / 'prop_texture_sets.order').read_text().split()]
    prop_set = (root / PROP_TEXTURE_SETS / f'{texture_sets[model_sets.index(model_set)]}.nsbtx').read_bytes()
    return map_set, prop_set


def block_origin(repository: maps.MapRepository, header: str, block) -> np.ndarray:
    """World position of a block's centre, where its map model and props are anchored."""
    matrix = repository.context.matrix(repository.context.header(header)['mapMatrixID'])
    row, col = block.base_z // maps.BLOCK_TILES, block.base_x // maps.BLOCK_TILES
    altitude = matrix['altitudes'][row][col] if matrix['altitudes'] else 0
    half = maps.BLOCK_TILES // 2
    return np.array([(block.base_x + half) * TILE, altitude * ALTITUDE, (block.base_z + half) * TILE], dtype=float)


def translation(offset) -> np.ndarray:
    m = np.eye(4)
    m[3, :3] = offset
    return m


class Animations:
    """Ground-tile and prop texture animations, loaded once for a run of frames."""

    def __init__(self, root):
        self.ground = animation.GroundAnimations(root)
        self.props = animation.PropAnimations(root)


@dataclass
class MapScene:
    meshes: list
    camera: object
    blocks: list
    low: np.ndarray
    high: np.ndarray
    prop_count: int
    missing_textures: list


def build_scene(repository: maps.MapRepository, header: str, view: str, size: int, props: bool, blocks,
                prop_texture_set, tick: int | None, animations: 'Animations | None', animate: bool) -> MapScene:
    """Meshes and camera for a map. tick bakes animations in at that frame; animate attaches animators instead."""
    context = repository.context
    context.header(header)
    chosen = [b for b in context.blocks(header) if blocks is None or b.land_data in blocks]
    if not chosen:
        raise maps.map_props.MapPropError([f'{header} has no blocks to render'])

    map_set, prop_set = area_texture_sets(repository, header, prop_texture_set)
    map_textures = scene.TextureLibrary(map_set)
    prop_textures = scene.TextureLibrary(prop_set)
    if tick is not None or animate:
        animations = animations or Animations(repository.root)
    if tick is not None:
        for name, ground in animations.ground.animations.items():
            if name in map_textures.textures:
                map_textures.override_texels(ground.texture_at(tick))
    ground = animations.ground if animate else None
    model_names = context.model_names()
    prop_models = {}
    meshes, prop_count = [], 0

    for block in chosen:
        land = context.read_block(block)
        origin = block_origin(repository, header, block)
        meshes += scene.meshes_from_model(nsbmd.load_model(land.model), map_textures, translation(origin),
                                          ground=ground, animate=animate)
        if not props:
            continue
        for prop in land.props:
            name = model_names[prop.model_id]
            if name not in prop_models:
                prop_models[name] = nsbmd.load_model((repository.root / PROP_MODELS / name).read_bytes())
            transform = np.diag([s / 4096 for s in prop.scale] + [1.0]) @ translation(origin + np.array(prop.position) / 4096)
            prop_animations = animations.props.for_model(name) if (tick is not None or animate) else ()
            meshes += scene.meshes_from_model(prop_models[name], prop_textures, transform, prop_animations, tick,
                                              animate=animate)
            prop_count += 1

    low = high = None
    if view == 'top':
        # Frame the blocks' tiles exactly, so pixels line up with the tile grid.
        low = np.array([min(b.base_x for b in chosen) * TILE, 0.0, min(b.base_z for b in chosen) * TILE])
        high = np.array([(max(b.base_x for b in chosen) + maps.BLOCK_TILES) * TILE, 0.0,
                         (max(b.base_z for b in chosen) + maps.BLOCK_TILES) * TILE])
        mesh_low, mesh_high = scene.bounds(meshes)
        low[1], high[1] = mesh_low[1] - 1, mesh_high[1] + 1
        camera = scene.top_camera(low, high, size)
    else:
        camera = scene.camera_for(meshes, view, size)

    missing = sorted(map_textures.missing | prop_textures.missing)
    return MapScene(meshes, camera, chosen, low, high, prop_count, missing)


def render_map(repository: maps.MapRepository, header: str, view: str = 'top', size: int = 1024, props: bool = True,
               markers: bool = False, blocks: list[str] | None = None, prop_texture_set: str | None = None,
               tick: int | None = None, animations: 'Animations | None' = None) -> RenderResult:
    """Renders a map; with a tick (game frames at 30 per second), texture animations are shown at that moment."""
    built = build_scene(repository, header, view, size, props, blocks, prop_texture_set, tick, animations, animate=False)
    image = raster.render(built.meshes, built.camera)
    if markers and view == 'top':
        image = draw_markers(image, repository.load(header), built.blocks, built.low, built.high)
    return RenderResult(image, [b.land_data for b in built.blocks], built.prop_count, built.missing_textures)


@dataclass
class BakedMap:
    """A map rasterised once; frame(tick) re-textures its animated surfaces, cheaply enough for live playback."""

    baked: raster.Baked
    overlay: object = None

    @property
    def animated(self) -> bool:
        return self.baked.animated

    def frame(self, tick: int) -> np.ndarray:
        image = self.baked.frame(tick)
        return self.overlay(image) if self.overlay else image


def bake_map(repository: maps.MapRepository, header: str, view: str = 'top', size: int = 1024, props: bool = True,
             markers: bool = False, blocks: list[str] | None = None, animations: 'Animations | None' = None) -> BakedMap:
    built = build_scene(repository, header, view, size, props, blocks, None, None, animations, animate=True)
    static = [mesh for mesh in built.meshes if mesh.animator is None]
    animated = [mesh for mesh in built.meshes if mesh.animator is not None]
    overlay = None
    if markers and view == 'top':
        view_data = repository.load(header)
        overlay = lambda image: draw_markers(image, view_data, built.blocks, built.low, built.high)  # noqa: E731
    return BakedMap(raster.bake(static, animated, built.camera), overlay)


def render_frames(repository: maps.MapRepository, header: str, ticks, **options) -> list[np.ndarray]:
    """One image per tick, from a single bake."""
    baked = bake_map(repository, header, **options)
    return [baked.frame(tick) for tick in ticks]


def draw_markers(image: np.ndarray, view: maps.MapView, blocks, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Dots on event tiles: warps red, NPCs cyan, signs yellow, triggers green."""
    picture = Image.fromarray(image)
    draw = ImageDraw.Draw(picture)
    tile_pixels = image.shape[1] / ((high[0] - low[0]) / TILE)
    radius = max(tile_pixels * 0.35, 2)
    for block in blocks:
        for marker in view.events(block):
            x = (marker.x + 0.5 - low[0] / TILE) * tile_pixels
            y = (marker.z + 0.5 - low[2] / TILE) * tile_pixels
            colour = MARKER_COLOURS.get(marker.kind, (255, 255, 255)) + (255,)
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=colour, outline=(0, 0, 0, 255))
    return np.array(picture)
