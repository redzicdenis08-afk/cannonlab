#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker missing")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker missing")
    return text[:start_index] + replacement + text[end_index:]


def update_controller() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java"
    text = path.read_text(encoding="utf-8")

    text = replace_once(text, """            recorder.start(
                    runId,
                    scenario.name(),
                    shotNumber,
                    world,
                    arenaOrigin,
                    scenario.maxShotTicks(),
                    scenario.quietTicks(),
                    this::shotCompleted
            );
""", """            recorder.start(
                    runId,
                    scenario.name(),
                    shotNumber,
                    world,
                    arenaOrigin,
                    pasteOrigin,
                    new ShotRecorder.BlockBounds(
                            pasteResult.minimum().x(),
                            pasteResult.minimum().y(),
                            pasteResult.minimum().z(),
                            pasteResult.maximum().x(),
                            pasteResult.maximum().y(),
                            pasteResult.maximum().z()
                    ),
                    scenario.maxShotTicks(),
                    scenario.quietTicks(),
                    this::shotCompleted
            );
""", "controller recorder start")

    text = replace_once(text, """            regenMonitor = new RegenMonitor(
                    world,
                    targetCells,
                    scenario.regeneration()
            );
""", """            regenMonitor = new RegenMonitor(
                    world,
                    targetCells
            );
""", "controller regen constructor")

    text = replace_once(text, """                result.explosions(),
                result.destroyedBlocks(),
                finalDestroyed,
""", """                result.explosions(),
                result.destroyedBlocks(),
                result.selfDamageBlocks(),
                finalDestroyed,
""", "completed shot self damage")

    text = replace_once(text, """                + " | explosions=" + result.explosions()
                + " | maxTnt=" + result.maximumTnt()
                + " | targetFinal=" + finalDestroyed + "/" + targetCells.size()
""", """                + " | explosions=" + result.explosions()
                + " | maxTnt=" + result.maximumTnt()
                + " | selfDamage=" + result.selfDamageBlocks()
                + " | targetFinal=" + finalDestroyed + "/" + targetCells.size()
""", "shot log self damage")

    new_target_method = r'''    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {
        List<TargetCell> cells = new ArrayList<>();
        BoundsBuilder bounds = new BoundsBuilder();
        int stageDistance = selected.targetDistance();
        int globalLayer = 0;

        for (int stageIndex = 0; stageIndex < selected.targetStages().size(); stageIndex++) {
            LabScenario.TargetStage stage = selected.targetStages().get(stageIndex);
            int halfWidth = stage.width() / 2;

            for (int layer = 0; layer < stage.layers(); layer++) {
                int distance = stageDistance + layer * stage.spacing();

                for (int vertical = 0; vertical < stage.height(); vertical++) {
                    int y = origin.getBlockY() + stage.yOffset() + vertical;
                    if (y < world.getMinHeight() || y >= world.getMaxHeight()) {
                        throw new IllegalStateException("Target Y outside world bounds: " + y);
                    }

                    for (int across = 0; across < stage.width(); across++) {
                        int lateral = stage.lateralOffset() - halfWidth + across;
                        TargetPlacement placement = targetPlacement(
                                origin,
                                selected.targetDirection(),
                                distance,
                                lateral,
                                y
                        );
                        validateArenaBounds(origin, placement);

                        Block target = world.getBlockAt(placement.targetX(), y, placement.targetZ());
                        Block front = world.getBlockAt(placement.frontX(), y, placement.frontZ());
                        Block back = world.getBlockAt(placement.backX(), y, placement.backZ());
                        target.setType(Material.AIR, false);
                        front.setType(Material.AIR, false);
                        back.setType(Material.AIR, false);

                        boolean checker = ((vertical + across + layer) & 1) == 0;
                        switch (stage.type()) {
                            case DRY -> target.setType(stage.material(), false);
                            case WATERED -> {
                                target.setType(stage.material(), false);
                                front.setType(Material.WATER, false);
                            }
                            case COBBLE_REGEN -> {
                                target.setType(stage.material(), false);
                                front.setType(Material.WATER, false);
                                back.setType(Material.LAVA, false);
                            }
                            case FILTER -> target.setType(
                                    checker ? stage.material() : Material.AIR,
                                    false
                            );
                            case SLAB_FILTER -> {
                                target.setType(stage.material(), false);
                                front.setType(Material.STONE_SLAB, false);
                                BlockData data = front.getBlockData();
                                if (data instanceof Slab slab) {
                                    slab.setType(checker ? Slab.Type.TOP : Slab.Type.BOTTOM);
                                    front.setBlockData(slab, false);
                                }
                            }
                            case HOTDOG -> {
                                boolean solidLane = ((across / stage.hotdogBandWidth()) & 1) == 0;
                                front.setType(Material.WATER, false);
                                if (solidLane) {
                                    target.setType(
                                            checker ? stage.material() : stage.alternateMaterial(),
                                            false
                                    );
                                }
                            }
                            case PILLARS -> {
                                boolean pillar = Math.floorMod(across + layer, stage.pillarSpacing()) == 0;
                                if (pillar) {
                                    target.setType(stage.material(), false);
                                }
                            }
                        }

                        if (!target.isEmpty()) {
                            TargetCell cell = new TargetCell(
                                    target.getX(),
                                    target.getY(),
                                    target.getZ(),
                                    target.getType(),
                                    target.getBlockData().getAsString(),
                                    globalLayer,
                                    stageIndex,
                                    stage.name(),
                                    stage.regeneration()
                            );
                            cells.add(cell);
                            bounds.include(cell.x(), cell.y(), cell.z());
                        }
                    }
                }
                globalLayer++;
            }

            stageDistance += (stage.layers() - 1) * stage.spacing() + stage.gapAfter();
        }
        if (cells.isEmpty()) {
            throw new IllegalStateException("Target configuration produced zero solid target cells.");
        }
        return new TargetBuild(List.copyOf(cells), bounds.build());
    }

    private void writeTargetCourse(Path runDirectory) throws IOException {
        if (scenario == null) {
            return;
        }
        StringBuilder stagesJson = new StringBuilder();
        int distance = scenario.targetDistance();
        for (int index = 0; index < scenario.targetStages().size(); index++) {
            LabScenario.TargetStage stage = scenario.targetStages().get(index);
            if (index > 0) {
                stagesJson.append(",\n");
            }
            stagesJson.append("""
                    {
                      "index": %d,
                      "name": "%s",
                      "type": "%s",
                      "start_distance": %d,
                      "end_distance": %d,
                      "width": %d,
                      "height": %d,
                      "layers": %d,
                      "spacing": %d,
                      "gap_after": %d,
                      "regeneration": {"enabled": %s, "delay_ticks": %d, "interval_ticks": %d, "max_blocks_per_cycle": %d}
                    }
                    """.formatted(
                    index,
                    json(stage.name()),
                    stage.type().name(),
                    distance,
                    distance + (stage.layers() - 1) * stage.spacing(),
                    stage.width(),
                    stage.height(),
                    stage.layers(),
                    stage.spacing(),
                    stage.gapAfter(),
                    stage.regeneration().enabled(),
                    stage.regeneration().delayTicks(),
                    stage.regeneration().intervalTicks(),
                    stage.regeneration().maxBlocksPerCycle()
            ));
            distance += (stage.layers() - 1) * stage.spacing() + stage.gapAfter();
        }
        String course = """
                {
                  "direction": "%s",
                  "stage_count": %d,
                  "stages": [
                %s
                  ]
                }
                """.formatted(
                scenario.targetDirection().name(),
                scenario.targetStages().size(),
                indent(stagesJson.toString(), 4)
        );
        Files.writeString(runDirectory.resolve("target-course.json"), course, StandardCharsets.UTF_8);
    }

'''
    text = replace_between(
        text,
        "    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {",
        "    private TargetPlacement targetPlacement(",
        new_target_method,
        "mixed target builder",
    )

    text = replace_once(text, """        Files.createDirectories(runDirectory);

        StringBuilder shotsJson = new StringBuilder();
""", """        Files.createDirectories(runDirectory);
        writeTargetCourse(runDirectory);

        StringBuilder shotsJson = new StringBuilder();
""", "target course export")

    text = replace_once(text, """                      "explosions": %d,
                      "destroyed_blocks": %d,
                      "maximum_tnt_entities": %d,
""", """                      "explosions": %d,
                      "destroyed_blocks": %d,
                      "self_damage_blocks": %d,
                      "maximum_tnt_entities": %d,
""", "run summary self damage key")

    text = replace_once(text, """                    shot.explosions(),
                    shot.destroyedBlocks(),
                    shot.maximumTnt(),
""", """                    shot.explosions(),
                    shot.destroyedBlocks(),
                    shot.selfDamageBlocks(),
                    shot.maximumTnt(),
""", "run summary self damage value")

    text = replace_once(text, """        private final World world;
        private final List<TargetCell> cells;
        private final LabScenario.RegenConfig config;
""", """        private final World world;
        private final List<TargetCell> cells;
""", "regen monitor fields")

    text = replace_once(text, """        private RegenMonitor(
                World world,
                List<TargetCell> cells,
                LabScenario.RegenConfig config
        ) {
            this.world = world;
            this.cells = cells;
            this.config = config;
        }
""", """        private RegenMonitor(
                World world,
                List<TargetCell> cells
        ) {
            this.world = world;
            this.cells = cells;
        }
""", "regen monitor constructor")

    text = replace_once(text, '                                cell.material().name(),\n', '                                cell.stageName() + ":" + cell.material().name(),\n', "destroy event stage")

    restore_start = "            if (!allowRestore || !config.enabled() || tick % config.intervalTicks() != 0) {"
    restore_end = "        private RegenStats stopAndSnapshot() {"
    restore_block = r'''            if (!allowRestore) {
                return;
            }

            boolean cycleDue = cells.stream()
                    .map(TargetCell::regeneration)
                    .distinct()
                    .anyMatch(config -> config.enabled() && tick % config.intervalTicks() == 0);
            if (!cycleDue) {
                return;
            }
            cycles++;

            List<Map.Entry<TargetCell, Long>> due = missingSince.entrySet().stream()
                    .filter(entry -> {
                        LabScenario.RegenConfig config = entry.getKey().regeneration();
                        return config.enabled()
                                && tick % config.intervalTicks() == 0
                                && tick - entry.getValue() >= config.delayTicks();
                    })
                    .sorted(Comparator
                            .comparingLong((Map.Entry<TargetCell, Long> entry) -> entry.getValue())
                            .thenComparingInt(entry -> entry.getKey().layer()))
                    .toList();

            Map<LabScenario.RegenConfig, Integer> restoredByConfig = new HashMap<>();
            for (Map.Entry<TargetCell, Long> entry : due) {
                TargetCell cell = entry.getKey();
                LabScenario.RegenConfig config = cell.regeneration();
                int restoredForConfig = restoredByConfig.getOrDefault(config, 0);
                if (restoredForConfig >= config.maxBlocksPerCycle()) {
                    continue;
                }
                if (matches(world, cell)) {
                    missingSince.remove(cell);
                    continue;
                }
                restore(world, cell);
                missingSince.remove(cell);
                restored++;
                restoredByConfig.put(config, restoredForConfig + 1);
                recorder.recordCustomEvent(
                        "REGEN_RESTORE",
                        cell.stageName() + ":" + cell.material().name(),
                        new Location(world, cell.x(), cell.y(), cell.z()),
                        1
                );
            }
        }

'''
    text = replace_between(text, restore_start, restore_end, restore_block, "per-stage regen")

    text = replace_once(text, """    private record TargetCell(
            int x,
            int y,
            int z,
            Material material,
            String blockData,
            int layer
    ) {
    }
""", """    private record TargetCell(
            int x,
            int y,
            int z,
            Material material,
            String blockData,
            int layer,
            int stageIndex,
            String stageName,
            LabScenario.RegenConfig regeneration
    ) {
    }
""", "target cell metadata")

    text = replace_once(text, """            int explosions,
            int destroyedBlocks,
            int targetDestroyed,
""", """            int explosions,
            int destroyedBlocks,
            int selfDamageBlocks,
            int targetDestroyed,
""", "completed shot record")

    old_preparation = """        private static CompletedShot preparationError(
                int number,
                int targetTotal,
                Exception exception
        ) {
            return new CompletedShot(
                    number,
                    "preparation_error",
                    false,
                    0,
                    0,
                    0,
                    0,
                    0,
                    targetTotal,
                    0,
                    0,
                    0,
                    0,
                    0,
                    exception.getClass().getSimpleName() + ": " + exception.getMessage()
            );
        }
"""
    new_preparation = """        private static CompletedShot preparationError(
                int number,
                int targetTotal,
                Exception exception
        ) {
            return new CompletedShot(
                    number,
                    "preparation_error",
                    false,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    targetTotal,
                    0,
                    0,
                    0,
                    0,
                    0,
                    exception.getClass().getSimpleName() + ": " + exception.getMessage()
            );
        }
"""
    text = replace_once(text, old_preparation, new_preparation, "preparation error constructor")

    path.write_text(text, encoding="utf-8")


