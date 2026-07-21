package io.github.redzicdenis08afk.cannonlab;

import com.sk89q.worldedit.WorldEditException;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.BlockFace;
import org.bukkit.block.BlockState;
import org.bukkit.block.Dispenser;
import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.type.Switch;
import org.bukkit.block.data.type.Slab;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.Item;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.inventory.ItemStack;
import org.bukkit.scheduler.BukkitTask;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

final class LabRunController {
    private static final int DISPENSER_LIMIT_PER_CHUNK = 128;
    private static final BlockFace[] NEIGHBOUR_FACES = {
            BlockFace.WEST,
            BlockFace.EAST,
            BlockFace.DOWN,
            BlockFace.UP,
            BlockFace.NORTH,
            BlockFace.SOUTH
    };

    private final CannonLabPlugin plugin;
    private final WorldEditService worldEdit;
    private final ShotRecorder recorder;

    private LabScenario scenario;
    private String runId;
    private int shotNumber;
    private boolean running;
    private boolean cancelled;
    private final List<CompletedShot> completedShots = new ArrayList<>();
    private List<TargetCell> targetCells = List.of();
    private TargetBounds targetBounds = TargetBounds.empty();
    private RegenMonitor regenMonitor;

    LabRunController(CannonLabPlugin plugin, WorldEditService worldEdit, ShotRecorder recorder) {
        this.plugin = plugin;
        this.worldEdit = worldEdit;
        this.recorder = recorder;
    }

    boolean isRunning() {
        return running;
    }

    String status() {
        if (!running || scenario == null) {
            return "idle";
        }
        return "running scenario=" + scenario.name()
                + " shot=" + shotNumber + "/" + scenario.shots()
                + " fireMode=" + scenario.fireMode()
                + " targetDirection=" + scenario.targetDirection()
                + " regen=" + scenario.regeneration().enabled();
    }

    void run(String scenarioFileName, CommandSender sender) {
        if (running) {
            throw new IllegalStateException("A CannonLab run is already active.");
        }

        File scenarioFile = plugin.resolveScenarioFile(scenarioFileName);
        scenario = LabScenario.load(scenarioFile);
        runId = Instant.now().toEpochMilli() + "-" + safeName(scenario.name());
        shotNumber = 0;
        running = true;
        cancelled = false;
        completedShots.clear();
        sender.sendMessage("CannonLab run started: " + scenario.name()
                + " x" + scenario.shots()
                + " | fireMode=" + scenario.fireMode()
                + " | inputs=" + scenario.fireInputs().size()
                + " | target=" + scenario.targetType() + "/" + scenario.targetDirection()
                + " | regen=" + scenario.regeneration().enabled());
        prepareNextShot();
    }

    void cancel(CommandSender sender) {
        if (!running) {
            sender.sendMessage("No CannonLab run is active.");
            return;
        }
        cancelled = true;
        recorder.cancel();
        stopRegenMonitor();
        finishRun("cancelled");
        sender.sendMessage("CannonLab run cancelled.");
    }

