#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_decoder() -> None:
    path = ROOT / "scripts/schem-audit.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        origin = tuple(int(position.get(axis, 0)) for axis in ("x", "y", "z"))
        direction = tuple(1 if value >= 0 else -1 for value in signed)
        palette = region.get("BlockStatePalette") or []
''',
        '''        corner = tuple(int(position.get(axis, 0)) for axis in ("x", "y", "z"))
        region_min = tuple(
            min(corner[index], corner[index] + signed[index] + (1 if signed[index] < 0 else -1))
            for index in range(3)
        )
        palette = region.get("BlockStatePalette") or []
''',
        "negative-region origin",
    )
    text = replace_once(
        text,
        '''            pos = tuple(origin[i] + direction[i] * value for i, value in enumerate((x, y, z)))
''',
        '''            pos = tuple(region_min[i] + value for i, value in enumerate((x, y, z)))
''',
        "negative-region packed coordinate",
    )
    text = replace_once(
        text,
        '''            local = tuple(int(entity[axis]) for axis in ("x", "y", "z"))
            pos = tuple(origin[i] + direction[i] * local[i] for i in range(3))
''',
        '''            pos = tuple(int(entity[axis]) for axis in ("x", "y", "z"))
''',
        "litematic block-entity coordinate",
    )
    path.write_text(text, encoding="utf-8")


def patch_scenario() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        BlockPoint directDispenser,
        int firePulseTicks,
        boolean enforceDispenserLimit,
''',
        '''        BlockPoint directDispenser,
        int firePulseTicks,
        boolean suppressPasteSideEffects,
        int settleBeforeFillTicks,
        int fillToFireTicks,
        boolean enforceDispenserLimit,
''',
        "scenario record field order",
    )
    text = replace_once(
        text,
        '''        TargetType targetType = targetType(yaml.getString("target.type", "watered"), "target.type");
''',
        '''        boolean suppressPasteSideEffects = yaml.getBoolean("cannon.suppress-paste-side-effects", false);
        int settleBeforeFillTicks = Math.max(0, yaml.getInt("cannon.settle-before-fill-ticks", 0));
        int fillToFireTicks = Math.max(0, yaml.getInt("cannon.fill-to-fire-ticks", 0));

        TargetType targetType = targetType(yaml.getString("target.type", "watered"), "target.type");
''',
        "scenario field workflow parse",
    )
    text = replace_once(
        text,
        '''                directDispenser,
                Math.max(1, yaml.getInt("cannon.fire-pulse-ticks", 2)),
                yaml.getBoolean("limits.enforce-dispenser-limit", true),
''',
        '''                directDispenser,
                Math.max(1, yaml.getInt("cannon.fire-pulse-ticks", 2)),
                suppressPasteSideEffects,
                settleBeforeFillTicks,
                fillToFireTicks,
                yaml.getBoolean("limits.enforce-dispenser-limit", true),
''',
        "scenario field workflow constructor",
    )
    text = replace_once(
        text,
        '''    enum FireMode {
        REDSTONE,
        DIRECT_DISPENSE
    }
''',
        '''    enum FireMode {
        REDSTONE,
        BUTTON,
        DIRECT_DISPENSE
    }
''',
        "button fire mode",
    )
    path.write_text(text, encoding="utf-8")


def patch_controller() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.type.Slab;
''',
        '''import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.Powerable;
import org.bukkit.block.data.type.Slab;
''',
        "powerable import",
    )
    text = replace_once(
        text,
        '''            WorldEditService.PasteResult pasteResult = worldEdit.paste(
                    world,
                    schematic,
                    pasteOrigin,
                    false
            );
''',
        '''            WorldEditService.PasteResult pasteResult = worldEdit.paste(
                    world,
                    schematic,
                    pasteOrigin,
                    false,
                    scenario.suppressPasteSideEffects()
            );
''',
        "cannon paste side-effect mode",
    )
    text = replace_once(
        text,
        '''            FillAudit audit = auditAndFill(world, pasteResult);
''',
        '''            FillAudit audit = auditDispensers(world, pasteResult);
''',
        "separate dispenser audit",
    )
    text = replace_once(
        text,
        '''            Bukkit.getScheduler().runTaskLater(plugin, () -> {
                try {
                    fire(world, pasteOrigin);
                } catch (RuntimeException exception) {
                    plugin.getLogger().severe("Shot " + shotNumber
                            + " firing failed: " + exception.getMessage());
                    exception.printStackTrace();
                }
            }, scenario.warmupTicks());
''',
        '''            long fillDelay = scenario.settleBeforeFillTicks();
            Runnable fillAction = () -> {
                try {
                    int filled = fillDispensers(world, pasteResult);
                    plugin.getLogger().info("Filled " + filled + " dispensers after "
                            + fillDelay + " empty-settle ticks.");
                } catch (RuntimeException exception) {
                    plugin.getLogger().severe("Shot " + shotNumber
                            + " fill failed: " + exception.getMessage());
                    exception.printStackTrace();
                }
            };
            if (fillDelay == 0) {
                fillAction.run();
            } else {
                Bukkit.getScheduler().runTaskLater(plugin, fillAction, fillDelay);
            }

            long fireDelay = Math.max(
                    scenario.warmupTicks(),
                    fillDelay + scenario.fillToFireTicks()
            );
            Bukkit.getScheduler().runTaskLater(plugin, () -> {
                try {
                    fire(world, pasteOrigin);
                } catch (RuntimeException exception) {
                    plugin.getLogger().severe("Shot " + shotNumber
                            + " firing failed: " + exception.getMessage());
                    exception.printStackTrace();
                }
            }, fireDelay);
