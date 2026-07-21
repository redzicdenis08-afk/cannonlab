#!/usr/bin/env python3
from __future__ import annotations

import gzip
import io
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

END, BYTE, SHORT, INT, LONG, FLOAT, DOUBLE, BYTE_ARRAY, STRING, LIST, COMPOUND, INT_ARRAY, LONG_ARRAY = range(13)

AIR = "minecraft:air"
OBSIDIAN = "minecraft:obsidian"
SMOOTH_STONE = "minecraft:smooth_stone"
CYAN_CONCRETE = "minecraft:cyan_concrete"
WIRE = "minecraft:redstone_wire[east=side,north=side,power=0,south=side,west=side]"
WATER_STOP = "minecraft:oak_trapdoor[facing=north,half=bottom,open=true,powered=false,waterlogged=false]"
FIRE_BUTTON = "minecraft:stone_button[face=floor,facing=north,powered=false]"


def water(level: int) -> str:
    if not 0 <= level <= 7:
        raise ValueError(f"invalid flowing-water level: {level}")
    return f"minecraft:water[level={level}]"


def dispenser(facing: str) -> str:
    return f"minecraft:dispenser[facing={facing},triggered=false]"


def repeater(output_direction: str, delay: int = 1) -> str:
    if delay not in {1, 2, 3, 4}:
        raise ValueError(f"invalid repeater delay: {delay}")
    blockstate_facing = {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
    }[output_direction]
    return (
        "minecraft:repeater["
        f"delay={delay},facing={blockstate_facing},locked=false,powered=false]"
    )


def _write_string(stream: io.BytesIO, value: str) -> None:
    encoded = value.encode("utf-8")
    stream.write(struct.pack(">H", len(encoded)))
    stream.write(encoded)


def _write_payload(stream: io.BytesIO, tag: int, value: Any) -> None:
    if tag == BYTE:
        stream.write(struct.pack(">b", int(value)))
    elif tag == SHORT:
        stream.write(struct.pack(">h", int(value)))
    elif tag == INT:
        stream.write(struct.pack(">i", int(value)))
    elif tag == LONG:
        stream.write(struct.pack(">q", int(value)))
    elif tag == FLOAT:
        stream.write(struct.pack(">f", float(value)))
    elif tag == DOUBLE:
        stream.write(struct.pack(">d", float(value)))
    elif tag == BYTE_ARRAY:
        data = bytes(value)
        stream.write(struct.pack(">i", len(data)))
        stream.write(data)
    elif tag == STRING:
        _write_string(stream, str(value))
    elif tag == LIST:
        child_tag, values = value
        stream.write(struct.pack(">B", child_tag))
        stream.write(struct.pack(">i", len(values)))
        for child in values:
            _write_payload(stream, child_tag, child)
    elif tag == COMPOUND:
        for name, (child_tag, child_value) in value.items():
            stream.write(struct.pack(">B", child_tag))
            _write_string(stream, name)
            _write_payload(stream, child_tag, child_value)
        stream.write(struct.pack(">B", END))
    elif tag == INT_ARRAY:
        stream.write(struct.pack(">i", len(value)))
        for item in value:
            stream.write(struct.pack(">i", int(item)))
    elif tag == LONG_ARRAY:
        stream.write(struct.pack(">i", len(value)))
        for item in value:
            stream.write(struct.pack(">q", int(item)))
    else:
        raise ValueError(f"unsupported NBT tag: {tag}")


def _named_root(name: str, compound: dict[str, tuple[int, Any]]) -> bytes:
    stream = io.BytesIO()
    stream.write(struct.pack(">B", COMPOUND))
    _write_string(stream, name)
    _write_payload(stream, COMPOUND, compound)
    return stream.getvalue()


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative palette id")
    encoded = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        if value:
            part |= 0x80
        encoded.append(part)
        if not value:
            return bytes(encoded)


