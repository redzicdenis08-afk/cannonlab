#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def update_scenario() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabScenario.java"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, """        TargetType targetType,
        TargetDirection targetDirection,
        Material targetMaterial,
""", """        TargetType targetType,
        TargetDirection targetDirection,
        String targetFile,
        BlockPoint targetOrigin,
        Material targetMaterial,
""", "scenario target source fields")
    text = replace_once(text, """        int targetLateralOffset = yaml.getInt("target.lateral-offset", 0);
        int targetLayers = Math.max(1, yaml.getInt("target.layers", 1));
""", """        int targetLateralOffset = yaml.getInt("target.lateral-offset", 0);
        String targetFile = yaml.getString("target.file", "").trim();
        BlockPoint targetOrigin = point(
                yaml,
                "target.origin",
                defaultTargetOrigin(targetDirection, targetDistance, targetYOffset, targetLateralOffset)
        );
        int targetLayers = Math.max(1, yaml.getInt("target.layers", 1));
""", "scenario target source parse")
    text = replace_once(text, """                targetType,
                targetDirection,
                targetMaterial,
""", """                targetType,
                targetDirection,
                targetFile,
                targetOrigin,
                targetMaterial,
""", "scenario target source constructor")
    helper = """    private static BlockPoint defaultTargetOrigin(
            TargetDirection direction,
            int distance,
            int yOffset,
            int lateralOffset
    ) {
        return switch (direction) {
            case EAST -> new BlockPoint(distance, yOffset, lateralOffset);
            case WEST -> new BlockPoint(-distance, yOffset, lateralOffset);
            case SOUTH -> new BlockPoint(lateralOffset, yOffset, distance);
            case NORTH -> new BlockPoint(lateralOffset, yOffset, -distance);
        };
    }

"""
    text = replace_once(text, "    private static BlockPoint point(YamlConfiguration yaml, String path, BlockPoint fallback) {\n", helper + "    private static BlockPoint point(YamlConfiguration yaml, String path, BlockPoint fallback) {\n", "scenario target origin helper")
    path.write_text(text, encoding="utf-8")


def update_controller() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, """            TargetBuild targetBuild = buildTarget(world, arenaOrigin, scenario);
            targetCells = targetBuild.cells();
""", """            TargetBuild targetBuild = scenario.targetFile().isBlank()
                    ? buildTarget(world, arenaOrigin, scenario)
                    : buildTargetFromSchematic(world, arenaOrigin, scenario);
            targetCells = targetBuild.cells();
