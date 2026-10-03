# ABOUTME: A small numpy triangle rasteriser: z-buffer, perspective-correct texturing, wrap modes, translucency.
# ABOUTME: Opaque texels are drawn first with depth writes; translucent ones are blended far-to-near afterwards.

import numpy as np

LIGHT = np.array([-0.4, 1.0, 0.6]) / np.linalg.norm([-0.4, 1.0, 0.6])
ALPHA_DISCARD = 8 / 255
OPAQUE = 254 / 255


def project(camera, points: np.ndarray):
    """World points (n, 3) -> pixel x, pixel y, depth, 1/w."""
    clip = np.concatenate([points, np.ones((len(points), 1))], axis=1) @ camera.view_projection
    w = clip[:, 3] if camera.perspective else np.ones(len(points))
    ndc = clip[:, :3] / w[:, None]
    x = (ndc[:, 0] + 1) / 2 * camera.width
    y = (1 - ndc[:, 1]) / 2 * camera.height
    return x, y, ndc[:, 2], 1 / w


def wrap_coordinate(values: np.ndarray, size: int, repeat: bool, flip: bool) -> np.ndarray:
    texel = np.floor(values).astype(np.int64)
    if not repeat:
        return np.clip(texel, 0, size - 1)
    if flip:
        period = texel % (2 * size)
        return np.where(period < size, period, 2 * size - 1 - period)
    return texel % size


def shade(positions: np.ndarray) -> float:
    normal = np.cross(positions[1] - positions[0], positions[2] - positions[0])
    length = np.linalg.norm(normal)
    if length == 0:
        return 1.0
    return 0.7 + 0.3 * abs(normal @ LIGHT) / length


def render(meshes, camera, shading: bool = True, background=(0, 0, 0, 0)) -> np.ndarray:
    colour = np.zeros((camera.height, camera.width, 4), dtype=float)
    colour[:] = np.array(background, dtype=float) / 255
    depth = np.full((camera.height, camera.width), np.inf)

    triangles = []
    for mesh in meshes:
        for index in range(len(mesh.positions)):
            triangles.append((mesh, index))

    # Opaque pass, then translucent texels far-to-near.
    for mesh, index in triangles:
        draw_triangle(colour, depth, camera, mesh, index, shading, translucent=False)
    centres = [project(camera, mesh.positions[index])[2].mean() for mesh, index in triangles]
    for order in np.argsort(centres)[::-1]:
        mesh, index = triangles[order]
        draw_triangle(colour, depth, camera, mesh, index, shading, translucent=True)

    return np.clip(np.round(colour * 255), 0, 255).astype(np.uint8)


def draw_triangle(colour, depth, camera, mesh, index, shading: bool, translucent: bool):
    positions = mesh.positions[index]
    x, y, z, inv_w = project(camera, positions)
    if not np.all(np.isfinite(x)) or np.any(inv_w <= 0):
        return
    x0, x1 = max(int(np.floor(x.min())), 0), min(int(np.ceil(x.max())), camera.width - 1)
    y0, y1 = max(int(np.floor(y.min())), 0), min(int(np.ceil(y.max())), camera.height - 1)
    if x0 > x1 or y0 > y1:
        return

    area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
    if abs(area) < 1e-12:
        return
    px, py = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    w0 = ((x[1] - px) * (y[2] - py) - (x[2] - px) * (y[1] - py)) / area
    w1 = ((x[2] - px) * (y[0] - py) - (x[0] - px) * (y[2] - py)) / area
    w2 = 1 - w0 - w1
    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not inside.any():
        return

    pixel_depth = w0 * z[0] + w1 * z[1] + w2 * z[2]
    region_depth = depth[y0:y1 + 1, x0:x1 + 1]
    visible = inside & (pixel_depth < region_depth)
    if not visible.any():
        return

    # Perspective-correct interpolation of texture coordinates and vertex colours.
    pw = w0 * inv_w[0] + w1 * inv_w[1] + w2 * inv_w[2]
    weights = [w * inv_w[i] / pw for i, w in enumerate((w0, w1, w2))]
    uv = sum(weights[i][..., None] * mesh.uvs[index][i] for i in range(3))
    vertex_colour = sum(weights[i][..., None] * mesh.colours[index][i] for i in range(3))

    texture = mesh.texture
    height, width = texture.shape[:2]
    repeat_s, repeat_t, flip_s, flip_t = mesh.wrap
    s = wrap_coordinate(uv[..., 0], width, repeat_s, flip_s)
    t = wrap_coordinate(uv[..., 1], height, repeat_t, flip_t)
    texel = texture[t, s].astype(float) / 255

    rgb = texel[..., :3] * vertex_colour * (shade(positions) if shading else 1.0)
    alpha = texel[..., 3] * mesh.alpha

    if translucent:
        mask = visible & (alpha > ALPHA_DISCARD) & (alpha < OPAQUE)
        if not mask.any():
            return
        region = colour[y0:y1 + 1, x0:x1 + 1]
        a = alpha[mask][:, None]
        region[mask, :3] = rgb[mask] * a + region[mask, :3] * (1 - a)
        region[mask, 3] = alpha[mask] + region[mask, 3] * (1 - alpha[mask])
    else:
        mask = visible & (alpha >= OPAQUE)
        if not mask.any():
            return
        region = colour[y0:y1 + 1, x0:x1 + 1]
        region[mask, :3] = rgb[mask]
        region[mask, 3] = 1.0
        region_depth[mask] = pixel_depth[mask]
