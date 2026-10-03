# ABOUTME: Builds renderable meshes from decoded models and texture sets, and the cameras used to view them.
# ABOUTME: Textures bind to materials by texture and palette name, as NNS_G3dBindMdlSet does in the game.

from dataclasses import dataclass

import numpy as np

from . import model as nsbmd
from . import raster
from . import textures

WHITE = np.array([[[255, 255, 255, 255]]], dtype=np.uint8)

# texImageParam wrap bits.
REPEAT_S, REPEAT_T, FLIP_S, FLIP_T = 1 << 16, 1 << 17, 1 << 18, 1 << 19


@dataclass
class Mesh:
    positions: np.ndarray    # (n, 3, 3) world space
    uvs: np.ndarray          # (n, 3, 2) in texels
    colours: np.ndarray      # (n, 3, 3) vertex colours, 0-1
    texture: np.ndarray      # (h, w, 4) RGBA
    alpha: float
    wrap: tuple              # (repeat_s, repeat_t, flip_s, flip_t)


@dataclass
class Camera:
    view_projection: np.ndarray    # row-vector world -> clip
    width: int
    height: int
    perspective: bool


class TextureLibrary:
    """Texture and palette lookups by name, decoded once."""

    def __init__(self, *texture_set_files: bytes):
        self.textures, self.palettes = {}, {}
        for data in texture_set_files:
            if data is None:
                continue
            texture_set = textures.nt.read_texture_set(data)
            for texture in texture_set.textures():
                self.textures.setdefault(texture.name, texture)
            for palette in texture_set.palettes():
                self.palettes.setdefault(palette.name, palette)
        self.cache = {}
        self.missing = set()

    def add(self, data: bytes):
        """Fills gaps from another texture set (earlier sets win)."""
        texture_set = textures.nt.read_texture_set(data)
        for texture in texture_set.textures():
            self.textures.setdefault(texture.name, texture)
        for palette in texture_set.palettes():
            self.palettes.setdefault(palette.name, palette)

    def rgba(self, texture_name: str | None, palette_name: str | None) -> np.ndarray | None:
        if texture_name is None:
            return None
        if texture_name not in self.textures:
            self.missing.add(texture_name)
            return None
        key = (texture_name, palette_name)
        if key not in self.cache:
            palette = self.palettes.get(palette_name)
            self.cache[key] = textures.decode(self.textures[texture_name], palette.data if palette else b'')
        return self.cache[key]


def meshes_from_model(model: nsbmd.Model, library: TextureLibrary, transform: np.ndarray | None = None) -> list[Mesh]:
    meshes = []
    for draw in model.draws:
        material = model.materials[draw.material] if draw.material < len(model.materials) else nsbmd.Material('none')
        texture = library.rgba(material.texture, material.palette)
        param = material.tex_image_param
        wrap = (bool(param & REPEAT_S), bool(param & REPEAT_T), bool(param & FLIP_S), bool(param & FLIP_T))
        positions, uvs, colours = [], [], []
        for primitive in draw.primitives:
            for a, b, c in primitive.triangles():
                positions.append(primitive.positions[[a, b, c]])
                uvs.append(primitive.uvs[[a, b, c]])
                colours.append(primitive.colours[[a, b, c]])
        if not positions:
            continue
        positions = np.array(positions)
        if transform is not None:
            ones = np.ones(positions.shape[:2] + (1,))
            positions = (np.concatenate([positions, ones], axis=2) @ transform)[..., :3]
        meshes.append(Mesh(positions, np.array(uvs), np.array(colours), texture if texture is not None else WHITE,
                           material.alpha if material.alpha > 0 else 1.0, wrap if texture is not None else (False,) * 4))
    return meshes


def bounds(meshes: list[Mesh]) -> tuple[np.ndarray, np.ndarray]:
    points = np.concatenate([mesh.positions.reshape(-1, 3) for mesh in meshes])
    return points.min(axis=0), points.max(axis=0)


def image_size(extent_x: float, extent_y: float, size: int) -> tuple[int, int]:
    if extent_x >= extent_y:
        return size, max(1, round(size * extent_y / max(extent_x, 1e-9)))
    return max(1, round(size * extent_x / max(extent_y, 1e-9))), size


