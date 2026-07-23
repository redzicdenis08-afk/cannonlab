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
import org.bukkit.block.data.type.Slab;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.Item;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockExplodeEvent;
import org.bukkit.event.entity.EntityExplodeEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.Vector;

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

final class LabRunController implements Listener {
    private static final int DEFAULT_DISPENSER_LIMIT_PER_CHUNK = 160;
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
    private List<CompanionCell> targetCompanions = List.of();
    private Map<BlockKey, TargetCell> targetCellsByPosition = Map.of();
    private TargetBounds targetBounds = TargetBounds.empty();
    private RegenMonitor regenMonitor;
    private final Map<BlockKey, DurabilityState> durabilityStates = new HashMap<>();
    private Map<BlockKey, String> cannonSnapshot = Map.of();
    private int durabilityHits;
    private int durabilityBreaks;

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
            boolean disposableFreshWorld = shotNumber == 1
                    && Boolean.parseBoolean(System.getProperty("cannonlab.fresh-world", "false"));
            if (!disposableFreshWorld) {
                clearArena(world, arenaOrigin);
            }

            File schematic = plugin.resolveCannonFile(scenario.cannonFile());
            Location pasteOrigin = relative(arenaOrigin, scenario.cannonOrigin());
            WorldEditService.PasteResult pasteResult = worldEdit.paste(
                    world,
                    schematic,
                    pasteOrigin,
                    false,
                    scenario.suppressPasteSideEffects()
            );

            TargetBuild targetBuild = scenario.targetFile().isBlank()
                    ? buildTarget(world, arenaOrigin, scenario)
                    : buildTargetFromSchematic(world, arenaOrigin, scenario);
            targetCells = targetBuild.cells();
            targetCompanions = targetBuild.companions();
            targetCellsByPosition = indexTargetCells(targetCells);
            targetBounds = targetBuild.bounds();
            durabilityStates.clear();
            durabilityHits = 0;
            durabilityBreaks = 0;
            LabScenario.DurabilityMode durabilityMode = effectiveDurabilityMode();

            FillAudit audit = auditDispensers(world, pasteResult);
            int dispenserLimitPerChunk = dispenserLimitPerChunk();
            if (scenario.enforceDispenserLimit()
                    && audit.maximumPerChunk() > dispenserLimitPerChunk) {
                throw new IllegalStateException(
                        "Dispenser limit exceeded: " + audit.maximumPerChunk()
                                + " in chunk " + audit.maximumChunk()
                                + " (configured limit " + dispenserLimitPerChunk + ")");
            }
            if (audit.totalDispensers() == 0) {
                throw new IllegalStateException("Pasted schematic contains no dispensers.");
            }
            cannonSnapshot = snapshotCannon(world, pasteResult);

            plugin.getLogger().info("Prepared shot " + shotNumber
                    + " | dispensers=" + audit.totalDispensers()
                    + " | max/chunk=" + audit.maximumPerChunk()
                    + " | dispenserLimit/chunk=" + dispenserLimitPerChunk
                    + " | fireMode=" + scenario.fireMode()
                    + " | inputs=" + scenario.fireInputs().size()
                    + " | target=" + scenario.targetType() + "/" + scenario.targetDirection()
                    + " | targetCells=" + targetCells.size()
                    + " | companionCells=" + targetCompanions.size()
                    + " | regen=" + scenario.regeneration()
                    + " | durability=" + durabilityMode
                    + " | volleys=" + scenario.volleysPerShot());

            long fillDelay = scenario.settleBeforeFillTicks();
            long fireDelay = Math.max(
                    scenario.warmupTicks(),
                    fillDelay + scenario.fillToFireTicks()
            );
            long lastVolleyDelay = fireDelay
                    + (long) (scenario.volleysPerShot() - 1) * scenario.volleyIntervalTicks();
            int minimumTicksBeforeQuiet = boundedTicks(lastVolleyDelay + scenario.quietTicks());
            int effectiveMaxShotTicks = Math.max(
                    scenario.maxShotTicks(),
                    boundedTicks(lastVolleyDelay + scenario.quietTicks() + 20L)
            );

            recorder.start(
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
                    effectiveMaxShotTicks,
                    scenario.quietTicks(),
                    minimumTicksBeforeQuiet,
                    scenario.targetDirection(),
                    this::shotCompleted
            );

            regenMonitor = new RegenMonitor(
                    world,
                    targetCells,
                    targetCompanions
            );
            regenMonitor.start();

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

            for (int volley = 1; volley <= scenario.volleysPerShot(); volley++) {
                int scheduledVolley = volley;
                long volleyDelay = fireDelay
                        + (long) (volley - 1) * scenario.volleyIntervalTicks();
                Bukkit.getScheduler().runTaskLater(plugin, () -> {
                    try {
                        recorder.recordControlEvent(
                                "VOLLEY_FIRE",
                                pasteOrigin,
                                "volley=" + scheduledVolley + "/" + scenario.volleysPerShot()
                        );
                        fire(world, arenaOrigin, pasteOrigin);
                    } catch (RuntimeException exception) {
                        plugin.getLogger().severe("Shot " + shotNumber
                                + " volley " + scheduledVolley
                                + " firing failed: " + exception.getMessage());
                        exception.printStackTrace();
                    }
                }, volleyDelay);
            }
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

