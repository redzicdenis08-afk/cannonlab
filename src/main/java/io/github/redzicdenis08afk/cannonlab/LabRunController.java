package io.github.redzicdenis08afk.cannonlab;

import com.sk89q.worldedit.WorldEditException;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.BlockState;
import org.bukkit.block.Dispenser;
import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.type.Slab;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.Item;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.inventory.ItemStack;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

final class LabRunController {
    private static final int DISPENSER_LIMIT_PER_CHUNK = 128;

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
        return "running scenario=" + scenario.name() + " shot=" + shotNumber + "/" + scenario.shots();
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
        sender.sendMessage("CannonLab run started: " + scenario.name() + " x" + scenario.shots());
        prepareNextShot();
    }

    void cancel(CommandSender sender) {
        if (!running) {
            sender.sendMessage("No CannonLab run is active.");
            return;
        }
        cancelled = true;
        recorder.cancel();
        finishRun("cancelled");
        sender.sendMessage("CannonLab run cancelled.");
    }

    private void prepareNextShot() {
        if (!running || cancelled) {
            return;
        }
        shotNumber++;

        try {
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

            targetCells = buildTarget(world, arenaOrigin, scenario);
            FillAudit audit = auditAndFill(world, pasteResult);
            if (audit.maximumPerChunk() > DISPENSER_LIMIT_PER_CHUNK) {
                throw new IllegalStateException(
                        "Dispenser limit exceeded: " + audit.maximumPerChunk()
                                + " in chunk " + audit.maximumChunk());
            }

            plugin.getLogger().info("Prepared shot " + shotNumber
                    + " | dispensers=" + audit.totalDispensers()
                    + " | max/chunk=" + audit.maximumPerChunk());

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

            Bukkit.getScheduler().runTaskLater(plugin,
                    () -> pulseFireInput(world, pasteOrigin),
                    scenario.warmupTicks());
        } catch (IOException | WorldEditException | RuntimeException exception) {
            plugin.getLogger().severe("Run preparation failed: " + exception.getMessage());
            completedShots.add(new CompletedShot(
                    shotNumber,
                    "preparation_error",
                    false,
                    0,
                    0,
                    0,
                    targetCells.size(),
                    exception.getClass().getSimpleName() + ": " + exception.getMessage()
            ));
            finishRun("error");
        }
    }

    private void shotCompleted(ShotRecorder.ShotResult result) {
        int remaining = countRemainingTargetBlocks();
        int destroyedTarget = Math.max(0, targetCells.size() - remaining);
        completedShots.add(new CompletedShot(
                shotNumber,
                result.finishReason(),
                result.sawPayload(),
                result.explosions(),
                result.destroyedBlocks(),
                destroyedTarget,
                targetCells.size(),
                null
        ));

        plugin.getLogger().info("Shot " + shotNumber
                + " complete | payload=" + result.sawPayload()
                + " | explosions=" + result.explosions()
                + " | target=" + destroyedTarget + "/" + targetCells.size());

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

        try {
            writeRunSummary(reason);
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to write run summary: " + exception.getMessage());
        }

        plugin.getLogger().info("CannonLab run finished: " + reason);
        boolean shutdown = scenario != null && scenario.shutdownWhenFinished();
        scenario = null;
        targetCells = List.of();

        if (shutdown) {
            Bukkit.getScheduler().runTaskLater(plugin, Bukkit::shutdown, 20L);
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

    private List<TargetCell> buildTarget(World world, Location origin, LabScenario selected) {
        List<TargetCell> cells = new ArrayList<>();
        int halfWidth = selected.targetWidth() / 2;

        for (int layer = 0; layer < selected.targetLayers(); layer++) {
            int wallX = origin.getBlockX() + selected.targetDistance()
                    + layer * selected.targetSpacing();

            for (int y = origin.getBlockY(); y < origin.getBlockY() + selected.targetHeight(); y++) {
                for (int z = origin.getBlockZ() - halfWidth;
                     z < origin.getBlockZ() - halfWidth + selected.targetWidth(); z++) {
                    Block target = world.getBlockAt(wallX, y, z);

                    switch (selected.targetType()) {
                        case DRY -> target.setType(Material.OBSIDIAN, false);
                        case WATERED -> {
                            target.setType(Material.OBSIDIAN, false);
                            world.getBlockAt(wallX - 1, y, z).setType(Material.WATER, false);
                        }
                        case COBBLE_REGEN -> {
                            target.setType(Material.COBBLESTONE, false);
                            world.getBlockAt(wallX - 1, y, z).setType(Material.WATER, false);
                            world.getBlockAt(wallX + 1, y, z).setType(Material.LAVA, false);
                        }
                        case FILTER -> {
                            if ((y + z) % 2 == 0) {
                                target.setType(Material.OBSIDIAN, false);
                            } else {
                                target.setType(Material.AIR, false);
                            }
                        }
                        case SLAB_FILTER -> {
                            target.setType(Material.OBSIDIAN, false);
                            Block slabBlock = world.getBlockAt(wallX - 1, y, z);
                            slabBlock.setType(Material.STONE_SLAB, false);
                            BlockData data = slabBlock.getBlockData();
                            if (data instanceof Slab slab) {
                                slab.setType((y + z) % 2 == 0 ? Slab.Type.TOP : Slab.Type.BOTTOM);
                                slabBlock.setBlockData(slab, false);
                            }
                        }
                    }

                    if (!target.isEmpty()) {
                        cells.add(new TargetCell(target.getX(), target.getY(), target.getZ(), target.getType()));
                    }
                }
            }
        }
        return cells;
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

    private void pulseFireInput(World world, Location pasteOrigin) {
        if (!running || cancelled) {
            return;
        }
        Location pulseLocation = relative(pasteOrigin, scenario.fireInput());
        Block block = world.getBlockAt(pulseLocation);
        Material previousType = block.getType();
        BlockData previousData = block.getBlockData().clone();

        block.setType(Material.REDSTONE_BLOCK, true);
        Bukkit.getScheduler().runTaskLater(plugin, () -> {
            block.setType(previousType, false);
            block.setBlockData(previousData, true);
        }, scenario.firePulseTicks());
    }

    private int countRemainingTargetBlocks() {
        if (targetCells.isEmpty()) {
            return 0;
        }
        World world = plugin.arenaWorld();
        int remaining = 0;
        for (TargetCell cell : targetCells) {
            if (world.getBlockAt(cell.x(), cell.y(), cell.z()).getType() == cell.material()) {
                remaining++;
            }
        }
        return remaining;
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
                      "target_blocks_destroyed": %d,
                      "target_blocks_total": %d,
                      "error": %s
                    }
                    """.formatted(
                    shot.number(),
                    json(shot.finishReason()),
                    shot.sawPayload(),
                    shot.explosions(),
                    shot.destroyedBlocks(),
                    shot.targetDestroyed(),
                    shot.targetTotal(),
                    shot.error() == null ? "null" : "\"" + json(shot.error()) + "\""
            ));
        }

        String summary = """
                {
                  "run_id": "%s",
                  "scenario": "%s",
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

    private record ChunkKey(int x, int z) {
    }

    private record FillAudit(
            int totalDispensers,
            int maximumPerChunk,
            ChunkKey maximumChunk,
            Map<ChunkKey, Integer> counts
    ) {
    }

    private record TargetCell(int x, int y, int z, Material material) {
    }

    private record CompletedShot(
            int number,
            String finishReason,
            boolean sawPayload,
            int explosions,
            int destroyedBlocks,
            int targetDestroyed,
            int targetTotal,
            String error
    ) {
    }
}