    private void prepareNextShot() {
        if (!running || cancelled) {
            return;
        }
        shotNumber++;

        try {
            stopRegenMonitor();
            World world = plugin.arenaWorld();
            Location arenaOrigin = plugin.arenaOrigin(world);
            clearArena(world, arenaOrigin);

            File schematic = plugin.resolveCannonFile(scenario.cannonFile());
            Location pasteOrigin = relative(arenaOrigin, scenario.cannonOrigin());
            WorldEditService.PasteResult pasteResult = worldEdit.paste(
                    world,
                    schematic,
                    pasteOrigin,
                    false
            );

            TargetBuild targetBuild = buildTarget(world, arenaOrigin, scenario);
            targetCells = targetBuild.cells();
            targetBounds = targetBuild.bounds();

            FillAudit audit = auditAndFill(world, pasteResult);
            if (scenario.enforceDispenserLimit()
                    && audit.maximumPerChunk() > DISPENSER_LIMIT_PER_CHUNK) {
                throw new IllegalStateException(
                        "Dispenser limit exceeded: " + audit.maximumPerChunk()
                                + " in chunk " + audit.maximumChunk());
            }
            if (audit.totalDispensers() == 0) {
                throw new IllegalStateException("Pasted schematic contains no dispensers.");
            }

            plugin.getLogger().info("Prepared shot " + shotNumber
                    + " | dispensers=" + audit.totalDispensers()
                    + " | max/chunk=" + audit.maximumPerChunk()
                    + " | fireMode=" + scenario.fireMode()
                    + " | inputs=" + scenario.fireInputs().size()
                    + " | target=" + scenario.targetType() + "/" + scenario.targetDirection()
                    + " | targetCells=" + targetCells.size()
                    + " | regen=" + scenario.regeneration());

            recorder.start(
                    runId,
                    scenario.name(),
                    shotNumber,
                    world,
                    arenaOrigin,
                    scenario.maxShotTicks(),
                    scenario.quietTicks(),
                    this::shotCompleted
            );

            regenMonitor = new RegenMonitor(
                    world,
                    targetCells,
                    scenario.regeneration()
            );
            regenMonitor.start();

            Bukkit.getScheduler().runTaskLater(plugin, () -> {
                try {
                    fire(world, pasteOrigin);
                } catch (RuntimeException exception) {
                    plugin.getLogger().severe("Shot " + shotNumber
                            + " firing failed: " + exception.getMessage());
                    exception.printStackTrace();
                }
            }, scenario.warmupTicks());
        } catch (IOException | WorldEditException | RuntimeException exception) {
            stopRegenMonitor();
            plugin.getLogger().severe("Run preparation failed: " + exception.getMessage());
            completedShots.add(CompletedShot.preparationError(
                    shotNumber,
                    targetCells.size(),
                    exception
            ));
            finishRun("error");
        }
    }

    private void fire(World world, Location pasteOrigin) {
        if (!running || cancelled || scenario == null) {
            return;
        }

        switch (scenario.fireMode()) {
            case DIRECT_DISPENSE -> dispenseDirectly(world, pasteOrigin);
            case REDSTONE -> pulseRedstone(world, pasteOrigin);
        }
    }

    private void dispenseDirectly(World world, Location pasteOrigin) {
        Location dispenserLocation = relative(pasteOrigin, scenario.directDispenser());
        Block block = world.getBlockAt(dispenserLocation);
        if (!(block.getState() instanceof Dispenser dispenser)) {
            throw new IllegalStateException("Direct dispenser coordinate "
                    + coordinates(dispenserLocation)
                    + " contains " + block.getType());
        }

        int tntBefore = countTnt(dispenser);
        if (tntBefore < 1) {
            throw new IllegalStateException("Direct dispenser at "
                    + coordinates(dispenserLocation) + " has no TNT.");
        }

        boolean dispensed = dispenser.dispense();
        int tntAfter = countTnt((Dispenser) block.getState());
        plugin.getLogger().info("Direct fire at " + coordinates(dispenserLocation)
                + " | success=" + dispensed
                + " | TNT=" + tntBefore + "->" + tntAfter);
        if (!dispensed || tntAfter >= tntBefore) {
            throw new IllegalStateException("Dispenser API did not consume TNT at "
                    + coordinates(dispenserLocation));
        }
    }