    private void fire(World world, Location arenaOrigin, Location pasteOrigin) {
        if (!running || cancelled || scenario == null) {
            return;
        }

        switch (scenario.fireMode()) {
            case DIRECT_DISPENSE -> dispenseDirectly(world, pasteOrigin);
            case BUTTON -> pressButtons(world, pasteOrigin);
            case REDSTONE -> pulseRedstone(world, pasteOrigin);
            case TNT_PROBE -> spawnTntProbe(world, arenaOrigin);
        }
    }

    private void spawnTntProbe(World world, Location arenaOrigin) {
        Location spawn = relative(arenaOrigin, scenario.probeTntOrigin()).add(0.5, 0.1, 0.5);
        recorder.recordControlEvent(
                "FIRE_INPUT",
                spawn,
                "mode=tnt-probe;diagnostic=true;fuse=" + scenario.probeTntFuseTicks()
        );
        TNTPrimed tnt = world.spawn(spawn, TNTPrimed.class);
        tnt.setGravity(false);
        tnt.setVelocity(new Vector(0.0, 0.0, 0.0));
        tnt.setFuseTicks(scenario.probeTntFuseTicks());
        plugin.getLogger().info("Diagnostic TNT probe spawned at " + coordinates(spawn)
                + " | fuse=" + scenario.probeTntFuseTicks());
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

    private void pressButtons(World world, Location pasteOrigin) {
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
                    + " | neighbours=" + describeNeighbours(pulse.block()));
            recorder.recordControlEvent(
                    "FIRE_INPUT",
                    pulse.location(),
                    "previous=" + pulse.previousType() + ";pulse_ticks=" + scenario.firePulseTicks()
            );
            pulse.block().setType(Material.REDSTONE_BLOCK, true);
            BlockState pulseState = pulse.block().getState();
            pulseState.update(true, true);
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

    private int boundedTicks(long ticks) {
        return (int) Math.min(Integer.MAX_VALUE, Math.max(0L, ticks));
    }

    private void shotCompleted(ShotRecorder.ShotResult result) {
        RegenStats regenStats = regenMonitor == null
                ? RegenStats.empty()
                : regenMonitor.stopAndSnapshot();
        regenMonitor = null;

        int remaining = countRemainingTargetBlocks();
        int finalDestroyed = Math.max(0, targetCells.size() - remaining);
        CannonIntegrity integrity = inspectCannonIntegrity();
        try {
            writeIntegrityDiff(result.directory(), integrity);
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to write cannon integrity diff: "
                    + exception.getMessage());
        }
        List<String> contractFailures = contractFailures(result, integrity, finalDestroyed);
        completedShots.add(new CompletedShot(
                shotNumber,
                result.finishReason(),
                result.sawPayload(),
                result.explosions(),
                result.destroyedBlocks(),
                result.selfDamageBlocks(),
                finalDestroyed,
                regenStats.peakDestroyed(),
                regenStats.everDestroyed(),
                targetCells.size(),
                regenStats.restored(),
                regenStats.maxLayerBreached(),
                regenStats.cycles(),
                regenStats.finalCompanionMissing(),
                regenStats.companionPeakMissing(),
                regenStats.everCompanionMissing(),
                regenStats.companionRestored(),
                durabilityHits,
                durabilityBreaks,
                result.maximumTnt(),
                result.maximumFallingBlocks(),
                result.maximumForwardDistance(),
                result.minimumForwardDistance(),
                integrity,
                contractFailures,
                null
        ));

        plugin.getLogger().info("Shot " + shotNumber
                + " complete | payload=" + result.sawPayload()
                + " | explosions=" + result.explosions()
                + " | maxTnt=" + result.maximumTnt()
                + " | maxForward="
                + String.format(java.util.Locale.ROOT, "%.3f", result.maximumForwardDistance())
                + " | selfDamage=" + result.selfDamageBlocks()
                + " | integrity=" + integrity.sameState() + "/" + integrity.initial()
                + " | stateChanged=" + integrity.stateChanged()
                + " | missing=" + integrity.missing()
                + " | replacedType=" + integrity.replacedType()
                + " | dispensers=" + integrity.dispensersRemaining()
                + "/" + integrity.dispensersInitial()
                + " | targetFinal=" + finalDestroyed + "/" + targetCells.size()
                + " | targetPeak=" + regenStats.peakDestroyed()
                + " | regenRestored=" + regenStats.restored()
                + " | companionMissing=" + regenStats.finalCompanionMissing()
                + " | companionRestored=" + regenStats.companionRestored()
                + " | maxLayer=" + regenStats.maxLayerBreached()
                + " | contractPass=" + contractFailures.isEmpty()
                + (contractFailures.isEmpty() ? "" : " | failures=" + contractFailures));

        if (cancelled) {
            finishRun("cancelled");
        } else if (shotNumber < scenario.shots()) {
            Bukkit.getScheduler().runTaskLater(plugin, this::prepareNextShot, 20L);
        } else {
            boolean contractPass = completedShots.stream().allMatch(CompletedShot::contractPass);
            finishRun(contractPass ? "complete" : "contract_failed");
        }
    }