""", "controller exact target selection")

    exact_method = r'''    private TargetBuild buildTargetFromSchematic(
            World world,
            Location arenaOrigin,
            LabScenario selected
    ) throws IOException, WorldEditException {
        File targetFile = plugin.resolveTargetFile(selected.targetFile());
        Location targetOrigin = relative(arenaOrigin, selected.targetOrigin());
        WorldEditService.PasteResult result = worldEdit.paste(
                world,
                targetFile,
                targetOrigin,
                false
        );

        List<TargetCell> cells = new ArrayList<>();
        BoundsBuilder bounds = new BoundsBuilder();
        for (int x = result.minimum().x(); x <= result.maximum().x(); x++) {
            for (int y = Math.max(world.getMinHeight(), result.minimum().y());
                 y <= Math.min(world.getMaxHeight() - 1, result.maximum().y()); y++) {
                for (int z = result.minimum().z(); z <= result.maximum().z(); z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (!block.getType().isSolid()) {
                        continue;
                    }
                    validateArenaCoordinate(arenaOrigin, x, y, z);
                    int layer = switch (selected.targetDirection()) {
                        case EAST -> x - result.minimum().x();
                        case WEST -> result.maximum().x() - x;
                        case SOUTH -> z - result.minimum().z();
                        case NORTH -> result.maximum().z() - z;
                    };
                    TargetCell cell = new TargetCell(
                            x,
                            y,
                            z,
                            block.getType(),
                            block.getBlockData().getAsString(),
                            layer,
                            0,
                            "schematic:" + selected.targetFile(),
                            selected.regeneration()
                    );
                    cells.add(cell);
                    bounds.include(x, y, z);
                }
            }
        }
        if (cells.isEmpty()) {
            throw new IllegalStateException("Target schematic contains no solid target blocks: " + selected.targetFile());
        }
        return new TargetBuild(List.copyOf(cells), bounds.build());
    }

    private void validateArenaCoordinate(Location origin, int x, int y, int z) {
        int radiusX = plugin.getConfig().getInt("arena.radius-x", 256);
        int radiusY = plugin.getConfig().getInt("arena.radius-y", 128);
        int radiusZ = plugin.getConfig().getInt("arena.radius-z", 96);
        if (Math.abs(x - origin.getBlockX()) > radiusX
                || Math.abs(y - origin.getBlockY()) > radiusY
                || Math.abs(z - origin.getBlockZ()) > radiusZ) {
            throw new IllegalStateException(
                    "Target schematic exceeds configured arena radius at " + x + "," + y + "," + z
            );
        }
    }

'''
    text = replace_once(text, "    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {\n", exact_method + "    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {\n", "exact target builder")

    old_course_start = """    private void writeTargetCourse(Path runDirectory) throws IOException {
        if (scenario == null) {
            return;
        }
        StringBuilder stagesJson = new StringBuilder();
"""
    new_course_start = """    private void writeTargetCourse(Path runDirectory) throws IOException {
        if (scenario == null) {
            return;
        }
        if (!scenario.targetFile().isBlank()) {
            String exactCourse = """
                    {
                      "direction": "%s",
                      "source_file": "%s",
                      "stage_count": 0,
                      "stages": []
                    }
                    """.formatted(
                    scenario.targetDirection().name(),
                    json(scenario.targetFile())
            );
            Files.writeString(runDirectory.resolve("target-course.json"), exactCourse, StandardCharsets.UTF_8);
            return;
        }
        StringBuilder stagesJson = new StringBuilder();
"""
    text = replace_once(text, old_course_start, new_course_start, "exact target course export")

    text = replace_once(text, """            Map<LabScenario.RegenConfig, Integer> restoredByConfig = new HashMap<>();
            for (Map.Entry<TargetCell, Long> entry : due) {
                TargetCell cell = entry.getKey();
                LabScenario.RegenConfig config = cell.regeneration();
                int restoredForConfig = restoredByConfig.getOrDefault(config, 0);
                if (restoredForConfig >= config.maxBlocksPerCycle()) {
""", """            Map<Integer, Integer> restoredByStage = new HashMap<>();
            for (Map.Entry<TargetCell, Long> entry : due) {
                TargetCell cell = entry.getKey();
                LabScenario.RegenConfig config = cell.regeneration();
                int restoredForStage = restoredByStage.getOrDefault(cell.stageIndex(), 0);
                if (restoredForStage >= config.maxBlocksPerCycle()) {
""", "regen per-stage cap")
    text = replace_once(text, """                restored++;
                restoredByConfig.put(config, restoredForConfig + 1);
                recorder.recordCustomEvent(
""", """                restored++;
                restoredByStage.put(cell.stageIndex(), restoredForStage + 1);
                recorder.recordCustomEvent(
""", "regen per-stage accounting")
    path.write_text(text, encoding="utf-8")


def update_plugin() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/CannonLabPlugin.java"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, """    File resolveCannonFile(String name) {
        String normalized = name.endsWith(".schem") ? name : name + ".schem";
        File file = resolveInside(directory("cannons"), normalized);
        if (!file.isFile()) {
            throw new IllegalArgumentException("Cannon schematic not found: " + file.getAbsolutePath());
        }
        return file;
    }

""", """    File resolveCannonFile(String name) {
        String normalized = name.endsWith(".schem") ? name : name + ".schem";
        File file = resolveInside(directory("cannons"), normalized);
        if (!file.isFile()) {
            throw new IllegalArgumentException("Cannon schematic not found: " + file.getAbsolutePath());
        }
        return file;
    }

    File resolveTargetFile(String name) {
        String normalized = name.endsWith(".schem") ? name : name + ".schem";
        File file = resolveInside(directory("targets"), normalized);
        if (!file.isFile()) {
            throw new IllegalArgumentException("Target schematic not found: " + file.getAbsolutePath());
        }
        return file;
    }

""", "plugin target resolver")
    text = replace_once(text, """        Files.createDirectories(directory("cannons"));
        Files.createDirectories(directory("scenarios"));
        Files.createDirectories(directory("results"));
""", """        Files.createDirectories(directory("cannons"));
        Files.createDirectories(directory("targets"));
        Files.createDirectories(directory("scenarios"));
        Files.createDirectories(directory("results"));
""", "plugin target directory")
    path.write_text(text, encoding="utf-8")


def update_runner() -> None:
    path = ROOT / "scripts/cloud-smoke.sh"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, 'mkdir -p "$PLUGINS" "$DATA/cannons" "$DATA/scenarios" "$DATA/results" "$ARTIFACTS"\n', 'mkdir -p "$PLUGINS" "$DATA/cannons" "$DATA/targets" "$DATA/scenarios" "$DATA/results" "$ARTIFACTS"\n', "runner target directory")
    text = replace_once(text, """for fixture in "$ROOT"/cannons/*.schem.b64; do
  output="$DATA/cannons/$(basename "${fixture%.b64}")"
  base64 --decode "$fixture" > "$output"
done
cp "$ROOT"/scenarios/*.yml "$DATA/scenarios/"
""", """for fixture in "$ROOT"/cannons/*.schem.b64; do
  output="$DATA/cannons/$(basename "${fixture%.b64}")"
  base64 --decode "$fixture" > "$output"
done
if compgen -G "$ROOT/targets/*.schem.b64" > /dev/null; then
  for fixture in "$ROOT"/targets/*.schem.b64; do
    output="$DATA/targets/$(basename "${fixture%.b64}")"
    base64 --decode "$fixture" > "$output"
  done
fi
cp "$ROOT"/scenarios/*.yml "$DATA/scenarios/"
""", "runner target fixtures")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    update_scenario()
    update_controller()
    update_plugin()
    update_runner()
    print("Exact target support and per-stage regen caps applied.")


if __name__ == "__main__":
    main()
