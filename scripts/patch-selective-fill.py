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
    "        List<BlockPoint> fireInputs,\n"
    "        List<BlockPoint> delayedButtonInputs,\n"
    "        int delayedButtonTicks,\n"
    "        List<BlockPoint> fillDispensers,\n"
    "        int fillTntPerDispenser,\n"
    "        BlockPoint directDispenser,",
    "record diagnostic fields",
)
text = one(
    text,
    "        fireInputs = List.copyOf(fireInputs);\n        targetStages = List.copyOf(targetStages);",
    "        fireInputs = List.copyOf(fireInputs);\n"
    "        delayedButtonInputs = List.copyOf(delayedButtonInputs);\n"
    "        fillDispensers = List.copyOf(fillDispensers);\n"
    "        targetStages = List.copyOf(targetStages);",
    "immutable diagnostic lists",
)
text = one(
    text,
    "        BlockPoint directDispenser = point(\n",
    "        List<BlockPoint> delayedButtonInputs = points(yaml, \"cannon.delayed-button-inputs\");\n"
    "        int delayedButtonTicks = Math.max(0, yaml.getInt(\"cannon.delayed-button-ticks\", 0));\n"
    "        List<BlockPoint> fillDispensers = points(yaml, \"cannon.fill-dispensers\");\n"
    "        int fillTntPerDispenser = Math.max(1, Math.min(576, yaml.getInt(\"cannon.fill-tnt-per-dispenser\", 576)));\n"
    "        BlockPoint directDispenser = point(\n",
    "parse diagnostic settings",
)
text = one(
    text,
    "                fireInputs,\n                directDispenser,",
    "                fireInputs,\n"
    "                delayedButtonInputs,\n"
    "                delayedButtonTicks,\n"
    "                fillDispensers,\n"
    "                fillTntPerDispenser,\n"
    "                directDispenser,",
    "constructor diagnostic args",
)
scenario.write_text(text)

controller = Path("src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java")
text = controller.read_text()
text = one(
    text,
    "            case BUTTON -> pressButtons(world, pasteOrigin);",
    '''            case BUTTON -> {
                pressButtons(world, pasteOrigin, scenario.fireInputs(), "primary");
                if (!scenario.delayedButtonInputs().isEmpty()) {
                    Bukkit.getScheduler().runTaskLater(plugin, () ->
                                    pressButtons(world, pasteOrigin, scenario.delayedButtonInputs(), "delayed"),
                            scenario.delayedButtonTicks());
                }
            }''',
    "button staging switch",
)
text = one(
    text,
    "    private void pressButtons(World world, Location pasteOrigin) {",
    '''    private void pressButtons(
            World world,
            Location pasteOrigin,
            List<LabScenario.BlockPoint> inputs,
            String stage
    ) {''',
    "button method signature",
)
text = one(
    text,
    "        for (LabScenario.BlockPoint point : scenario.fireInputs()) {",
    "        for (LabScenario.BlockPoint point : inputs) {",
    "button input loop",
)
text = one(
    text,
    '                    "mode=button;implementation=native-button-block"',
    '                    "mode=button;stage=" + stage + ";implementation=native-button-block"',
    "button telemetry stage",
)
text = one(
    text,
    '            throw new IllegalStateException("No button fire inputs configured.");',
    '            throw new IllegalStateException("No button fire inputs configured for stage " + stage + ".");',
    "button empty error",
)
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
                fillExact(dispenser, scenario.fillTntPerDispenser());
                if (countTnt(dispenser) != scenario.fillTntPerDispenser()) {
                    throw new IllegalStateException("Selective TNT fill verification failed at " + key);
                }
                total++;
            }
            plugin.getLogger().info("Selective TNT fill active | configured="
                    + scenario.fillDispensers().size()
                    + " | unique=" + total
                    + " | TNT/dispenser=" + scenario.fillTntPerDispenser());
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
                    fillExact(dispenser, scenario.fillTntPerDispenser());
                    if (countTnt(dispenser) != scenario.fillTntPerDispenser()) {
                        throw new IllegalStateException("TNT fill verification failed at "
                                + x + "," + y + "," + z);
                    }
                    total++;
                }
            }
        }
        return total;
    }

    private void fillExact(Dispenser dispenser, int amount) {
        dispenser.getInventory().clear();
        int remaining = amount;
        for (int slot = 0; slot < dispenser.getInventory().getSize() && remaining > 0; slot++) {
            int stack = Math.min(64, remaining);
            dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, stack));
            remaining -= stack;
        }
        if (remaining != 0) {
            throw new IllegalStateException("Unable to fit " + amount + " TNT in dispenser at "
                    + coordinates(dispenser.getLocation()));
        }
    }
'''
text = one(text, old_method, new_method, "fill method")
controller.write_text(text)
print("selective exact-fill + delayed native-button patch applied")