    private List<String> contractFailures(
            ShotRecorder.ShotResult result,
            CannonIntegrity integrity,
            int targetDestroyed
    ) {
        LabScenario.AcceptanceConfig acceptance = scenario.acceptance();
        List<String> failures = new ArrayList<>();
        if (acceptance.requirePayload() && !result.sawPayload()) {
            failures.add("payload_not_observed");
        }
        if (targetDestroyed < acceptance.minTargetDestroyed()) {
            failures.add("target_destroyed=" + targetDestroyed
                    + "<" + acceptance.minTargetDestroyed());
        }
        if (result.maximumFallingBlocks() < acceptance.minFallingBlocks()) {
            failures.add("falling_blocks=" + result.maximumFallingBlocks()
                    + "<" + acceptance.minFallingBlocks());
        }
        if (result.maximumForwardDistance() + 1.0e-12 < acceptance.minForwardDistance()) {
            failures.add("forward_distance="
                    + String.format(java.util.Locale.ROOT, "%.6f", result.maximumForwardDistance())
                    + "<" + acceptance.minForwardDistance());
        }
        double remainingRatio = integrity.dispensersInitial() == 0
                ? 0.0
                : (double) integrity.dispensersRemaining() / integrity.dispensersInitial();
        if (remainingRatio + 1.0e-12 < acceptance.minRemainingDispenserRatio()) {
            failures.add("remaining_dispenser_ratio="
                    + String.format(java.util.Locale.ROOT, "%.6f", remainingRatio)
                    + "<" + acceptance.minRemainingDispenserRatio());
        }
        if (integrity.missing() > acceptance.maxCannonMissingBlocks()) {
            failures.add("cannon_missing=" + integrity.missing()
                    + ">" + acceptance.maxCannonMissingBlocks());
        }
        if (integrity.replacedType() > acceptance.maxCannonReplacedTypeBlocks()) {
            failures.add("cannon_replaced_type=" + integrity.replacedType()
                    + ">" + acceptance.maxCannonReplacedTypeBlocks());
        }
        if (result.selfDamageBlocks() > acceptance.maxSelfDamageBlocks()) {
            failures.add("self_damage=" + result.selfDamageBlocks()
                    + ">" + acceptance.maxSelfDamageBlocks());
        }
        return List.copyOf(failures);
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
        targetCompanions = List.of();
        targetCellsByPosition = Map.of();
        durabilityStates.clear();
        targetBounds = TargetBounds.empty();
        cannonSnapshot = Map.of();

        if (shutdown) {
            Bukkit.getScheduler().runTaskLater(plugin, Bukkit::shutdown, 20L);
        }
    }

    private Map<BlockKey, String> snapshotCannon(
            World world,
            WorldEditService.PasteResult result
    ) {
        Map<BlockKey, String> snapshot = new HashMap<>();
        for (int x = result.minimum().x(); x <= result.maximum().x(); x++) {
            for (int y = Math.max(world.getMinHeight(), result.minimum().y());
                 y <= Math.min(world.getMaxHeight() - 1, result.maximum().y()); y++) {
                for (int z = result.minimum().z(); z <= result.maximum().z(); z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (!block.isEmpty()) {
                        snapshot.put(new BlockKey(x, y, z), block.getBlockData().getAsString());
                    }
                }
            }
        }
        return Map.copyOf(snapshot);
    }

    private CannonIntegrity inspectCannonIntegrity() {
        if (cannonSnapshot.isEmpty()) {
            return CannonIntegrity.empty();
        }
        World world = plugin.arenaWorld();
        int sameState = 0;
        int stateChanged = 0;
        int missing = 0;
        int replacedType = 0;
        int dispensersInitial = 0;
        int dispensersRemaining = 0;
        List<BlockDifference> differences = new ArrayList<>();
        for (Map.Entry<BlockKey, String> entry : cannonSnapshot.entrySet()) {
            BlockKey key = entry.getKey();
            Block block = world.getBlockAt(key.x(), key.y(), key.z());
            String expectedState = entry.getValue();
            String expectedType = blockType(expectedState);
            if (expectedType.equals("minecraft:dispenser")) {
                dispensersInitial++;
            }
            if (block.isEmpty()) {
                missing++;
                differences.add(new BlockDifference(
                        "missing", key.x(), key.y(), key.z(), expectedState, "minecraft:air"));
            } else if (!block.getType().getKey().toString().equals(expectedType)) {
                replacedType++;
                differences.add(new BlockDifference(
                        "replaced_type", key.x(), key.y(), key.z(),
                        expectedState, block.getBlockData().getAsString()));
            } else if (block.getBlockData().getAsString().equals(expectedState)) {
                sameState++;
            } else {
                stateChanged++;
                differences.add(new BlockDifference(
                        "state_changed", key.x(), key.y(), key.z(),
                        expectedState, block.getBlockData().getAsString()));
            }
            if (block.getState() instanceof Dispenser) {
                dispensersRemaining++;
            }
        }
        return new CannonIntegrity(
                cannonSnapshot.size(),
                sameState,
                stateChanged,
                missing,
                replacedType,
                dispensersInitial,
                dispensersRemaining,
                differences
        );
    }

