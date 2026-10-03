# ABOUTME: Renders a whole map: each block's map model and placed props, textured from the area's sets as the game does.
# ABOUTME: Also reports textures the area is missing (which the game would draw white) and can mark events on top views.

import json
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from .. import maps
from . import animation, fog, lighting
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
    weather: str | None = None     # the weather whose fog was drawn, if any


MAP_WEATHER = 'map'   # use the map header's own weather


def weather_fog(repository: maps.MapRepository, header: str, view: str, weather):
    """(weather name, fog settings) for a render; fog is defined relative to the overworld camera, so only the
    game view draws it."""
    if weather == MAP_WEATHER:
        weather = repository.context.header(header).get('weather')
    if view != 'game' or weather is None:
        return weather, None
    return weather, fog.WEATHER_FOG.get(weather)


def game_target(repository: maps.MapRepository, header: str, at) -> np.ndarray:
    """Where the overworld camera looks when the player stands on tile at: the tile centre, on the ground."""
    context = repository.context
    block = context.block_at(header, *at) if at is not None else context.blocks(header)[0]
    x, z = at if at is not None else (block.base_x + maps.BLOCK_TILES // 2, block.base_z + maps.BLOCK_TILES // 2)
    origin = block_origin(repository, header, block)
    land = context.read_block(block)
    x_offset = maps.map_props.tile_to_offset(x, block.base_x)
    z_offset = maps.map_props.tile_to_offset(z, block.base_z)
    heights = maps.map_props.ground_heights(land.bdhc, x_offset, z_offset)
    ground = heights[0] / 4096 if heights else 0.0
    return np.array([(x + 0.5) * TILE, origin[1] + ground, (z + 0.5) * TILE])


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
    lit: bool = False
    dynamic: list = field(default_factory=list)    # tick -> meshes, for props with joint animations


# Line of sight for specular highlights: straight down for the top view, the overworld camera's pitch otherwise.
_GAME_PITCH = np.radians(scene.GAME_PITCH_DEGREES)
VIEW_DIRECTIONS = {
    'top': (0.0, -1.0, 0.0),
    'angled': (0.0, -np.sin(_GAME_PITCH), -np.cos(_GAME_PITCH)),
    'game': (0.0, -np.sin(_GAME_PITCH), -np.cos(_GAME_PITCH)),
}


def area_environment(repository: maps.MapRepository, header: str, time: int | None, view: str):
    if time is None:
        return None
    area = repository.context.header(header)['areaDataArchiveID']
    area_data = json.loads((repository.root / 'res/field/area_data' / f'{area}.json').read_text(encoding='utf-8'))
    return lighting.environment(repository.root, area_data['lightingSet'], time, VIEW_DIRECTIONS[view])


def build_scene(repository: maps.MapRepository, header: str, view: str, size: int, props: bool, blocks,
                prop_texture_set, tick: int | None, animations: 'Animations | None', animate: bool,
                time: int | None = lighting.NOON, at=None) -> MapScene:
    """Meshes and camera for a map, lit as at a time of day (None: unlit).

    tick bakes animations in at that frame; animate attaches animators instead.
    """
    context = repository.context
    context.header(header)
    environment = area_environment(repository, header, time, view)
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
    meshes, prop_count, dynamic = [], 0, []
    jointed, framing_only = [], []       # jointed props posed at the tick, and as at tick 0 for framing

    for block in chosen:
        land = context.read_block(block)
        origin = block_origin(repository, header, block)
        meshes += scene.meshes_from_model(nsbmd.load_model(land.model), map_textures, translation(origin),
                                          ground=ground, animate=animate, environment=environment)
        if not props:
            continue
        for prop in land.props:
            name = model_names[prop.model_id]
            if name not in prop_models:
                data = (repository.root / PROP_MODELS / name).read_bytes()
                prop_models[name] = (data, nsbmd.load_model(data))
            data, model = prop_models[name]
            transform = np.diag([s / 4096 for s in prop.scale] + [1.0]) @ translation(origin + np.array(prop.position) / 4096)
            moving = tick is not None or animate
            prop_animations = animations.props.for_model(name) if moving else ()
            joints = animations.props.joints_for_model(name) if moving else ()
            prop_count += 1
            if joints and animate:
                dynamic.append(posed_meshes(data, joints, prop_textures, transform, prop_animations, environment))
                continue
            if joints:
                # Posed at the tick for drawing; framed as at tick 0, so the camera holds still as it moves.
                framing_only += scene.meshes_from_model(nsbmd.load_model(data, pose=pose_at(joints, 0, data)),
                                                        prop_textures, transform)
                jointed += scene.meshes_from_model(nsbmd.load_model(data, pose=pose_at(joints, tick, data)), prop_textures,
                                                   transform, prop_animations, tick, environment=environment)
                continue
            meshes += scene.meshes_from_model(model, prop_textures, transform, prop_animations, tick,
                                              animate=animate, environment=environment)

    low = high = None
    # Frame jointed props too (posed as at tick 0), so baked and direct renders share a camera.
    framing = meshes + framing_only + [mesh for builder in dynamic for mesh in builder(0)]
    meshes = meshes + jointed
    if view == 'game':
        camera = scene.game_camera(game_target(repository, header, at), size)
    elif view == 'top':
        # Frame the blocks' tiles exactly, so pixels line up with the tile grid.
        low = np.array([min(b.base_x for b in chosen) * TILE, 0.0, min(b.base_z for b in chosen) * TILE])
        high = np.array([(max(b.base_x for b in chosen) + maps.BLOCK_TILES) * TILE, 0.0,
                         (max(b.base_z for b in chosen) + maps.BLOCK_TILES) * TILE])
        mesh_low, mesh_high = scene.bounds(framing)
        low[1], high[1] = mesh_low[1] - 1, mesh_high[1] + 1
        camera = scene.top_camera(low, high, size)
    else:
        camera = scene.camera_for(framing, view, size)

    missing = sorted(map_textures.missing | prop_textures.missing)
    return MapScene(meshes, camera, chosen, low, high, prop_count, missing, lit=environment is not None, dynamic=dynamic)


def pose_at(joints, tick: int, data: bytes) -> dict:
    pose = {}
    for joint in joints:
        pose.update(joint.pose_at(tick, data))
    return pose


def posed_meshes(data, joints, library, transform, texture_animations, environment):
    """tick -> meshes of a jointed prop posed at that tick (texture animations applied too)."""
    def build(tick: int):
        model = nsbmd.load_model(data, pose=pose_at(joints, tick, data))
        return scene.meshes_from_model(model, library, transform, texture_animations, tick, environment=environment)
    return build


def render_map(repository: maps.MapRepository, header: str, view: str = 'top', size: int = 1024, props: bool = True,
               markers: bool = False, blocks: list[str] | None = None, prop_texture_set: str | None = None,
               tick: int | None = None, animations: 'Animations | None' = None,
               time: int | None = lighting.NOON, at=None, weather=MAP_WEATHER) -> RenderResult:
    """Renders a map lit as at a time of day (seconds since midnight; None for no lighting).

    With a tick (game frames at 30 per second), texture animations are shown at that moment.
    """
    built = build_scene(repository, header, view, size, props, blocks, prop_texture_set, tick, animations, animate=False,
                        time=time, at=at)
    weather_name, fog_settings = weather_fog(repository, header, view, weather)
    image = raster.render(built.meshes, built.camera, shading=not built.lit, fog=fog_settings)
    if markers and view == 'top':
        image = draw_markers(image, repository.load(header), built.blocks, built.low, built.high)
    return RenderResult(image, [b.land_data for b in built.blocks], built.prop_count, built.missing_textures,
                        weather_name if fog_settings is not None else None)


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
             markers: bool = False, blocks: list[str] | None = None, animations: 'Animations | None' = None,
             time: int | None = lighting.NOON, at=None, weather=MAP_WEATHER) -> BakedMap:
    built = build_scene(repository, header, view, size, props, blocks, None, None, animations, animate=True, time=time,
                        at=at)
    _, fog_settings = weather_fog(repository, header, view, weather)
    static = [mesh for mesh in built.meshes if mesh.animator is None]
    animated = [mesh for mesh in built.meshes if mesh.animator is not None]
    dynamic = None
    if built.dynamic:
        builders = built.dynamic
        dynamic = lambda tick: [mesh for build in builders for mesh in build(tick)]  # noqa: E731
    overlay = None
    if markers and view == 'top':
        view_data = repository.load(header)
        overlay = lambda image: draw_markers(image, view_data, built.blocks, built.low, built.high)  # noqa: E731
    return BakedMap(raster.bake(static, animated, built.camera, shading=not built.lit, dynamic=dynamic, fog=fog_settings),
                    overlay)


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
