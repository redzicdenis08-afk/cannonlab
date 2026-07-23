from pathlib import Path


def one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


scenario = Path("src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java")
text = scenario.read_text()
text = one(
    text,
    "        List<BlockPoint> fireInputs,\n        BlockPoint directDispenser,",
    "        List<BlockPoint> fireInputs,\n        List<BlockPoint> fillDispensers,\n        BlockPoint directDispenser,",
    "record fill field",
)
text = one(
    text,
    "        fireInputs = List.copyOf(fireInputs);\n        targetStages = List.copyOf(targetStages);",
    "        fireInputs = List.copyOf(fireInputs);\n        fillDispensers = List.copyOf(fillDispensers);\n        targetStages = List.copyOf(targetStages);",
    "immutable fill list",
)
text = one(
    text,
    "        BlockPoint directDispenser = point(\n",
    "        List<BlockPoint> fillDispensers = points(yaml, \"cannon.fill-dispensers\");\n"
    "        BlockPoint directDispenser = point(\n",
    "parse fill list",
)
text = one(
    text,
    "                fireInputs,\n                directDispenser,",
    "                fireInputs,\n                fillDispensers,\n                directDispenser,",
    "constructor fill arg",
)
scenario.write_text(text)

controller = Path("src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java")
text = controller.read_text()
text = one(
    text,
    "                    int filled = fillDispensers(world, pasteResult);",
    "                    int filled = fillDispensers(world, pasteResult, pasteOrigin);",
    "fill call",
)
old_method = '''    private int fillDispensers(World world, WorldEditService.PasteResult result) {
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
new_method = '''    private int fillDispensers(
            World world,
            WorldEditService.PasteResult result,
            Location pasteOrigin
    ) {
        if (!scenario.fillDispensers().isEmpty()) {
            int total = 0;
            Set<String> seen = new HashSet<>();
            for (LabScenario.BlockPoint point : scenario.fillDispensers()) {
                Location location = relative(pasteOrigin, point);
                String key = coordinates(location);
                if (!seen.add(key)) {
                    continue;
                }
                BlockState state = world.getBlockAt(location).getState();
                if (!(state instanceof Dispenser dispenser)) {
                    throw new IllegalStateException("Selective fill coordinate "
                            + key + " contains " + state.getType());
                }
                dispenser.getInventory().clear();
                for (int slot = 0; slot < dispenser.getInventory().getSize(); slot++) {
                    dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, 64));
                }
                int expectedTnt = dispenser.getInventory().getSize() * 64;
                if (countTnt(dispenser) != expectedTnt) {
                    throw new IllegalStateException("Selective TNT fill verification failed at " + key);
                }
                total++;
            }
            plugin.getLogger().info("Selective TNT fill active | configured="
                    + scenario.fillDispensers().size() + " | unique=" + total);
            return total;
        }

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
text = one(text, old_method, new_method, "fill method")
controller.write_text(text)
print("selective fill patch applied")