    private void pulseRedstone(World world, Location pasteOrigin) {
        Map<String, PulseState> uniquePulses = new LinkedHashMap<>();
        for (LabScenario.BlockPoint point : scenario.fireInputs()) {
            Location pulseLocation = relative(pasteOrigin, point);
            Block pulseBlock = world.getBlockAt(pulseLocation);
            uniquePulses.putIfAbsent(
                    coordinates(pulseLocation),
                    new PulseState(
                            pulseLocation,
                            pulseBlock,
                            pulseBlock.getType(),
                            pulseBlock.getBlockData().clone()
                    )
            );
        }
        if (uniquePulses.isEmpty()) {
            throw new IllegalStateException("No redstone fire inputs configured.");
        }

        for (PulseState pulse : uniquePulses.values()) {
            plugin.getLogger().info("Redstone fire at " + coordinates(pulse.location())
                    + " | previous=" + pulse.previousType()
                    + " | control=" + pulseControl(pulse)
                    + " | neighbours=" + describeNeighbours(pulse.block()));
            pressPulse(pulse);
        }

        Bukkit.getScheduler().runTaskLater(plugin, () -> {
            for (PulseState pulse : uniquePulses.values()) {
                plugin.getLogger().info("Redstone pulse verification at "
                        + coordinates(pulse.location())
                        + " | powered=" + pulse.block().isBlockPowered()
                        + " | indirect=" + pulse.block().isBlockIndirectlyPowered()
                        + " | neighbours=" + describeNeighbours(pulse.block()));
            }
        }, 1L);

        Bukkit.getScheduler().runTaskLater(plugin, () -> {
            for (PulseState pulse : uniquePulses.values()) {
                pulse.block().setType(pulse.previousType(), true);
                pulse.block().setBlockData(pulse.previousData(), true);
            }
        }, scenario.firePulseTicks());
    }

    private String pulseControl(PulseState pulse) {
        return pulse.previousData() instanceof Switch ? "button" : "redstone-block";
    }

    private void pressPulse(PulseState pulse) {
        if (pulse.previousData() instanceof Switch previousSwitch) {
            Switch pressed = (Switch) previousSwitch.clone();
            pressed.setPowered(true);
            pulse.block().setBlockData(pressed, true);
            return;
        }

        pulse.block().setType(Material.REDSTONE_BLOCK, true);
        BlockState pulseState = pulse.block().getState();
        pulseState.update(true, true);
    }

    private List<String> describeNeighbours(Block center) {
        List<String> descriptions = new ArrayList<>();
        for (BlockFace face : NEIGHBOUR_FACES) {
            Block neighbour = center.getRelative(face);
            String description = face.name() + "=" + neighbour.getType();
            if (neighbour.getState() instanceof Dispenser dispenser) {
                description += "[TNT=" + countTnt(dispenser)
                        + ",powered=" + neighbour.isBlockPowered()
                        + ",indirect=" + neighbour.isBlockIndirectlyPowered() + "]";
            }
            descriptions.add(description);
        }
        return descriptions;
    }

    private int countTnt(Dispenser dispenser) {
        int total = 0;
        for (ItemStack item : dispenser.getInventory().getContents()) {
            if (item != null && item.getType() == Material.TNT) {
                total += item.getAmount();
            }
        }
        return total;
    }

    private void shotCompleted(ShotRecorder.ShotResult result) {
        RegenStats regenStats = regenMonitor == null
                ? RegenStats.empty()
                : regenMonitor.stopAndSnapshot();
        regenMonitor = null;

        int remaining = countRemainingTargetBlocks();
        int finalDestroyed = Math.max(0, targetCells.size() - remaining);
        completedShots.add(new CompletedShot(
                shotNumber,
                result.finishReason(),
                result.sawPayload(),
                result.explosions(),
                result.destroyedBlocks(),
                finalDestroyed,
                regenStats.peakDestroyed(),
                regenStats.everDestroyed(),
                targetCells.size(),
                regenStats.restored(),
                regenStats.maxLayerBreached(),
                regenStats.cycles(),
                result.maximumTnt(),
                result.maximumFallingBlocks(),
                null
        ));

        plugin.getLogger().info("Shot " + shotNumber
                + " complete | payload=" + result.sawPayload()
                + " | explosions=" + result.explosions()
                + " | maxTnt=" + result.maximumTnt()
                + " | targetFinal=" + finalDestroyed + "/" + targetCells.size()
                + " | targetPeak=" + regenStats.peakDestroyed()
                + " | regenRestored=" + regenStats.restored()
                + " | maxLayer=" + regenStats.maxLayerBreached());

        if (cancelled) {
            finishRun("cancelled");
        } else if (shotNumber < scenario.shots()) {
            Bukkit.getScheduler().runTaskLater(plugin, this::prepareNextShot, 20L);
        } else {
            finishRun("complete");
        }
    }