def update_recorder() -> None:
    path = ROOT / "src/main/java/io/github/redzicdenis08afk/cannonlab/ShotRecorder.java"
    text = path.read_text(encoding="utf-8")

    text = replace_once(text, """    private Location origin;
    private Location cannonOrigin;
    private Path shotDirectory;
""", """    private Location origin;
    private Location cannonOrigin;
    private BlockBounds cannonBounds;
    private Path shotDirectory;
""", "recorder bounds field")
    text = replace_once(text, """    private int explosions;
    private int destroyedBlocks;
    private int maximumTnt;
""", """    private int explosions;
    private int destroyedBlocks;
    private int selfDamageBlocks;
    private int maximumTnt;
""", "recorder self damage field")
    text = replace_once(text, """            int shotNumber,
            World recordingWorld,
            Location recordingOrigin,
            int shotMaxTicks,
""", """            int shotNumber,
            World recordingWorld,
            Location recordingOrigin,
            Location recordingCannonOrigin,
            BlockBounds recordingCannonBounds,
            int shotMaxTicks,
""", "recorder start signature")
    text = replace_once(text, """        world = recordingWorld;
        origin = recordingOrigin.clone();
        cannonOrigin = recordingOrigin.clone();
        maxTicks = shotMaxTicks;
""", """        world = recordingWorld;
        origin = recordingOrigin.clone();
        cannonOrigin = recordingCannonOrigin.clone();
        cannonBounds = recordingCannonBounds;
        maxTicks = shotMaxTicks;
""", "recorder coordinate origin")
    text = replace_once(text, """        explosions = 0;
        destroyedBlocks = 0;
        maximumTnt = 0;
""", """        explosions = 0;
        destroyedBlocks = 0;
        selfDamageBlocks = 0;
        maximumTnt = 0;
""", "recorder reset self damage")

    text = text.replace(
        """        explosions++;
        destroyedBlocks += event.blockList().size();
        try {
""",
        """        explosions++;
        destroyedBlocks += event.blockList().size();
        int selfDamage = countSelfDamage(event.blockList());
        selfDamageBlocks += selfDamage;
        try {
""",
        2,
    )
    if text.count("int selfDamage = countSelfDamage(event.blockList());") != 2:
        raise RuntimeError("explosion self-damage hooks did not land twice")
    text = text.replace(
        '                        "affected_blocks=" + event.blockList().size()\n',
        '                        "affected_blocks=" + event.blockList().size()\n                                + ";self_damage_blocks=" + selfDamage\n',
        2,
    )

    count_helper = r'''    private int countSelfDamage(List<Block> blocks) {
        if (cannonBounds == null) {
            return 0;
        }
        int count = 0;
        for (Block block : blocks) {
            if (cannonBounds.contains(block)) {
                count++;
            }
        }
        return count;
    }

'''
    text = replace_once(text, "    private boolean causalEnabled() {\n", count_helper + "    private boolean causalEnabled() {\n", "self damage helper")
    text = replace_once(text, """                explosions,
                destroyedBlocks,
                maximumTnt,
""", """                explosions,
                destroyedBlocks,
                selfDamageBlocks,
                maximumTnt,
""", "shot result self damage")
    text = replace_once(text, """                  "explosions": %d,
                  "destroyed_blocks": %d,
                  "maximum_tnt_entities": %d,
""", """                  "explosions": %d,
                  "destroyed_blocks": %d,
                  "self_damage_blocks": %d,
                  "maximum_tnt_entities": %d,
""", "shot summary self damage key")
    text = replace_once(text, """                result.explosions(),
                result.destroyedBlocks(),
                result.maximumTnt(),
""", """                result.explosions(),
                result.destroyedBlocks(),
                result.selfDamageBlocks(),
                result.maximumTnt(),
""", "shot summary self damage value")
    text = replace_once(text, """        world = null;
        origin = null;
        cannonOrigin = null;
        completion = null;
""", """        world = null;
        origin = null;
        cannonOrigin = null;
        cannonBounds = null;
        completion = null;
""", "clear bounds")

    block_bounds = """    record BlockBounds(
            int minX,
            int minY,
            int minZ,
            int maxX,
            int maxY,
            int maxZ
    ) {
        boolean contains(Block block) {
            return block.getX() >= minX && block.getX() <= maxX
                    && block.getY() >= minY && block.getY() <= maxY
                    && block.getZ() >= minZ && block.getZ() <= maxZ;
        }
    }

"""
    text = replace_once(text, "    record ShotResult(\n", block_bounds + "    record ShotResult(\n", "block bounds record")
    text = replace_once(text, """            int explosions,
            int destroyedBlocks,
            int maximumTnt,
""", """            int explosions,
            int destroyedBlocks,
            int selfDamageBlocks,
            int maximumTnt,
""", "shot result record")

    path.write_text(text, encoding="utf-8")


