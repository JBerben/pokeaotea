# ABOUTME: DS-style per-vertex lighting from the field's area lighting sets (res/field/lighting), by time of day.
# ABOUTME: Slot choice follows AreaLightManager_New; the colour sum follows the DS geometry engine's lighting.

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LIGHTING_SETS = Path('res/field/lighting')
# AreaDataManager_IsOutdoorsLighting: these sets also replace every material's reflection colours.
OUTDOOR_SETS = {'lighting_set_000', 'lighting_set_003'}
NOON = 12 * 3600


@dataclass
class Light:
    colour: np.ndarray       # 0-1
    direction: np.ndarray    # the direction light travels, world space


@dataclass
class Reflection:
    diffuse: np.ndarray
    ambient: np.ndarray
    specular: np.ndarray
    emission: np.ndarray


@dataclass
class Slot:
    end_time: int            # 2-second units since midnight
    lights: list             # four entries, None where disabled
    reflection: Reflection


@dataclass
class LightingSet:
    name: str
    slots: list

    @property
    def outdoor(self) -> bool:
        return self.name in OUTDOOR_SETS

    def slot_index(self, seconds: int) -> int:
        """The slot the game uses at a time: the first whose end time is later (AreaLightManager_New)."""
        now = seconds // 2
        for index, slot in enumerate(self.slots):
            if slot.end_time > now:
                return index
        return 0

    def slot_at(self, seconds: int) -> Slot:
        return self.slots[self.slot_index(seconds)]


def colour(value: dict) -> np.ndarray:
    return np.array([value['red'], value['green'], value['blue']], dtype=float) / 31


def load_set(root: Path, name: str) -> LightingSet:
    slots = []
    for entry in json.loads((Path(root) / LIGHTING_SETS / f'{name}.json').read_text(encoding='utf-8')):
        lights = []
        for light in entry['lights']:
            direction = np.array([light['direction'][axis] for axis in 'xyz'], dtype=float)
            lights.append(Light(colour(light['color']), direction) if light['enabled'] else None)
        reflection = Reflection(colour(entry['diffuseColor']), colour(entry['ambientColor']),
                                colour(entry['specularColor']), colour(entry['emissionColor']))
        slots.append(Slot(entry['endTime'], lights, reflection))
    return LightingSet(name, slots)


def parse_time(text: str) -> int:
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', text.strip())
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise ValueError(f'time must be HH:MM (24-hour), not {text!r}')
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60


def format_time(seconds: int) -> str:
    return f'{seconds // 3600:02}:{seconds % 3600 // 60:02}'


def vertex_colours(normals: np.ndarray, reflection: Reflection, lights: list, light_mask: int, view: np.ndarray) -> np.ndarray:
    """Lit vertex colours: emission + sum over enabled lights of light * (ambient + diffuse * d + specular * s)."""
    colours = np.tile(reflection.emission, (len(normals), 1))
    for index, light in enumerate(lights):
        if light is None or not light_mask & (1 << index):
            continue
        diffuse_level = np.clip(-(normals @ light.direction), 0, 1)
        half = (light.direction + view) / 2
        shininess = np.clip(-(normals @ half), 0, 1) ** 2
        colours += light.colour * (reflection.ambient + reflection.diffuse * diffuse_level[:, None]
                                   + reflection.specular * shininess[:, None])
    return np.clip(colours, 0, 1)


@dataclass
class Environment:
    """What lights a scene: the slot's lights, and its reflection colours when the area overrides materials."""

    lights: list
    reflection_override: Reflection | None
    view: np.ndarray


def environment(root: Path, set_name: str, seconds: int, view=(0.0, -1.0, 0.0)) -> Environment:
    lighting_set = load_set(root, set_name)
    slot = lighting_set.slot_at(seconds)
    return Environment(slot.lights, slot.reflection if lighting_set.outdoor else None, np.array(view, dtype=float))
