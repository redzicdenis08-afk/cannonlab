#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java"
text = path.read_text(encoding="utf-8")
text = text.replace("import org.bukkit.block.data.Powerable;\n", "", 1)
old = '''    private void pressButtons(World world, Location pasteOrigin) {
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
new = '''    private void pressButtons(World world, Location pasteOrigin) {
        int pressed = 0;
        for (LabScenario.BlockPoint point : scenario.fireInputs()) {
            Location location = relative(pasteOrigin, point);
            Block block = world.getBlockAt(location);
            BlockData data = block.getBlockData();
            if (!block.getType().name().endsWith("_BUTTON")) {
                throw new IllegalStateException("Button fire coordinate "
                        + coordinates(location) + " contains " + data.getAsString());
            }
            recorder.recordControlEvent(
                    "FIRE_INPUT",
                    location,
                    "mode=button;implementation=native-button-block"
            );
            pressNativeButton(block);
            pressed++;
        }
        if (pressed == 0) {
            throw new IllegalStateException("No button fire inputs configured.");
        }
    }

    private void pressNativeButton(Block block) {
        try {
            Class<?> craftBlockClass = Class.forName("org.bukkit.craftbukkit.block.CraftBlock");
            Class<?> buttonBlockClass = Class.forName("net.minecraft.world.level.block.ButtonBlock");
            if (!craftBlockClass.isInstance(block)) {
                throw new IllegalStateException("Unsupported Bukkit block implementation: "
                        + block.getClass().getName());
            }

            Object state = craftBlockClass.getMethod("getBlockState").invoke(block);
            Object nmsBlock = state.getClass().getMethod("getBlock").invoke(state);
            if (!buttonBlockClass.isInstance(nmsBlock)) {
                throw new IllegalStateException("Block is not backed by ButtonBlock: "
                        + nmsBlock.getClass().getName());
            }
            Object level = craftBlockClass.getMethod("getLevel").invoke(block);
            Object position = craftBlockClass.getMethod("getPosition").invoke(block);

            java.lang.reflect.Method press = null;
            for (java.lang.reflect.Method candidate : buttonBlockClass.getMethods()) {
                if (candidate.getName().equals("press") && candidate.getParameterCount() == 4) {
                    press = candidate;
                    break;
                }
            }
            if (press == null) {
                throw new NoSuchMethodException("ButtonBlock.press(BlockState, Level, BlockPos, Player)");
            }
            press.invoke(nmsBlock, state, level, position, null);
            plugin.getLogger().info("Native button press at " + coordinates(block.getLocation()));
        } catch (ReflectiveOperationException exception) {
            Throwable cause = exception instanceof java.lang.reflect.InvocationTargetException
                    && exception.getCause() != null
                    ? exception.getCause()
                    : exception;
            throw new IllegalStateException("Unable to invoke native button press at "
                    + coordinates(block.getLocation()) + ": " + cause, cause);
        }
    }
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one old button implementation, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Native ButtonBlock.press reflection installed.")