def update_assertions() -> None:
    path = ROOT / "scripts/assert-results.py"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, '    parser.add_argument("--min-layer-breached", type=int)\n', '    parser.add_argument("--min-layer-breached", type=int)\n    parser.add_argument("--max-self-damage-blocks", type=int)\n', "assertion CLI")
    text = replace_once(text, """    if args.min_target_peak_mean is not None and args.min_target_peak_mean < 0:
        fail("--min-target-peak-mean cannot be negative")

""", """    if args.min_target_peak_mean is not None and args.min_target_peak_mean < 0:
        fail("--min-target-peak-mean cannot be negative")
    if args.max_self_damage_blocks is not None and args.max_self_damage_blocks < 0:
        fail("--max-self-damage-blocks cannot be negative")

""", "assertion validation")
    text = replace_once(text, """    regen_restored_values: list[float] = []
    layer_breached_values: list[float] = []
""", """    regen_restored_values: list[float] = []
    layer_breached_values: list[float] = []
    self_damage_values: list[float] = []
""", "assertion self damage stats")
    text = replace_once(text, """        max_layer = int(shot.get("max_layer_breached", 0))
        peak_destroyed_values.append(float(peak_destroyed))
""", """        max_layer = int(shot.get("max_layer_breached", 0))
        self_damage = int(shot.get("self_damage_blocks", 0))
        peak_destroyed_values.append(float(peak_destroyed))
""", "assertion shot self damage")
    text = replace_once(text, """        layer_breached_values.append(float(max_layer))

        if (
""", """        layer_breached_values.append(float(max_layer))
        self_damage_values.append(float(self_damage))

        if (
""", "assertion collect self damage")
    text = replace_once(text, """        if args.require_regen and regen_restored < args.min_regen_restored:
            failures.append(
                f"shot {number}: regen_blocks_restored={regen_restored} "
                f"below {args.min_regen_restored}"
            )

""", """        if args.require_regen and regen_restored < args.min_regen_restored:
            failures.append(
                f"shot {number}: regen_blocks_restored={regen_restored} "
                f"below {args.min_regen_restored}"
            )
        if args.max_self_damage_blocks is not None and self_damage > args.max_self_damage_blocks:
            failures.append(
                f"shot {number}: self_damage_blocks={self_damage} "
                f"above {args.max_self_damage_blocks}"
            )

""", "assertion self damage gate")
    text = replace_once(text, '        "max_layer_breached": numeric_stats(layer_breached_values),\n', '        "max_layer_breached": numeric_stats(layer_breached_values),\n        "self_damage_blocks": numeric_stats(self_damage_values),\n', "assertion fingerprint")
    path.write_text(text, encoding="utf-8")