    private void writeIntegrityDiff(Path directory, CannonIntegrity integrity) throws IOException {
        Files.createDirectories(directory);
        StringBuilder csv = new StringBuilder(
                "kind,x,y,z,expected_block_data,actual_block_data\n");
        for (BlockDifference difference : integrity.differences()) {
            csv.append(difference.kind()).append(',')
                    .append(difference.x()).append(',')
                    .append(difference.y()).append(',')
                    .append(difference.z()).append(',')
                    .append(csv(difference.expected())).append(',')
                    .append(csv(difference.actual())).append('\n');
        }
        Files.writeString(
                directory.resolve("cannon-integrity.csv"),
                csv,
                StandardCharsets.UTF_8
        );
    }

    private static String csv(String value) {
        return "\"" + value.replace("\"", "\"\"") + "\"";
    }

    private static String blockType(String blockData) {
        int properties = blockData.indexOf('[');
        return properties < 0 ? blockData : blockData.substring(0, properties);
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

    private TargetBuild buildTargetFromSchematic(
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
        Map<BlockKey, CompanionCell> companions = new LinkedHashMap<>();
        BoundsBuilder bounds = new BoundsBuilder();
        for (int x = result.minimum().x(); x <= result.maximum().x(); x++) {
            for (int y = Math.max(world.getMinHeight(), result.minimum().y());
                 y <= Math.min(world.getMaxHeight() - 1, result.maximum().y()); y++) {
                for (int z = result.minimum().z(); z <= result.maximum().z(); z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (block.isEmpty()) {
                        continue;
                    }
                    validateArenaCoordinate(arenaOrigin, x, y, z);
                    int layer = switch (selected.targetDirection()) {
                        case EAST -> x - result.minimum().x();
                        case WEST -> result.maximum().x() - x;
                        case SOUTH -> z - result.minimum().z();
                        case NORTH -> result.maximum().z() - z;
                    };
                    if (block.getType().isSolid()) {
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
                    } else {
                        CompanionCell companion = new CompanionCell(
                                x,
                                y,
                                z,
                                block.getType(),
                                block.getBlockData().getAsString(),
                                layer,
                                0,
                                "schematic:" + selected.targetFile(),
                                "schematic-non-solid",
                                selected.regeneration()
                        );
                        companions.put(new BlockKey(x, y, z), companion);
                    }
                    bounds.include(x, y, z);
                }
            }
        }
        if (cells.isEmpty()) {
            throw new IllegalStateException("Target schematic contains no solid target blocks: " + selected.targetFile());
        }
        return new TargetBuild(
                List.copyOf(cells),
                List.copyOf(companions.values()),
                bounds.build()
        );
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

    private TargetBuild buildTarget(World world, Location origin, LabScenario selected) {
        List<TargetCell> cells = new ArrayList<>();
        Map<BlockKey, CompanionCell> companions = new LinkedHashMap<>();
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
                        captureCompanion(
                                companions,
                                bounds,
                                front,
                                globalLayer,
                                stageIndex,
                                stage.name(),
                                "front",
                                stage.regeneration()
                        );
                        captureCompanion(
                                companions,
                                bounds,
                                back,
                                globalLayer,
                                stageIndex,
                                stage.name(),
                                "back",
                                stage.regeneration()
                        );
                    }
                }
                globalLayer++;
            }