@dataclass
class Schematic:
    width: int
    height: int
    length: int
    blocks: dict[tuple[int, int, int], str] = field(default_factory=dict)
    block_entities: dict[tuple[int, int, int], dict[str, tuple[int, Any]]] = field(default_factory=dict)

    def set(self, x: int, y: int, z: int, state: str) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length):
            raise ValueError(f"block outside bounds: {(x, y, z)} in {(self.width, self.height, self.length)}")
        self.blocks[(x, y, z)] = state
        if not state.startswith("minecraft:dispenser["):
            self.block_entities.pop((x, y, z), None)

    def fill(self, minimum: tuple[int, int, int], maximum: tuple[int, int, int], state: str) -> None:
        min_x, min_y, min_z = minimum
        max_x, max_y, max_z = maximum
        for y in range(min_y, max_y + 1):
            for z in range(min_z, max_z + 1):
                for x in range(min_x, max_x + 1):
                    self.set(x, y, z, state)

    def add_dispenser(self, x: int, y: int, z: int, facing: str) -> None:
        self.set(x, y, z, dispenser(facing))
        self.block_entities[(x, y, z)] = {
            "Pos": (INT_ARRAY, [x, y, z]),
            "Id": (STRING, "minecraft:dispenser"),
            "Items": (LIST, (COMPOUND, [])),
        }

    def write(self, path: Path) -> None:
        states = {AIR, *self.blocks.values()}
        ordered_states = [AIR] + sorted(state for state in states if state != AIR)
        palette = {state: index for index, state in enumerate(ordered_states)}

        block_data = bytearray()
        for y in range(self.height):
            for z in range(self.length):
                for x in range(self.width):
                    state = self.blocks.get((x, y, z), AIR)
                    block_data.extend(_varint(palette[state]))

        entities = [
            self.block_entities[position]
            for position in sorted(self.block_entities, key=lambda item: (item[1], item[2], item[0]))
        ]
        root = {
            "Metadata": (
                COMPOUND,
                {
                    "WEOffsetX": (INT, 0),
                    "WEOffsetY": (INT, 0),
                    "WEOffsetZ": (INT, 0),
                },
            ),
            "Palette": (COMPOUND, {state: (INT, index) for state, index in palette.items()}),
            "BlockEntities": (LIST, (COMPOUND, entities)),
            "DataVersion": (INT, 3465),
            "Height": (SHORT, self.height),
            "Length": (SHORT, self.length),
            "PaletteMax": (INT, len(palette)),
            "Version": (INT, 2),
            "Width": (SHORT, self.width),
            "BlockData": (BYTE_ARRAY, bytes(block_data)),
            "Offset": (INT_ARRAY, [0, 0, 0]),
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(_named_root("Schematic", root), compresslevel=9, mtime=0))

    def dispenser_count(self) -> int:
        return sum(1 for state in self.blocks.values() if state.startswith("minecraft:dispenser["))


def support(schematic: Schematic, x: int, y: int, z: int, state: str = SMOOTH_STONE) -> None:
    schematic.set(x, y - 1, z, state)


def dust(schematic: Schematic, x: int, y: int, z: int) -> None:
    if y < 1:
        raise ValueError("redstone dust requires support")
    if (x, y - 1, z) not in schematic.blocks:
        schematic.set(x, y - 1, z, SMOOTH_STONE)
    schematic.set(x, y, z, WIRE)


def repeat(schematic: Schematic, x: int, y: int, z: int, facing: str, delay: int = 1) -> None:
    support(schematic, x, y, z)
    schematic.set(x, y, z, repeater(facing, delay))


def north_flow(
    schematic: Schematic,
    x_min: int,
    x_max: int,
    y: int,
    front_z: int,
    source_z: int,
) -> None:
    if source_z - front_z > 7:
        raise ValueError("a flat water stream cannot exceed seven blocks from source")
    for z in range(front_z, source_z + 1):
        level = source_z - z
        schematic.fill((x_min, y, z), (x_max, y, z), water(level))


def build_streambreach() -> tuple[Schematic, list[tuple[int, int, int]]]:
    schematic = Schematic(width=28, height=8, length=27)
    channels = tuple(range(1, 16, 2))

    schematic.fill((0, 3, 0), (16, 3, 24), OBSIDIAN)
    schematic.fill((0, 4, 7), (0, 5, 24), OBSIDIAN)
    schematic.fill((16, 4, 7), (16, 5, 24), OBSIDIAN)
    schematic.fill((0, 4, 24), (16, 5, 24), OBSIDIAN)
    schematic.fill((1, 4, 8), (15, 4, 23), water(0))
    schematic.fill((1, 4, 7), (15, 4, 7), WATER_STOP)

    for x in channels:
        for z in range(10, 24):
            schematic.add_dispenser(x, 5, z, "down")
            dust(schematic, x, 6, z)
        repeat(schematic, x, 6, 24, "north", 1)

        schematic.add_dispenser(x, 5, 7, "north")

    for x in range(1, 17):
        dust(schematic, x, 6, 25)

    delay_values = [4, 4, 4, 4, 4, 4, 4, 2]
    for offset, delay in enumerate(delay_values):
        repeat(schematic, 18 + offset, 6, 25, "east", delay)

    for z in range(25, 16, -1):
        dust(schematic, 26, 6, z)
    repeat(schematic, 26, 6, 16, "north", 1)
    for z in range(15, 8, -1):
        dust(schematic, 26, 6, z)

    for x in range(26, 17, -1):
        dust(schematic, x, 6, 9)
    repeat(schematic, 17, 6, 9, "west", 1)
    for x in range(16, 7, -1):
        dust(schematic, x, 6, 9)
    repeat(schematic, 8, 6, 8, "north", 1)
    for x in range(1, 16):
        dust(schematic, x, 6, 7)

    schematic.set(17, 5, 25, SMOOTH_STONE)
    schematic.set(17, 5, 26, "minecraft:cyan_concrete")
    fire_inputs = [(17, 6, 25)]

    assert schematic.dispenser_count() == 120
    return schematic, fire_inputs


