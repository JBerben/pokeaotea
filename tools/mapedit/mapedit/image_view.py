# ABOUTME: An image widget for the terminal: real pixels via Sixel or the Kitty graphics protocol when the terminal
# ABOUTME: supports them (through textual-image), otherwise two pixels per cell with the upper half block.

import numpy as np
from PIL import Image, ImageDraw
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget

# textual-image asks the terminal what it supports when it is imported, which has to happen before Textual
# takes the terminal over - importing this module early (app.py does) is what makes 'auto' work.
from textual_image import renderable as detected
from textual_image.widget import SixelImage, TGPImage, get_cell_size

UPPER_HALF = '▀'
BACKGROUND = (30, 30, 30)
MODES = ('auto', 'sixel', 'kitty', 'halfblock')


def choose_mode(mode: str) -> str:
    """The concrete graphics mode for a requested one; auto picks what the terminal reported."""
    if mode not in MODES:
        raise ValueError(f"graphics mode must be one of {', '.join(MODES)}, not {mode!r}")
    if mode != 'auto':
        return mode
    if detected.Image is detected.SixelImage:
        return 'sixel'
    if detected.Image is detected.TGPImage:
        return 'kitty'
    return 'halfblock'


def cell_size() -> tuple[int, int]:
    """Pixels per character cell, as the terminal reports it (textual-image falls back to 10x20)."""
    size = get_cell_size()
    return size.width, size.height


def fit_pixels(image: np.ndarray, width: int, height: int) -> np.ndarray:
    """Scales an RGBA image to fit width x height pixels, keeping its aspect ratio."""
    image_height, image_width = image.shape[:2]
    scale = min(width / image_width, height / image_height)
    size = (max(1, int(image_width * scale)), max(1, int(image_height * scale)))
    resample = Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.BOX
    return np.array(Image.fromarray(image).resize(size, resample))


def fit(image: np.ndarray, columns: int, rows: int) -> np.ndarray:
    """Scales an RGBA image to fit columns x (2 * rows) half-block pixels."""
    return fit_pixels(image, columns, 2 * rows)


def composite(image: np.ndarray, background) -> np.ndarray:
    alpha = image[..., 3:4].astype(float) / 255
    return (image[..., :3] * alpha + np.array(background) * (1 - alpha)).astype(np.uint8)


def to_text(image: np.ndarray, background=BACKGROUND) -> Text:
    rgb = composite(image, background)
    if rgb.shape[0] % 2:
        rgb = np.concatenate([rgb, np.full((1,) + rgb.shape[1:], background, dtype=np.uint8)])
    text = Text()
    for row in range(0, rgb.shape[0], 2):
        for top, bottom in zip(rgb[row], rgb[row + 1]):
            text.append(UPPER_HALF, Style(color=f'rgb({top[0]},{top[1]},{top[2]})',
                                          bgcolor=f'rgb({bottom[0]},{bottom[1]},{bottom[2]})'))
        text.append('\n')
    return text


def outline(image: np.ndarray, rectangle, scale: float) -> np.ndarray:
    x0, y0, x1, y1 = (round(v * scale) for v in rectangle)
    picture = Image.fromarray(image)
    ImageDraw.Draw(picture).rectangle((x0, y0, max(x1, x0), max(y1, y0)), outline=(255, 255, 0, 255))
    return np.array(picture)


class ImageView(Widget):
    """Shows an RGBA image scaled to fit, with an optional rectangle outlined on top."""

    DEFAULT_CSS = """
    ImageView { height: 1fr; }
    ImageView > SixelImage, ImageView > TGPImage { width: auto; height: auto; }
    """

    def __init__(self, mode: str = 'auto', **kwargs):
        super().__init__(**kwargs)
        self.mode = choose_mode(mode)
        self.image = None
        self.highlight = None          # (x0, y0, x1, y1) in source image pixels

    def compose(self) -> ComposeResult:
        if self.mode == 'sixel':
            yield SixelImage()
        elif self.mode == 'kitty':
            yield TGPImage()

    @property
    def backend(self):
        return self.query_one(SixelImage if self.mode == 'sixel' else TGPImage) if self.mode != 'halfblock' else None

    def pixel_size(self) -> tuple[int, int]:
        """Pixels the widget can show: real pixels in Sixel/Kitty modes, two per cell vertically otherwise."""
        columns, rows = max(self.size.width, 1), max(self.size.height, 1)
        if self.mode == 'halfblock':
            return columns, 2 * rows
        width, height = cell_size()
        return columns * width, rows * height

    def set_image(self, image: np.ndarray):
        self.image = image
        self.redraw()

    def set_highlight(self, rectangle):
        if rectangle != self.highlight:
            self.highlight = rectangle
            self.redraw()

    def shown(self) -> np.ndarray | None:
        """The image as drawn: fitted to the widget, then outlined (so the outline stays crisp)."""
        if self.image is None:
            return None
        fitted = fit_pixels(self.image, *self.pixel_size())
        if self.highlight is not None:
            fitted = outline(fitted, self.highlight, fitted.shape[1] / self.image.shape[1])
        return fitted

    def redraw(self):
        if self.mode != 'halfblock' and self.is_mounted and self.image is not None:
            shown = self.shown()
            picture = Image.fromarray(composite(shown, BACKGROUND))
            width, height = cell_size()
            backend = self.backend
            backend.styles.width = max(1, round(picture.width / width))
            backend.styles.height = max(1, round(picture.height / height))
            backend.image = picture
        self.refresh()

    def on_resize(self):
        self.redraw()

    def render(self):
        if self.mode != 'halfblock':
            return ''
        shown = self.shown()
        if shown is None:
            return Text('Rendering…', style='italic')
        return to_text(shown)
