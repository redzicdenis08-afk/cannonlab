from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

scenario = Path('src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java')
text = scenario.read_text()
text = replace_once(
    text,
    '        List<BlockPoint> fireInputs,\n        BlockPoint directDispenser,',
    '        List<BlockPoint> fireInputs,\n        List<BlockPoint> delayedFireInputs,\n        int delayedFireTicks,\n        BlockPoint directDispenser,',
    'scenario record fields',
)
text = replace_once(
    text,
    '        fireInputs = List.copyOf(fireInputs);\n        targetStages = List.copyOf(targetStages);',
    '        fireInputs = List.copyOf(fireInputs);\n        delayedFireInputs = List.copyOf(delayedFireInputs);\n        targetStages = List.copyOf(targetStages);',
    'scenario immutable lists',
)
text = replace_once(
    text,
    '        BlockPoint directDispenser = point(\n',
    '        List<BlockPoint> delayedFireInputs = points(yaml, "cannon.delayed-fire-inputs");\n'
    '        int delayedFireTicks = Math.max(0, yaml.getInt("cannon.delayed-fire-ticks", 0));\n'
    '        BlockPoint directDispenser = point(\n',
    'scenario yaml parsing',
)
text = replace_once(
    text,
    '                fireInputs,\n                directDispenser,',
    '                fireInputs,\n                delayedFireInputs,\n                delayedFireTicks,\n                directDispenser,',
    'scenario constructor args',
)
scenario.write_text(text)

controller = Path('src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java')
text = controller.read_text()
text = replace_once(
    text,
    '            case REDSTONE -> pulseRedstone(world, pasteOrigin);',
    '''            case REDSTONE -> {
                pulseRedstone(world, pasteOrigin, scenario.fireInputs(), "primary");
                if (!scenario.delayedFireInputs().isEmpty()) {
                    Bukkit.getScheduler().runTaskLater(plugin, () ->
                                    pulseRedstone(world, pasteOrigin, scenario.delayedFireInputs(), "delayed"),
                            scenario.delayedFireTicks());
                }
            }''',
    'controller fire switch',
)
text = replace_once(
    text,
    '    private void pulseRedstone(World world, Location pasteOrigin) {',
    '''    private void pulseRedstone(
            World world,
            Location pasteOrigin,
            List<LabScenario.BlockPoint> inputs,
            String stage
    ) {''',
    'pulse signature',
)
text = replace_once(
    text,
    '        for (LabScenario.BlockPoint point : scenario.fireInputs()) {\n            Location pulseLocation',
    '        for (LabScenario.BlockPoint point : inputs) {\n            Location pulseLocation',
    'pulse input loop',
)
text = replace_once(
    text,
    '            throw new IllegalStateException("No redstone fire inputs configured.");',
    '            throw new IllegalStateException("No redstone fire inputs configured for stage " + stage + ".");',
    'pulse empty error',
)
text = replace_once(
    text,
    '                    "previous=" + pulse.previousType() + ";pulse_ticks=" + scenario.firePulseTicks()',
    '                    "stage=" + stage + ";previous=" + pulse.previousType()\n'
    '                            + ";pulse_ticks=" + scenario.firePulseTicks()',
    'pulse telemetry',
)
controller.write_text(text)
print('staged redstone patch applied')