    private void finishRun(String reason) {
        if (!running) {
            return;
        }
        running = false;
        stopRegenMonitor();

        try {
            writeRunSummary(reason);
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to write run summary: " + exception.getMessage());
        }

        plugin.getLogger().info("CannonLab run finished: " + reason);
        boolean shutdown = scenario != null && scenario.shutdownWhenFinished();
        scenario = null;
        targetCells = List.of();
        targetBounds = TargetBounds.empty();

        if (shutdown) {
            Bukkit.getScheduler().runTaskLater(plugin, Bukkit::shutdown, 20L);
        }
    }

    private void stopRegenMonitor() {
        if (regenMonitor != null) {
            regenMonitor.cancel();
            regenMonitor = null;
        }
    }

    private void clearArena(World world, Location origin) throws WorldEditException {
        int radiusX = plugin.getConfig().getInt("arena.radius-x", 256);
        int radiusY = plugin.getConfig().getInt("arena.radius-y", 128);
        int radiusZ = plugin.getConfig().getInt("arena.radius-z", 96);

        Location minimum = new Location(
                world,
                origin.getBlockX() - radiusX,
                Math.max(world.getMinHeight(), origin.getBlockY() - radiusY),
                origin.getBlockZ() - radiusZ
        );
        Location maximum = new Location(
                world,
                origin.getBlockX() + radiusX,
                Math.min(world.getMaxHeight() - 1, origin.getBlockY() + radiusY),
                origin.getBlockZ() + radiusZ
        );

        for (Entity entity : world.getNearbyEntities(origin, radiusX, radiusY, radiusZ)) {
            if (entity instanceof TNTPrimed || entity instanceof FallingBlock || entity instanceof Item) {
                entity.remove();
            }
        }
        worldEdit.clear(world, minimum, maximum);
    }

    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {
        List<TargetCell> cells = new ArrayList<>();
        int halfWidth = selected.targetWidth() / 2;
        BoundsBuilder bounds = new BoundsBuilder();

        for (int layer = 0; layer < selected.targetLayers(); layer++) {
            int distance = selected.targetDistance() + layer * selected.targetSpacing();

            for (int vertical = 0; vertical < selected.targetHeight(); vertical++) {
                int y = origin.getBlockY() + selected.targetYOffset() + vertical;
                if (y < world.getMinHeight() || y >= world.getMaxHeight()) {
                    throw new IllegalStateException("Target Y outside world bounds: " + y);
                }

                for (int across = 0; across < selected.targetWidth(); across++) {
                    int lateral = selected.targetLateralOffset() - halfWidth + across;
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
                    switch (selected.targetType()) {
                        case DRY -> target.setType(selected.targetMaterial(), false);
                        case WATERED -> {
                            target.setType(selected.targetMaterial(), false);
                            front.setType(Material.WATER, false);
                        }
                        case COBBLE_REGEN -> {
                            target.setType(selected.targetMaterial(), false);
                            front.setType(Material.WATER, false);
                            back.setType(Material.LAVA, false);
                        }
                        case FILTER -> target.setType(
                                checker ? selected.targetMaterial() : Material.AIR,
                                false
                        );
                        case SLAB_FILTER -> {
                            target.setType(selected.targetMaterial(), false);
                            front.setType(Material.STONE_SLAB, false);
                            BlockData data = front.getBlockData();
                            if (data instanceof Slab slab) {
                                slab.setType(checker ? Slab.Type.TOP : Slab.Type.BOTTOM);
                                front.setBlockData(slab, false);
                            }
                        }
                        case HOTDOG -> {
                            boolean solidLane = ((across / selected.hotdogBandWidth()) & 1) == 0;
                            front.setType(Material.WATER, false);
                            if (solidLane) {
                                target.setType(
                                        checker ? selected.targetMaterial() : selected.alternateMaterial(),
                                        false
                                );
                            }
                        }
                        case PILLARS -> {
                            boolean pillar = Math.floorMod(across + layer, selected.pillarSpacing()) == 0;
                            if (pillar) {
                                target.setType(selected.targetMaterial(), false);
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
                                layer
                        );
                        cells.add(cell);
                        bounds.include(cell.x(), cell.y(), cell.z());
                    }
                }
            }
        }
        if (cells.isEmpty()) {
            throw new IllegalStateException("Target configuration produced zero solid target cells.");
        }
        return new TargetBuild(List.copyOf(cells), bounds.build());
    }

    private TargetPlacement targetPlacement(
            Location origin,
            LabScenario.TargetDirection direction,
            int distance,
            int lateral,
            int y
    ) {
        int originX = origin.getBlockX();
        int originZ = origin.getBlockZ();
        return switch (direction) {
            case EAST -> new TargetPlacement(
                    originX + distance, y, originZ + lateral,
                    originX + distance - 1, originZ + lateral,
                    originX + distance + 1, originZ + lateral
            );
            case WEST -> new TargetPlacement(
                    originX - distance, y, originZ + lateral,
                    originX - distance + 1, originZ + lateral,
                    originX - distance - 1, originZ + lateral
            );
            case SOUTH -> new TargetPlacement(
                    originX + lateral, y, originZ + distance,
                    originX + lateral, originZ + distance - 1,
                    originX + lateral, originZ + distance + 1
            );
            case NORTH -> new TargetPlacement(
                    originX + lateral, y, originZ - distance,
                    originX + lateral, originZ - distance + 1,
                    originX + lateral, originZ - distance - 1
            );
        };
    }

    private void validateArenaBounds(Location origin, TargetPlacement placement) {
        int radiusX = plugin.getConfig().getInt("arena.radius-x", 256);
        int radiusY = plugin.getConfig().getInt("arena.radius-y", 128);
        int radiusZ = plugin.getConfig().getInt("arena.radius-z", 96);
        int originX = origin.getBlockX();
        int originY = origin.getBlockY();
        int originZ = origin.getBlockZ();

        int[] xs = {placement.targetX(), placement.frontX(), placement.backX()};
        int[] zs = {placement.targetZ(), placement.frontZ(), placement.backZ()};
        for (int index = 0; index < xs.length; index++) {
            if (Math.abs(xs[index] - originX) > radiusX
                    || Math.abs(placement.y() - originY) > radiusY
                    || Math.abs(zs[index] - originZ) > radiusZ) {
                throw new IllegalStateException(
                        "Target exceeds configured arena radius at "
                                + xs[index] + "," + placement.y() + "," + zs[index]
                                + ". Increase arena radius.");
            }
        }
    }

    private FillAudit auditAndFill(World world, WorldEditService.PasteResult result) {
        Map<ChunkKey, Integer> counts = new HashMap<>();
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
                    counts.merge(new ChunkKey(x >> 4, z >> 4), 1, Integer::sum);
                }
            }
        }

        ChunkKey maxChunk = null;
        int max = 0;
        for (Map.Entry<ChunkKey, Integer> entry : counts.entrySet()) {
            if (entry.getValue() > max) {
                max = entry.getValue();
                maxChunk = entry.getKey();
            }
        }
        return new FillAudit(total, max, maxChunk, new LinkedHashMap<>(counts));
    }

    private int countRemainingTargetBlocks() {
        if (targetCells.isEmpty()) {
            return 0;
        }
        World world = plugin.arenaWorld();
        int remaining = 0;
        for (TargetCell cell : targetCells) {
            if (matches(world, cell)) {
                remaining++;
            }
        }
        return remaining;
    }

    private boolean matches(World world, TargetCell cell) {
        Block block = world.getBlockAt(cell.x(), cell.y(), cell.z());
        return block.getType() == cell.material()
                && block.getBlockData().getAsString().equals(cell.blockData());
    }

    private void restore(World world, TargetCell cell) {
        Block block = world.getBlockAt(cell.x(), cell.y(), cell.z());
        block.setType(cell.material(), false);
        block.setBlockData(Bukkit.createBlockData(cell.blockData()), false);
    }

    private void writeRunSummary(String reason) throws IOException {
        Path runDirectory = plugin.getDataFolder().toPath()
                .resolve(plugin.getConfig().getString("telemetry.output-directory", "results"))
                .resolve(runId);
        Files.createDirectories(runDirectory);

        StringBuilder shotsJson = new StringBuilder();
        for (int index = 0; index < completedShots.size(); index++) {
            CompletedShot shot = completedShots.get(index);
            if (index > 0) {
                shotsJson.append(",\n");
            }
            shotsJson.append("""
                    {
                      "shot": %d,
                      "finish_reason": "%s",
                      "saw_payload": %s,
                      "explosions": %d,
                      "destroyed_blocks": %d,
                      "maximum_tnt_entities": %d,
                      "maximum_falling_blocks": %d,
                      "target_blocks_destroyed": %d,
                      "target_peak_destroyed": %d,
                      "target_ever_destroyed": %d,
                      "target_blocks_total": %d,
                      "regen_blocks_restored": %d,
                      "regen_cycles": %d,
                      "max_layer_breached": %d,
                      "error": %s
                    }
                    """.formatted(
                    shot.number(),
                    json(shot.finishReason()),
                    shot.sawPayload(),
                    shot.explosions(),
                    shot.destroyedBlocks(),
                    shot.maximumTnt(),
                    shot.maximumFallingBlocks(),
                    shot.targetDestroyed(),
                    shot.targetPeakDestroyed(),
                    shot.targetEverDestroyed(),
                    shot.targetTotal(),
                    shot.regenRestored(),
                    shot.regenCycles(),
                    shot.maxLayerBreached(),
                    shot.error() == null ? "null" : "\"" + json(shot.error()) + "\""
            ));
        }

        Location arenaOrigin = plugin.arenaOrigin(plugin.arenaWorld());
        String summary = """
                {
                  "run_id": "%s",
                  "scenario": "%s",
                  "cannon_file": "%s",
                  "target_type": "%s",
                  "target_direction": "%s",
                  "target_material": "%s",
                  "target_alternate_material": "%s",
                  "target_distance": %d,
                  "target_layers": %d,
                  "target_spacing": %d,
                  "target_bounds": %s,
                  "arena_origin": {"x": %d, "y": %d, "z": %d},
                  "regeneration": {
                    "enabled": %s,
                    "delay_ticks": %d,
                    "interval_ticks": %d,
                    "max_blocks_per_cycle": %d
                  },
                  "finished_at": "%s",
                  "finish_reason": "%s",
                  "shots_requested": %d,
                  "shots_completed": %d,
                  "shots": [
                %s
                  ]
                }
                """.formatted(
                json(runId),
                json(scenario == null ? "unknown" : scenario.name()),
                json(scenario == null ? "unknown" : scenario.cannonFile()),
                json(scenario == null ? "unknown" : scenario.targetType().name()),
                json(scenario == null ? "unknown" : scenario.targetDirection().name()),
                json(scenario == null ? "unknown" : scenario.targetMaterial().name()),
                json(scenario == null ? "unknown" : scenario.alternateMaterial().name()),
                scenario == null ? 0 : scenario.targetDistance(),
                scenario == null ? 0 : scenario.targetLayers(),
                scenario == null ? 0 : scenario.targetSpacing(),
                targetBounds.toJson(),
                arenaOrigin.getBlockX(),
                arenaOrigin.getBlockY(),
                arenaOrigin.getBlockZ(),
                scenario != null && scenario.regeneration().enabled(),
                scenario == null ? 0 : scenario.regeneration().delayTicks(),
                scenario == null ? 0 : scenario.regeneration().intervalTicks(),
                scenario == null ? 0 : scenario.regeneration().maxBlocksPerCycle(),
                Instant.now(),
                json(reason),
                scenario == null ? 0 : scenario.shots(),
                completedShots.size(),
                indent(shotsJson.toString(), 4)
        );
        Files.writeString(runDirectory.resolve("run-summary.json"), summary, StandardCharsets.UTF_8);
    }

    private static Location relative(Location base, LabScenario.BlockPoint point) {
        return base.clone().add(point.x(), point.y(), point.z());
    }

    private static String coordinates(Location location) {
        return location.getBlockX() + "," + location.getBlockY() + "," + location.getBlockZ();
    }

    private static String safeName(String value) {
        return value.toLowerCase().replaceAll("[^a-z0-9._-]+", "-");
    }

    private static String json(String value) {
        return value.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r");
    }

    private static String indent(String value, int spaces) {
        String prefix = " ".repeat(spaces);
        return prefix + value.replace("\n", "\n" + prefix);
    }

    private final class RegenMonitor {
        private final World world;
        private final List<TargetCell> cells;
        private final LabScenario.RegenConfig config;
        private final Map<TargetCell, Long> missingSince = new HashMap<>();
        private final Set<TargetCell> everDestroyed = new HashSet<>();
        private BukkitTask task;
        private long tick;
        private int peakDestroyed;
        private int restored;
        private int maxLayerBreached;
        private int cycles;

        private RegenMonitor(
                World world,
                List<TargetCell> cells,
                LabScenario.RegenConfig config
        ) {
            this.world = world;
            this.cells = cells;
            this.config = config;
        }

        private void start() {
            task = Bukkit.getScheduler().runTaskTimer(plugin, this::tickSafely, 0L, 1L);
        }

        private void tickSafely() {
            try {
                scanAndRestore(true);
                tick++;
            } catch (RuntimeException exception) {
                plugin.getLogger().severe("Regen monitor failed: " + exception.getMessage());
                exception.printStackTrace();
                cancel();
            }
        }

        private void scanAndRestore(boolean allowRestore) {
            int currentlyDestroyed = 0;
            for (TargetCell cell : cells) {
                if (!matches(world, cell)) {
                    currentlyDestroyed++;
                    if (missingSince.putIfAbsent(cell, tick) == null) {
                        everDestroyed.add(cell);
                        maxLayerBreached = Math.max(maxLayerBreached, cell.layer() + 1);
                        recorder.recordCustomEvent(
                                "TARGET_DESTROYED",
                                cell.material().name(),
                                new Location(world, cell.x(), cell.y(), cell.z()),
                                1
                        );
                    }
                } else {
                    missingSince.remove(cell);
                }
            }
            peakDestroyed = Math.max(peakDestroyed, currentlyDestroyed);

            if (!allowRestore || !config.enabled() || tick % config.intervalTicks() != 0) {
                return;
            }
            cycles++;

            List<Map.Entry<TargetCell, Long>> due = missingSince.entrySet().stream()
                    .filter(entry -> tick - entry.getValue() >= config.delayTicks())
                    .sorted(Comparator
                            .comparingLong((Map.Entry<TargetCell, Long> entry) -> entry.getValue())
                            .thenComparingInt(entry -> entry.getKey().layer()))
                    .toList();

            int restoredThisCycle = 0;
            for (Map.Entry<TargetCell, Long> entry : due) {
                if (restoredThisCycle >= config.maxBlocksPerCycle()) {
                    break;
                }
                TargetCell cell = entry.getKey();
                if (matches(world, cell)) {
                    missingSince.remove(cell);
                    continue;
                }
                restore(world, cell);
                missingSince.remove(cell);
                restored++;
                restoredThisCycle++;
                recorder.recordCustomEvent(
                        "REGEN_RESTORE",
                        cell.material().name(),
                        new Location(world, cell.x(), cell.y(), cell.z()),
                        1
                );
            }
        }

        private RegenStats stopAndSnapshot() {
            scanAndRestore(false);
            int finalDestroyed = 0;
            for (TargetCell cell : cells) {
                if (!matches(world, cell)) {
                    finalDestroyed++;
                }
            }
            cancel();
            return new RegenStats(
                    finalDestroyed,
                    peakDestroyed,
                    everDestroyed.size(),
                    restored,
                    maxLayerBreached,
                    cycles
            );
        }

        private void cancel() {
            if (task != null) {
                task.cancel();
                task = null;
            }
        }
    }

    private static final class BoundsBuilder {
        private int minX = Integer.MAX_VALUE;
        private int minY = Integer.MAX_VALUE;
        private int minZ = Integer.MAX_VALUE;
        private int maxX = Integer.MIN_VALUE;
        private int maxY = Integer.MIN_VALUE;
        private int maxZ = Integer.MIN_VALUE;

        private void include(int x, int y, int z) {
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            minZ = Math.min(minZ, z);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
            maxZ = Math.max(maxZ, z);
        }

        private TargetBounds build() {
            return new TargetBounds(minX, minY, minZ, maxX, maxY, maxZ);
        }
    }

    private record ChunkKey(int x, int z) {
    }

    private record FillAudit(
            int totalDispensers,
            int maximumPerChunk,
            ChunkKey maximumChunk,
            Map<ChunkKey, Integer> counts
    ) {
    }

    private record PulseState(
            Location location,
            Block block,
            Material previousType,
            BlockData previousData
    ) {
    }

    private record TargetPlacement(
            int targetX,
            int y,
            int targetZ,
            int frontX,
            int frontZ,
            int backX,
            int backZ
    ) {
    }

    private record TargetCell(
            int x,
            int y,
            int z,
            Material material,
            String blockData,
            int layer
    ) {
    }

    private record TargetBuild(
            List<TargetCell> cells,
            TargetBounds bounds
    ) {
    }

    private record TargetBounds(
            int minX,
            int minY,
            int minZ,
            int maxX,
            int maxY,
            int maxZ
    ) {
        private static TargetBounds empty() {
            return new TargetBounds(0, 0, 0, 0, 0, 0);
        }

        private String toJson() {
            return """
                    {"min_x": %d, "min_y": %d, "min_z": %d, "max_x": %d, "max_y": %d, "max_z": %d}
                    """.formatted(minX, minY, minZ, maxX, maxY, maxZ).trim();
        }
    }

    private record RegenStats(
            int finalDestroyed,
            int peakDestroyed,
            int everDestroyed,
            int restored,
            int maxLayerBreached,
            int cycles
    ) {
        private static RegenStats empty() {
            return new RegenStats(0, 0, 0, 0, 0, 0);
        }
    }

    private record CompletedShot(
            int number,
            String finishReason,
            boolean sawPayload,
            int explosions,
            int destroyedBlocks,
            int targetDestroyed,
            int targetPeakDestroyed,
            int targetEverDestroyed,
            int targetTotal,
            int regenRestored,
            int maxLayerBreached,
            int regenCycles,
            int maximumTnt,
            int maximumFallingBlocks,
            String error
    ) {
        private static CompletedShot preparationError(
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
    }
}