def update_runner() -> None:
    path = ROOT / "scripts/cloud-smoke.sh"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, 'MIN_LAYER_BREACHED="${CANNONLAB_MIN_LAYER_BREACHED:-}"\n', 'MIN_LAYER_BREACHED="${CANNONLAB_MIN_LAYER_BREACHED:-}"\nMAX_SELF_DAMAGE_BLOCKS="${CANNONLAB_MAX_SELF_DAMAGE_BLOCKS:-}"\n', "runner self damage env")
    text = replace_once(text, """if [[ -n "$MIN_LAYER_BREACHED" ]]; then
  ASSERT_ARGS+=(--min-layer-breached "$MIN_LAYER_BREACHED")
fi
case "${REQUIRE_REGEN,,}" in
""", """if [[ -n "$MIN_LAYER_BREACHED" ]]; then
  ASSERT_ARGS+=(--min-layer-breached "$MIN_LAYER_BREACHED")
fi
if [[ -n "$MAX_SELF_DAMAGE_BLOCKS" ]]; then
  ASSERT_ARGS+=(--max-self-damage-blocks "$MAX_SELF_DAMAGE_BLOCKS")
fi
case "${REQUIRE_REGEN,,}" in
""", "runner self damage args")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    update_controller()
    update_recorder()
    update_assertions()
    update_runner()
    print("EC readiness source transforms applied exactly once.")


if __name__ == "__main__":
    main()