            stageDistance += (stage.layers() - 1) * stage.spacing() + stage.gapAfter();
        }
        if (cells.isEmpty()) {
            throw new IllegalStateException("Target configuration produced zero solid target cells.");
        }
        return new TargetBuild(
                List.copyOf(cells),
                List.copyOf(companions.values()),
                bounds.build()
        );
    }

    private void captureCompanion(
            Map<BlockKey, CompanionCell> companions,
            BoundsBuilder bounds,
            Block block,
            int layer,
            int stageIndex,
            String stageName,
            String role,
            LabScenario.RegenConfig regeneration
    ) {
        if (block.isEmpty()) {
            return;
        }
        CompanionCell cell = new CompanionCell(
                block.getX(),
                block.getY(),
                block.getZ(),
                block.getType(),
                block.getBlockData().getAsString(),
                layer,
                stageIndex,
                stageName,
                role,
                regeneration
        );
        companions.put(new BlockKey(cell.x(), cell.y(), cell.z()), cell);
        bounds.include(cell.x(), cell.y(), cell.z());
    }

    private void writeTargetCourse(Path runDirectory) throws IOException {
        if (scenario == null) {
            return;
        }
        if (!scenario.targetFile().isBlank()) {
            String exactCourse = "{\n"
                    + "  \"direction\": \"" + json(scenario.targetDirection().name()) + "\",\n"
                    + "  \"source_file\": \"" + json(scenario.targetFile()) + "\",\n"
                    + "  \"stage_count\": 0,\n"
                    + "  \"stages\": []\n"
                    + "}\n";
            Files.writeString(runDirectory.resolve("target-course.json"), exactCourse, StandardCharsets.UTF_8);
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

    private FillAudit auditDispensers(World world, WorldEditService.PasteResult result) {
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

    private int fillDispensers(World world, WorldEditService.PasteResult result) {
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

    private int dispenserLimitPerChunk() {
        int configured = plugin.getConfig().getInt(
                "limits.dispensers-per-chunk",
                DEFAULT_DISPENSER_LIMIT_PER_CHUNK
        );
        if (configured < 1) {
            throw new IllegalStateException(
                    "limits.dispensers-per-chunk must be at least 1, got " + configured
            );
        }
        return configured;
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onEntityExplode(EntityExplodeEvent event) {
        applyDurability(
                event.getLocation(),
                event.blockList(),
                event.getEntity() instanceof TNTPrimed
        );
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onBlockExplode(BlockExplodeEvent event) {
        applyDurability(event.getBlock().getLocation(), event.blockList(), false);
    }

    private void applyDurability(Location center, List<Block> affectedBlocks, boolean tntExplosion) {
        if (!running || scenario == null || center.getWorld() == null) {
            return;
        }
        LabScenario.DurabilityConfig config = scenario.durability();
        if (!config.enabled() || effectiveDurabilityMode() != LabScenario.DurabilityMode.SIMULATE) {
            return;
        }
        if (config.onlyTnt() && !tntExplosion) {
            return;
        }
        World world = center.getWorld();
        if (!world.equals(plugin.arenaWorld())) {
            return;
        }

        double radiusSquared = config.hitRadius() * config.hitRadius();
        Set<BlockKey> candidates = new HashSet<>();
        for (Block block : affectedBlocks) {
            BlockKey key = new BlockKey(block.getX(), block.getY(), block.getZ());
            TargetCell cell = targetCellsByPosition.get(key);
            if (cell != null && config.materials().containsKey(cell.material())) {
                candidates.add(key);
            }
        }
        for (TargetCell cell : targetCells) {
            if (!config.materials().containsKey(cell.material())) {
                continue;
            }
            double dx = cell.x() + 0.5 - center.getX();
            double dy = cell.y() + 0.5 - center.getY();
            double dz = cell.z() + 0.5 - center.getZ();
            if (dx * dx + dy * dy + dz * dz <= radiusSquared) {
                candidates.add(new BlockKey(cell.x(), cell.y(), cell.z()));
            }
        }

        long gameTime = world.getGameTime();
        for (BlockKey key : candidates) {
            TargetCell cell = targetCellsByPosition.get(key);
            if (cell == null || !matches(world, cell)) {
                continue;
            }
            int fullDurability = config.hitsToBreak(cell.material());
            DurabilityState prior = durabilityStates.get(key);
            int remainingBefore = fullDurability;
            if (prior != null && gameTime - prior.lastHitTick() <= config.expirationTicks()) {
                remainingBefore = prior.remaining();
            }
            int remainingAfter = remainingBefore - 1;
            if (remainingAfter <= 0) {
                durabilityStates.remove(key);
                durabilityBreaks++;
                removeFromExplosionList(affectedBlocks, key);
                Bukkit.getScheduler().runTask(plugin, () -> {
                    if (matches(world, cell)) {
                        world.getBlockAt(cell.x(), cell.y(), cell.z()).setType(Material.AIR, false);
                    }
                });
                recorder.recordCustomEvent(
                        "DURABILITY_BREAK",
                        cell.stageName() + ":" + cell.material().name()
                                + ":hits=" + fullDurability,
                        new Location(world, cell.x(), cell.y(), cell.z()),
                        1
                );
            } else {
                durabilityStates.put(key, new DurabilityState(remainingAfter, gameTime));
                durabilityHits++;
                removeFromExplosionList(affectedBlocks, key);
                recorder.recordCustomEvent(
                        "DURABILITY_HIT",
                        cell.stageName() + ":" + cell.material().name()
                                + ":remaining=" + remainingAfter + "/" + fullDurability,
                        new Location(world, cell.x(), cell.y(), cell.z()),
                        0
                );
            }
        }
    }

    private void removeFromExplosionList(List<Block> affectedBlocks, BlockKey key) {
        affectedBlocks.removeIf(block -> block.getX() == key.x()
                && block.getY() == key.y()
                && block.getZ() == key.z());
    }

    private Map<BlockKey, TargetCell> indexTargetCells(List<TargetCell> cells) {
        Map<BlockKey, TargetCell> index = new HashMap<>();
        for (TargetCell cell : cells) {
            BlockKey key = new BlockKey(cell.x(), cell.y(), cell.z());
            TargetCell previous = index.put(key, cell);
            if (previous != null) {
                throw new IllegalStateException("Duplicate target cell at " + key);
            }
        }
        return Map.copyOf(index);
    }

    private LabScenario.DurabilityMode effectiveDurabilityMode() {
        if (scenario == null || !scenario.durability().enabled()) {
            return LabScenario.DurabilityMode.DISABLED;
        }
        boolean nativeAvailable = nativeSakuraDurabilityAvailable();
        return switch (scenario.durability().mode()) {
            case DISABLED -> LabScenario.DurabilityMode.DISABLED;
            case SIMULATE -> LabScenario.DurabilityMode.SIMULATE;
            case AUTO -> nativeAvailable
                    ? LabScenario.DurabilityMode.NATIVE
                    : LabScenario.DurabilityMode.SIMULATE;
            case NATIVE -> {
                if (!nativeAvailable) {
                    throw new IllegalStateException(
                            "Native Sakura durability requested, but Sakura durable-block classes are unavailable"
                    );
                }
                yield LabScenario.DurabilityMode.NATIVE;
            }
        };
    }

    private boolean nativeSakuraDurabilityAvailable() {
        try {
            Class.forName(
                    "me.samsuik.sakura.explosion.DurableBlockManager",
                    false,
                    getClass().getClassLoader()
            );
            return true;
        } catch (ClassNotFoundException ignored) {
            return false;
        }
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

    private boolean matches(World world, CompanionCell cell) {
        Block block = world.getBlockAt(cell.x(), cell.y(), cell.z());
        return block.getType() == cell.material()
                && block.getBlockData().getAsString().equals(cell.blockData());
    }

    private void restore(World world, TargetCell cell) {
        Block block = world.getBlockAt(cell.x(), cell.y(), cell.z());
        block.setType(cell.material(), false);
        block.setBlockData(Bukkit.createBlockData(cell.blockData()), false);
        durabilityStates.remove(new BlockKey(cell.x(), cell.y(), cell.z()));
    }

    private void restore(World world, CompanionCell cell) {
        Block block = world.getBlockAt(cell.x(), cell.y(), cell.z());
        block.setType(cell.material(), false);
        block.setBlockData(Bukkit.createBlockData(cell.blockData()), false);
    }

    private void writeRunSummary(String reason) throws IOException {
        Path runDirectory = plugin.getDataFolder().toPath()
                .resolve(plugin.getConfig().getString("telemetry.output-directory", "results"))
                .resolve(runId);
        Files.createDirectories(runDirectory);
        writeTargetCourse(runDirectory);

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
                      "self_damage_blocks": %d,
                      "maximum_tnt_entities": %d,
                      "maximum_falling_blocks": %d,
                      "maximum_forward_distance": %.6f,
                      "minimum_forward_distance": %.6f,
                      "cannon_initial_blocks": %d,
                      "cannon_same_state_blocks": %d,
                      "cannon_state_changed_blocks": %d,
                      "cannon_missing_blocks": %d,
                      "cannon_replaced_type_blocks": %d,
                      "cannon_initial_dispensers": %d,
                      "cannon_remaining_dispensers": %d,
                      "target_blocks_destroyed": %d,
                      "target_peak_destroyed": %d,
                      "target_ever_destroyed": %d,
                      "target_blocks_total": %d,
                      "regen_blocks_restored": %d,
                      "regen_cycles": %d,
                      "max_layer_breached": %d,
                      "companion_cells_missing": %d,
                      "companion_peak_missing": %d,
                      "companion_ever_missing": %d,
                      "companion_cells_restored": %d,
                      "durability_hits": %d,
                      "durability_breaks": %d,
                      "contract_pass": %s,
                      "contract_failures": %s,
                      "error": %s
                    }
                    """.formatted(
                    shot.number(),
                    json(shot.finishReason()),
                    shot.sawPayload(),
                    shot.explosions(),
                    shot.destroyedBlocks(),
                    shot.selfDamageBlocks(),
                    shot.maximumTnt(),
                    shot.maximumFallingBlocks(),
                    shot.maximumForwardDistance(),
                    shot.minimumForwardDistance(),
                    shot.integrity().initial(),
                    shot.integrity().sameState(),
                    shot.integrity().stateChanged(),
                    shot.integrity().missing(),
                    shot.integrity().replacedType(),
                    shot.integrity().dispensersInitial(),
                    shot.integrity().dispensersRemaining(),
                    shot.targetDestroyed(),
                    shot.targetPeakDestroyed(),
                    shot.targetEverDestroyed(),
                    shot.targetTotal(),
                    shot.regenRestored(),
                    shot.regenCycles(),
                    shot.maxLayerBreached(),
                    shot.companionMissing(),
                    shot.companionPeakMissing(),
                    shot.companionEverMissing(),
                    shot.companionRestored(),
                    shot.durabilityHits(),
                    shot.durabilityBreaks(),
                    shot.contractPass(),
                    jsonArray(shot.contractFailures()),
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
                  "target_companion_cells": %d,
                  "arena_origin": {"x": %d, "y": %d, "z": %d},
                  "regeneration": {
                    "enabled": %s,
                    "delay_ticks": %d,
                    "interval_ticks": %d,
                    "max_blocks_per_cycle": %d
                  },
                  "durability": {
                    "configured_mode": "%s",
                    "effective_mode": "%s",
                    "expiration_ticks": %d,
                    "only_tnt": %s,
                    "hit_radius": %.3f
                  },
                  "acceptance": {
                    "require_payload": %s,
                    "min_target_destroyed": %d,
                    "min_falling_blocks": %d,
                    "min_forward_distance": %.6f,
                    "min_remaining_dispenser_ratio": %.6f,
                    "max_cannon_missing_blocks": %d,
                    "max_cannon_replaced_type_blocks": %d,
                    "max_self_damage_blocks": %d
                  },
                  "volleys_per_shot": %d,
                  "volley_interval_ticks": %d,
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
                targetCompanions.size(),
                arenaOrigin.getBlockX(),
                arenaOrigin.getBlockY(),
                arenaOrigin.getBlockZ(),
                scenario != null && scenario.regeneration().enabled(),
                scenario == null ? 0 : scenario.regeneration().delayTicks(),
                scenario == null ? 0 : scenario.regeneration().intervalTicks(),
                scenario == null ? 0 : scenario.regeneration().maxBlocksPerCycle(),
                json(scenario == null ? "DISABLED" : scenario.durability().mode().name()),
                json(scenario == null ? "DISABLED" : effectiveDurabilityMode().name()),
                scenario == null ? 0 : scenario.durability().expirationTicks(),
                scenario != null && scenario.durability().onlyTnt(),
                scenario == null ? 0.0 : scenario.durability().hitRadius(),
                scenario != null && scenario.acceptance().requirePayload(),
                scenario == null ? 0 : scenario.acceptance().minTargetDestroyed(),
                scenario == null ? 0 : scenario.acceptance().minFallingBlocks(),
                scenario == null ? 0.0 : scenario.acceptance().minForwardDistance(),
                scenario == null ? 0.0 : scenario.acceptance().minRemainingDispenserRatio(),
                scenario == null ? Integer.MAX_VALUE : scenario.acceptance().maxCannonMissingBlocks(),
                scenario == null ? Integer.MAX_VALUE : scenario.acceptance().maxCannonReplacedTypeBlocks(),
                scenario == null ? Integer.MAX_VALUE : scenario.acceptance().maxSelfDamageBlocks(),
                scenario == null ? 0 : scenario.volleysPerShot(),
                scenario == null ? 0 : scenario.volleyIntervalTicks(),
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

    private static String jsonArray(List<String> values) {
        return values.stream()
                .map(value -> "\"" + json(value) + "\"")
                .collect(java.util.stream.Collectors.joining(",", "[", "]"));
    }

    private static String indent(String value, int spaces) {
        String prefix = " ".repeat(spaces);
        return prefix + value.replace("\n", "\n" + prefix);
    }

    private final class RegenMonitor {
        private final World world;
        private final List<TargetCell> cells;
        private final List<CompanionCell> companions;
        private final Map<TargetCell, Long> missingSince = new HashMap<>();
        private final Map<CompanionCell, Long> companionMissingSince = new HashMap<>();
        private final Set<TargetCell> everDestroyed = new HashSet<>();
        private final Set<CompanionCell> everCompanionMissing = new HashSet<>();
        private BukkitTask task;
        private long tick;
        private int peakDestroyed;
        private int restored;
        private int companionPeakMissing;
        private int companionRestored;
        private int maxLayerBreached;
        private int cycles;

        private RegenMonitor(
                World world,
                List<TargetCell> cells,
                List<CompanionCell> companions
        ) {
            this.world = world;
            this.cells = cells;
            this.companions = companions;
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
                                cell.stageName() + ":" + cell.material().name(),
                                new Location(world, cell.x(), cell.y(), cell.z()),
                                1
                        );
                    }
                } else {
                    missingSince.remove(cell);
                }
            }
            peakDestroyed = Math.max(peakDestroyed, currentlyDestroyed);

            int currentlyMissingCompanions = 0;
            for (CompanionCell cell : companions) {
                if (!matches(world, cell)) {
                    currentlyMissingCompanions++;
                    if (companionMissingSince.putIfAbsent(cell, tick) == null) {
                        everCompanionMissing.add(cell);
                        recorder.recordCustomEvent(
                                "COMPANION_MISSING",
                                cell.stageName() + ":" + cell.role() + ":" + cell.material().name(),
                                new Location(world, cell.x(), cell.y(), cell.z()),
                                1
                        );
                    }
                } else {
                    companionMissingSince.remove(cell);
                }
            }
            companionPeakMissing = Math.max(companionPeakMissing, currentlyMissingCompanions);

            if (!allowRestore) {
                return;
            }

            boolean targetCycleDue = cells.stream()
                    .map(TargetCell::regeneration)
                    .distinct()
                    .anyMatch(config -> config.enabled() && tick % config.intervalTicks() == 0);
            boolean companionCycleDue = companions.stream()
                    .map(CompanionCell::regeneration)
                    .distinct()
                    .anyMatch(config -> config.enabled() && tick % config.intervalTicks() == 0);
            if (!targetCycleDue && !companionCycleDue) {
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

            Map<Integer, Integer> restoredByStage = new HashMap<>();
            for (Map.Entry<TargetCell, Long> entry : due) {
                TargetCell cell = entry.getKey();
                LabScenario.RegenConfig config = cell.regeneration();
                int restoredForStage = restoredByStage.getOrDefault(cell.stageIndex(), 0);
                if (restoredForStage >= config.maxBlocksPerCycle()) {
                    continue;
                }
                if (matches(world, cell)) {
                    missingSince.remove(cell);
                    continue;
                }
                restore(world, cell);
                missingSince.remove(cell);
                restored++;
                restoredByStage.put(cell.stageIndex(), restoredForStage + 1);
                recorder.recordCustomEvent(
                        "REGEN_RESTORE",
                        cell.stageName() + ":" + cell.material().name(),
                        new Location(world, cell.x(), cell.y(), cell.z()),
                        1
                );
            }

            List<Map.Entry<CompanionCell, Long>> dueCompanions = companionMissingSince.entrySet().stream()
                    .filter(entry -> {
                        LabScenario.RegenConfig config = entry.getKey().regeneration();
                        return config.enabled()
                                && tick % config.intervalTicks() == 0
                                && tick - entry.getValue() >= config.delayTicks();
                    })
                    .sorted(Comparator
                            .comparingLong((Map.Entry<CompanionCell, Long> entry) -> entry.getValue())
                            .thenComparingInt(entry -> entry.getKey().layer()))
                    .toList();
            for (Map.Entry<CompanionCell, Long> entry : dueCompanions) {
                CompanionCell cell = entry.getKey();
                LabScenario.RegenConfig config = cell.regeneration();
                int restoredForStage = restoredByStage.getOrDefault(cell.stageIndex(), 0);
                if (restoredForStage >= config.maxBlocksPerCycle()) {
                    continue;
                }
                if (matches(world, cell)) {
                    companionMissingSince.remove(cell);
                    continue;
                }
                restore(world, cell);
                companionMissingSince.remove(cell);
                companionRestored++;
                restoredByStage.put(cell.stageIndex(), restoredForStage + 1);
                recorder.recordCustomEvent(
                        "COMPANION_RESTORE",
                        cell.stageName() + ":" + cell.role() + ":" + cell.material().name(),
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
            int finalCompanionMissing = 0;
            for (CompanionCell cell : companions) {
                if (!matches(world, cell)) {
                    finalCompanionMissing++;
                }
            }
            cancel();
            return new RegenStats(
                    finalDestroyed,
                    peakDestroyed,
                    everDestroyed.size(),
                    restored,
                    maxLayerBreached,
                    cycles,
                    finalCompanionMissing,
                    companionPeakMissing,
                    everCompanionMissing.size(),
                    companionRestored
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

    private record BlockKey(int x, int y, int z) {
    }

    private record DurabilityState(int remaining, long lastHitTick) {
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
            int layer,
            int stageIndex,
            String stageName,
            LabScenario.RegenConfig regeneration
    ) {
    }

    private record CompanionCell(
            int x,
            int y,
            int z,
            Material material,
            String blockData,
            int layer,
            int stageIndex,
            String stageName,
            String role,
            LabScenario.RegenConfig regeneration
    ) {
    }

    private record TargetBuild(
            List<TargetCell> cells,
            List<CompanionCell> companions,
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
            int cycles,
            int finalCompanionMissing,
            int companionPeakMissing,
            int everCompanionMissing,
            int companionRestored
    ) {
        private static RegenStats empty() {
            return new RegenStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
        }
    }

    private record BlockDifference(
            String kind,
            int x,
            int y,
            int z,
            String expected,
            String actual
    ) {
    }

    private record CannonIntegrity(
            int initial,
            int sameState,
            int stateChanged,
            int missing,
            int replacedType,
            int dispensersInitial,
            int dispensersRemaining,
            List<BlockDifference> differences
    ) {
        private CannonIntegrity {
            differences = List.copyOf(differences);
        }

        private static CannonIntegrity empty() {
            return new CannonIntegrity(0, 0, 0, 0, 0, 0, 0, List.of());
        }
    }

    private record CompletedShot(
            int number,
            String finishReason,
            boolean sawPayload,
            int explosions,
            int destroyedBlocks,
            int selfDamageBlocks,
            int targetDestroyed,
            int targetPeakDestroyed,
            int targetEverDestroyed,
            int targetTotal,
            int regenRestored,
            int maxLayerBreached,
            int regenCycles,
            int companionMissing,
            int companionPeakMissing,
            int companionEverMissing,
            int companionRestored,
            int durabilityHits,
            int durabilityBreaks,
            int maximumTnt,
            int maximumFallingBlocks,
            double maximumForwardDistance,
            double minimumForwardDistance,
            CannonIntegrity integrity,
            List<String> contractFailures,
            String error
    ) {
        private CompletedShot {
            contractFailures = List.copyOf(contractFailures);
        }

        private boolean contractPass() {
            return contractFailures.isEmpty();
        }

        private static CompletedShot preparationError(
                int number,
                int targetTotal,
                Exception exception
        ) {
            return new CompletedShot(
                    number,
                    "preparation_error",
                    false,
                    0, // explosions
                    0, // destroyed blocks
                    0, // self damage
                    0, // target destroyed
                    0, // target peak destroyed
                    0, // target ever destroyed
                    targetTotal,
                    0, // regen restored
                    0, // max layer breached
                    0, // regen cycles
                    0, // companion missing
                    0, // companion peak missing
                    0, // companion ever missing
                    0, // companion restored
                    0, // durability hits
                    0, // durability breaks
                    0, // maximum TNT
                    0, // maximum falling blocks
                    0.0, // maximum forward distance
                    0.0, // minimum forward distance
                    CannonIntegrity.empty(),
                    List.of("preparation_error"),
                    exception.getClass().getSimpleName() + ": " + exception.getMessage()
            );
        }
    }
}