def top_camera(low: np.ndarray, high: np.ndarray, size: int) -> Camera:
    """Orthographic, looking straight down; north (low z) at the top of the image."""
    width, height = image_size(high[0] - low[0], high[2] - low[2], size)
    sx = 2 / max(high[0] - low[0], 1e-9)
    sz = 2 / max(high[2] - low[2], 1e-9)
    sy = 1 / max(high[1] - low[1], 1e-9)
    m = np.zeros((4, 4))
    m[0, 0] = sx                 # clip x from world x
    m[2, 1] = -sz                # clip y from world z (north up)
    m[1, 2] = -sy                # clip z: higher is nearer
    m[3] = [-1 - low[0] * sx, 1 + low[2] * sz, high[1] * sy, 1]
    return Camera(m, width, height, perspective=False)


def look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    view = np.eye(4)
    view[:3, 0], view[:3, 1], view[:3, 2] = right, up, -forward
    view[3, :3] = [-right @ eye, -up @ eye, forward @ eye]
    return view


def angled_camera(low: np.ndarray, high: np.ndarray, size: int, pitch_degrees: float = 40.0,
                  fov_degrees: float = 30.0) -> Camera:
    """Perspective from the south, looking down at pitch_degrees, like the overworld camera."""
    centre = (low + high) / 2
    radius = np.linalg.norm(high - low) / 2
    distance = radius / np.sin(np.radians(fov_degrees) / 2) * 1.05
    pitch = np.radians(pitch_degrees)
    eye = centre + distance * np.array([0.0, np.sin(pitch), np.cos(pitch)])
    view = look_at(eye, centre)
    near, far = max(distance - radius * 1.5, 0.1), distance + radius * 1.5
    f = 1 / np.tan(np.radians(fov_degrees) / 2)
    projection = np.zeros((4, 4))
    projection[0, 0] = f
    projection[1, 1] = f
    projection[2, 2] = (far + near) / (near - far)
    projection[2, 3] = -1
    projection[3, 2] = 2 * far * near / (near - far)

    # Zoom so the bounding box's corners just fit, instead of its (looser) bounding sphere.
    corners = np.array([[x, y, z, 1.0] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
    clip = corners @ view @ projection
    ndc = clip[:, :2] / clip[:, 3:4]
    shift = (ndc.max(axis=0) + ndc.min(axis=0)) / 2
    extent = (ndc.max(axis=0) - ndc.min(axis=0)).max() / 2 * 1.04
    return Camera(view @ projection @ ndc_fit(shift, extent), size, size, perspective=True)


def ndc_fit(shift: np.ndarray, extent: float) -> np.ndarray:
    """Clip-space matrix giving ndc' = (ndc - shift) / extent; row 3 scales the incoming clip w."""
    m = np.eye(4)
    m[0, 0] = m[1, 1] = 1 / extent
    m[3, 0], m[3, 1] = -shift / extent
    return m


def camera_for(meshes: list[Mesh], view: str, size: int) -> Camera:
    low, high = bounds(meshes)
    if view == 'top':
        return top_camera(low, high, size)
    if view == 'angled':
        return angled_camera(low, high, size)
    raise ValueError(f"view must be 'top' or 'angled', not {view!r}")


def render_model(model_data: bytes, *texture_sets: bytes, view: str = 'angled', size: int = 512,
                 shading: bool = True, use_embedded: bool = True, textured: bool = True,
                 library: TextureLibrary | None = None) -> np.ndarray:
    """RGBA image of one model, textured from the given texture sets.

    The game ignores a prop's embedded textures and binds from the area's set; use_embedded=False
    reproduces that (missing textures render white). With it on, the model's own textures fill gaps,
    which is what you want when previewing a model before it is registered in an area.
    """
    model = nsbmd.load_model(model_data)
    embedded = model_data if use_embedded and textures.nt.find_tex0(model_data) is not None else None
    if not textured:
        library = TextureLibrary()
    elif library is None:
        library = TextureLibrary(*texture_sets, embedded)
    elif embedded is not None:
        library.add(embedded)
    meshes = meshes_from_model(model, library)
    if not meshes:
        raise ValueError('the model draws nothing')
    return raster.render(meshes, camera_for(meshes, view, size), shading=shading)