''',
        "settle fill fire schedule",
    )
    text = replace_once(
        text,
        '''        switch (scenario.fireMode()) {
            case DIRECT_DISPENSE -> dispenseDirectly(world, pasteOrigin);
            case REDSTONE -> pulseRedstone(world, pasteOrigin);
        }
''',
        '''        switch (scenario.fireMode()) {
            case DIRECT_DISPENSE -> dispenseDirectly(world, pasteOrigin);
            case BUTTON -> pressButtons(world, pasteOrigin);
            case REDSTONE -> pulseRedstone(world, pasteOrigin);
        }
''',
        "button fire switch",
    )
    button_method = '''    private void pressButtons(World world, Location pasteOrigin) {
        List<Block> buttons = new ArrayList<>();
        for (LabScenario.BlockPoint point : scenario.fireInputs()) {
            Location location = relative(pasteOrigin, point);
            Block block = world.getBlockAt(location);
            BlockData data = block.getBlockData();
            if (!(data instanceof Powerable powerable)
                    || !block.getType().name().endsWith("_BUTTON")) {
                throw new IllegalStateException("Button fire coordinate "
                        + coordinates(location) + " contains " + data.getAsString());
            }
            powerable.setPowered(true);
            recorder.recordControlEvent(
                    "FIRE_INPUT",
                    location,
                    "mode=button;pulse_ticks=" + scenario.firePulseTicks()
            );
            block.setBlockData(powerable, true);
            buttons.add(block);
        }
        if (buttons.isEmpty()) {
            throw new IllegalStateException("No button fire inputs configured.");
        }
        Bukkit.getScheduler().runTaskLater(plugin, () -> {
            for (Block block : buttons) {
                BlockData current = block.getBlockData();
                if (current instanceof Powerable powerable) {
                    powerable.setPowered(false);
                    block.setBlockData(powerable, true);
                }
            }
        }, scenario.firePulseTicks());
    }

'''
    text = replace_once(
        text,
        '''    private void pulseRedstone(World world, Location pasteOrigin) {
''',
        button_method + '''    private void pulseRedstone(World world, Location pasteOrigin) {
''',
        "button method",
    )
    text = replace_once(
        text,
        '''    private FillAudit auditAndFill(World world, WorldEditService.PasteResult result) {
''',
        '''    private FillAudit auditDispensers(World world, WorldEditService.PasteResult result) {
''',
        "audit method rename",
    )
    text = replace_once(
        text,
        '''                    dispenser.getInventory().clear();
                    for (int slot = 0; slot < dispenser.getInventory().getSize(); slot++) {
                        dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, 64));
                    }

                    int expectedTnt = dispenser.getInventory().getSize() * 64;
                    if (countTnt(dispenser) != expectedTnt) {
                        throw new IllegalStateException("TNT fill verification failed at "
                                + x + "," + y + "," + z);
                    }

                    total++;
''',
        '''                    dispenser.getInventory().clear();
                    total++;
''',
        "empty audit instead of immediate fill",
    )
    fill_method = '''    private int fillDispensers(World world, WorldEditService.PasteResult result) {
        int total = 0;
        for (int x = result.minimum().x(); x <= result.maximum().x(); x++) {
            for (int y = Math.max(world.getMinHeight(), result.minimum().y());
                 y <= Math.min(world.getMaxHeight() - 1, result.maximum().y()); y++) {
                for (int z = result.minimum().z(); z <= result.maximum().z(); z++) {
                    BlockState state = world.getBlockAt(x, y, z).getState();
                    if (!(state instanceof Dispenser dispenser)) {
                        continue;
                    }
                    dispenser.getInventory().clear();
                    for (int slot = 0; slot < dispenser.getInventory().getSize(); slot++) {
                        dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, 64));
                    }
                    int expectedTnt = dispenser.getInventory().getSize() * 64;
                    if (countTnt(dispenser) != expectedTnt) {
                        throw new IllegalStateException("TNT fill verification failed at "
                                + x + "," + y + "," + z);
                    }
                    total++;
                }
            }
        }
        return total;
    }

'''
    text = replace_once(
        text,
        '''    private int dispenserLimitPerChunk() {
''',
        fill_method + '''    private int dispenserLimitPerChunk() {
''',
        "delayed fill method",
    )
    path.write_text(text, encoding="utf-8")


def add_negative_test() -> None:
    path = ROOT / "scripts/test-negative-litematic.py"
    path.write_text('''#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("schem_audit", ROOT / "scripts/schem-audit.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

root = {
    "Version": 7,
    "MinecraftDataVersion": 3839,
    "Regions": {
        "negative-x": {
            "Position": {"x": 2, "y": 0, "z": 0},
            "Size": {"x": -3, "y": 1, "z": 1},
            "BlockStatePalette": [
                {"Name": "minecraft:stone"},
                {"Name": "minecraft:redstone_wire"},
                {"Name": "minecraft:glass"},
            ],
            "BlockStates": [36],
            "TileEntities": [],
        }
    },
}
model = module.decode_litematic(root)
assert model["source_dimensions"] == {"width": 3, "height": 1, "length": 1}, model
assert model["blocks"][(0, 0, 0)] == "minecraft:stone", model["blocks"]
assert model["blocks"][(1, 0, 0)] == "minecraft:redstone_wire", model["blocks"]
assert model["blocks"][(2, 0, 0)] == "minecraft:glass", model["blocks"]
assert model["offset"] == [0, 0, 0], model["offset"]
print("negative-region Litematica coordinate order PASS")
''', encoding="utf-8")


def main() -> None:
    patch_decoder()
    patch_scenario()
    patch_controller()
    add_negative_test()
    print("Field-parity transforms applied exactly once.")


if __name__ == "__main__":
    main()