def build_pocketcounter() -> tuple[Schematic, list[tuple[int, int, int]]]:
    schematic = Schematic(width=16, height=8, length=16)
    channels = (1, 3, 5, 7)

    schematic.fill((0, 3, 0), (9, 3, 14), OBSIDIAN)
    schematic.fill((0, 4, 0), (0, 5, 14), OBSIDIAN)
    schematic.fill((8, 4, 0), (8, 5, 14), OBSIDIAN)
    schematic.fill((0, 4, 14), (8, 5, 14), OBSIDIAN)
    north_flow(schematic, 1, 7, 4, front_z=7, source_z=13)
    schematic.fill((1, 4, 6), (7, 4, 6), WATER_STOP)

    for x in channels:
        for z in range(9, 14):
            schematic.add_dispenser(x, 5, z, "down")
            dust(schematic, x, 6, z)
        repeat(schematic, x, 6, 14, "north", 1)

        schematic.add_dispenser(x, 5, 6, "north")

    for x in range(1, 9):
        dust(schematic, x, 6, 15)

    first_row = [1, 1, 1, 1]
    second_row = [1, 1, 1, 1]
    for offset, delay in enumerate(first_row):
        repeat(schematic, 10 + offset, 6, 15, "east", delay)
    dust(schematic, 14, 6, 15)
    dust(schematic, 15, 6, 15)
    dust(schematic, 15, 6, 14)
    for offset, delay in enumerate(second_row):
        repeat(schematic, 14 - offset, 6, 14, "west", delay)

    dust(schematic, 10, 6, 14)
    for z in range(13, 7, -1):
        dust(schematic, 10, 6, z)
    repeat(schematic, 10, 6, 7, "north", 1)
    dust(schematic, 10, 6, 6)
    repeat(schematic, 9, 6, 6, "west", 1)
    for x in range(1, 9):
        dust(schematic, x, 6, 6)

    # The pasted cannon is immediately usable: the cyan block is the exact
    # fire-control support and the stone button above it feeds both branches.
    # West starts the one-tick charge path; east starts the ten-tick payload path.
    schematic.set(9, 5, 15, CYAN_CONCRETE)
    schematic.set(9, 6, 15, FIRE_BUTTON)
    fire_inputs = [(9, 6, 15)]

    assert schematic.dispenser_count() == 24
    assert schematic.blocks[fire_inputs[0]] == FIRE_BUTTON
    return schematic, fire_inputs


def build_saturation_plate(layers: int) -> tuple[Schematic, list[tuple[int, int, int]]]:
    if layers not in {8, 16}:
        raise ValueError("supported saturation layers are 8 and 16")
    schematic = Schematic(width=16, height=layers * 2 + 2, length=10)
    fire_inputs: list[tuple[int, int, int]] = []
    for layer in range(layers):
        dispenser_y = 1 + layer * 2
        wire_y = dispenser_y + 1
        for x in range(15):
            schematic.add_dispenser(x, dispenser_y, 8, "north")
            dust(schematic, x, wire_y, 8)
        schematic.set(15, dispenser_y, 8, SMOOTH_STONE)
        schematic.set(15, wire_y - 1, 9, "minecraft:lime_concrete")
        fire_inputs.append((15, wire_y, 8))
    assert schematic.dispenser_count() == layers * 15
    return schematic, fire_inputs


def emit() -> None:
    root = Path(__file__).resolve().parents[1]
    cannon_dir = root / "cannons"

    builds = {
        "ec-streambreach-120.schem": build_streambreach(),
        "ec-pocketcounter-24.schem": build_pocketcounter(),
        "ec-satplate-legal-120.schem": build_saturation_plate(8),
        "ec-satplate-overcap-240.schem": build_saturation_plate(16),
    }
    for name, (schematic, _inputs) in builds.items():
        output = cannon_dir / name
        schematic.write(output)
        print(
            f"generated {output.relative_to(root)} "
            f"dims={schematic.width}x{schematic.height}x{schematic.length} "
            f"dispensers={schematic.dispenser_count()} blockEntities={len(schematic.block_entities)}"
        )


if __name__ == "__main__":
    emit()
