package io.github.redzicdenis08afk.cannonlab;

import com.destroystokyo.paper.event.entity.EntityAddToWorldEvent;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockDispenseEvent;
import org.bukkit.event.block.BlockExplodeEvent;
import org.bukkit.event.block.BlockFromToEvent;
import org.bukkit.event.block.BlockPistonExtendEvent;
import org.bukkit.event.block.BlockPistonRetractEvent;
import org.bukkit.event.block.BlockRedstoneEvent;
import org.bukkit.event.block.FluidLevelChangeEvent;
import org.bukkit.event.block.TNTPrimeEvent;
import org.bukkit.event.entity.EntityExplodeEvent;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.Vector;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.function.Consumer;

final class ShotRecorder implements Listener {
    private static final int MAX_MOVED_COMPONENTS_IN_DETAIL = 128;

    private final CannonLabPlugin plugin;

    private BukkitTask task;
    private BufferedWriter writer;
    private BufferedWriter causalWriter;
    private World world;
    private Location origin;
    private Location cannonOrigin;
    private BlockBounds cannonBounds;
    private Path shotDirectory;
    private Consumer<ShotResult> completion;
    private long tick;
    private long causalSequence;
    private int maxTicks;
    private int quietTicksRequired;
    private int quietTicks;
    private int explosions;
    private int destroyedBlocks;
    private int selfDamageBlocks;
    private int maximumTnt;
    private int maximumFallingBlocks;
    private int causalEvents;
    private int redstoneEvents;
    private int dispenseEvents;
    private int pistonEvents;
    private int entityAddEvents;
    private int tntPrimeEvents;
    private int fluidEvents;
    private int controlEvents;
    private boolean sawPayload;
    private boolean finishing;

    ShotRecorder(CannonLabPlugin plugin) {
        this.plugin = plugin;
    }

    boolean isRecording() {
        return task != null;
    }

    Path start(
            String runId,
            String scenarioName,
            int shotNumber,
            World recordingWorld,
            Location recordingOrigin,
            Location recordingCannonOrigin,
            BlockBounds recordingCannonBounds,
            int shotMaxTicks,
            int requiredQuietTicks,
            Consumer<ShotResult> onComplete
    ) throws IOException {
        stopWithoutCallback();

        Path resultsRoot = plugin.getDataFolder().toPath()
                .resolve(plugin.getConfig().getString("telemetry.output-directory", "results"));
        shotDirectory = resultsRoot.resolve(runId).resolve("shot-%03d".formatted(shotNumber));
        Files.createDirectories(shotDirectory);

        writer = Files.newBufferedWriter(
                shotDirectory.resolve("events.csv"),
                StandardCharsets.UTF_8
        );
        writer.write("tick,event,type,uuid,x,y,z,vx,vy,vz,fuse,affected_blocks\n");

        if (causalEnabled()) {
            causalWriter = Files.newBufferedWriter(
                    shotDirectory.resolve("causal-events.csv"),
                    StandardCharsets.UTF_8
            );
            causalWriter.write(
                    "tick,server_tick,sequence,event,component_id,block_type,"
                            + "world_x,world_y,world_z,relative_x,relative_y,relative_z,"
                            + "old_power,new_power,direction,moved_blocks,item,"
                            + "entity_uuid,entity_type,vx,vy,vz,fuse,details\n"
            );
        }

        world = recordingWorld;
        origin = recordingOrigin.clone();
        cannonOrigin = recordingCannonOrigin.clone();
        cannonBounds = recordingCannonBounds;
        maxTicks = shotMaxTicks;
        quietTicksRequired = requiredQuietTicks;
        completion = onComplete;
        tick = 0;
        causalSequence = 0;
        quietTicks = 0;
        explosions = 0;
        destroyedBlocks = 0;
        selfDamageBlocks = 0;
        maximumTnt = 0;
        maximumFallingBlocks = 0;
        causalEvents = 0;
        redstoneEvents = 0;
        dispenseEvents = 0;
        pistonEvents = 0;
        entityAddEvents = 0;
        tntPrimeEvents = 0;
        fluidEvents = 0;
        controlEvents = 0;
        sawPayload = false;
        finishing = false;

        task = Bukkit.getScheduler().runTaskTimer(plugin, this::captureSafely, 0L, 1L);
        recordControlEvent(
                "RECORDING_START",
                recordingOrigin,
                "scenario=" + scenarioName + ";shot=" + shotNumber
        );
        return shotDirectory;
    }

    private void captureSafely() {
        try {
            captureTick();
        } catch (IOException exception) {
            plugin.getLogger().severe("Telemetry failed: " + exception.getMessage());
            finish("telemetry_error");
        }
    }

    private void captureTick() throws IOException {
        int radiusX = plugin.getConfig().getInt("arena.radius-x", 256);
        int radiusY = plugin.getConfig().getInt("arena.radius-y", 128);
        int radiusZ = plugin.getConfig().getInt("arena.radius-z", 96);

        List<Entity> entities = new ArrayList<>(world.getNearbyEntities(origin, radiusX, radiusY, radiusZ));
        int tntCount = 0;
        int fallingCount = 0;

        for (Entity entity : entities) {
            if (!(entity instanceof TNTPrimed) && !(entity instanceof FallingBlock)) {
                continue;
            }

            sawPayload = true;
            int fuse = -1;
            if (entity instanceof TNTPrimed tnt) {
                tntCount++;
                fuse = tnt.getFuseTicks();
            } else {
                fallingCount++;
            }

            Vector velocity = entity.getVelocity();
            writeEvent(
                    "ENTITY",
                    entity.getType().name(),
                    entity.getUniqueId(),
                    entity.getLocation(),
                    velocity,
                    fuse,
                    0
            );
        }

        maximumTnt = Math.max(maximumTnt, tntCount);
        maximumFallingBlocks = Math.max(maximumFallingBlocks, fallingCount);

        if (tntCount + fallingCount == 0) {
            if (sawPayload) {
                quietTicks++;
            }
        } else {
            quietTicks = 0;
        }

        writer.flush();
        if (causalWriter != null) {
            causalWriter.flush();
        }
        tick++;

        if (tick >= maxTicks) {
            finish("max_ticks");
        } else if (sawPayload && quietTicks >= quietTicksRequired) {
            finish("quiet");
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onRedstone(BlockRedstoneEvent event) {
        if (!causalFlag("capture-redstone", true) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        redstoneEvents++;
        writeCausalSafely(
                "REDSTONE_CHANGE",
                event.getBlock(),
                event.getOldCurrent(),
                event.getNewCurrent(),
                "",
                0,
                "",
                null,
                null,
                new Vector(),
                -1,
                "block_data=" + event.getBlock().getBlockData().getAsString()
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDispense(BlockDispenseEvent event) {
        if (!causalFlag("capture-dispense", true) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        dispenseEvents++;
        writeCausalSafely(
                "DISPENSE",
                event.getBlock(),
                -1,
                -1,
                "",
                0,
                event.getItem().getType().name(),
                null,
                null,
                event.getVelocity(),
                -1,
                "amount=" + event.getItem().getAmount()
                        + ";block_data=" + event.getBlock().getBlockData().getAsString()
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPistonExtend(BlockPistonExtendEvent event) {
        if (!causalFlag("capture-pistons", true) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        pistonEvents++;
        writeCausalSafely(
                "PISTON_EXTEND",
                event.getBlock(),
                -1,
                -1,
                event.getDirection().name(),
                event.getBlocks().size(),
                "",
                null,
                null,
                directionVector(event.getDirection()),
                -1,
                "sticky=" + event.isSticky()
                        + ";moved=" + summarizeMovedBlocks(event.getBlocks())
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPistonRetract(BlockPistonRetractEvent event) {
        if (!causalFlag("capture-pistons", true) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        pistonEvents++;
        writeCausalSafely(
                "PISTON_RETRACT",
                event.getBlock(),
                -1,
                -1,
                event.getDirection().name(),
                event.getBlocks().size(),
                "",
                null,
                null,
                directionVector(event.getDirection()),
                -1,
                "sticky=" + event.isSticky()
                        + ";moved=" + summarizeMovedBlocks(event.getBlocks())
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onTntPrime(TNTPrimeEvent event) {
        if (!causalFlag("capture-tnt-prime", true) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        tntPrimeEvents++;
        String primingBlock = event.getPrimingBlock() == null
                ? ""
                : componentId(event.getPrimingBlock());
        String primingEntity = event.getPrimingEntity() == null
                ? ""
                : event.getPrimingEntity().getUniqueId().toString();
        writeCausalSafely(
                "TNT_PRIME",
                event.getBlock(),
                -1,
                -1,
                "",
                0,
                "",
                event.getPrimingEntity() == null ? null : event.getPrimingEntity().getUniqueId(),
                event.getPrimingEntity() == null ? null : event.getPrimingEntity().getType().name(),
                new Vector(),
                -1,
                "cause=" + event.getCause().name()
                        + ";priming_block=" + primingBlock
                        + ";priming_entity=" + primingEntity
        );
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onEntityAdd(EntityAddToWorldEvent event) {
        Entity entity = event.getEntity();
        if (!(entity instanceof TNTPrimed) && !(entity instanceof FallingBlock)) {
            return;
        }
        if (!causalFlag("capture-entity-add", true) || !activeAt(entity.getLocation())) {
            return;
        }

        entityAddEvents++;
        int fuse = entity instanceof TNTPrimed tnt ? tnt.getFuseTicks() : -1;
        String details = entity instanceof FallingBlock fallingBlock
                ? "block_data=" + fallingBlock.getBlockData().getAsString()
                : "source=entity-add";
        writeCausalSafely(
                "ENTITY_ADD",
                null,
                -1,
                -1,
                "",
                0,
                "",
                entity.getUniqueId(),
                entity.getType().name(),
                entity.getVelocity(),
                fuse,
                details,
                entity.getLocation()
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onFluidFlow(BlockFromToEvent event) {
        if (!causalFlag("capture-fluid", false) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        fluidEvents++;
        Block from = event.getBlock();
        Block to = event.getToBlock();
        Vector direction = new Vector(
                to.getX() - from.getX(),
                to.getY() - from.getY(),
                to.getZ() - from.getZ()
        );
        writeCausalSafely(
                "FLUID_FLOW",
                from,
                -1,
                -1,
                directionName(direction),
                0,
                to.getType().name(),
                null,
                null,
                direction,
                -1,
                "to=" + componentId(to)
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onFluidLevelChange(FluidLevelChangeEvent event) {
        if (!causalFlag("capture-fluid", false) || !activeAt(event.getBlock().getLocation())) {
            return;
        }
        fluidEvents++;
        writeCausalSafely(
                "FLUID_LEVEL_CHANGE",
                event.getBlock(),
                -1,
                -1,
                "",
                0,
                "",
                null,
                null,
                new Vector(),
                -1,
                "old=" + event.getBlock().getBlockData().getAsString()
                        + ";new=" + event.getNewData().getAsString()
        );
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onEntityExplode(EntityExplodeEvent event) {
        if (!activeIn(event.getLocation().getWorld())) {
            return;
        }
        explosions++;
        destroyedBlocks += event.blockList().size();
        int selfDamage = countSelfDamage(event.blockList());
        selfDamageBlocks += selfDamage;
        try {
            writeEvent(
                    "EXPLOSION",
                    event.getEntityType().name(),
                    event.getEntity().getUniqueId(),
                    event.getLocation(),
                    new Vector(),
                    -1,
                    event.blockList().size()
            );
            if (causalEnabled()) {
                writeCausal(
                        "EXPLOSION",
                        null,
                        event.getLocation(),
                        -1,
                        -1,
                        "",
                        0,
                        "",
                        event.getEntity().getUniqueId(),
                        event.getEntityType().name(),
                        new Vector(),
                        -1,
                        "affected_blocks=" + event.blockList().size()
                                + ";self_damage_blocks=" + selfDamage
                );
            }
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record explosion: " + exception.getMessage());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onBlockExplode(BlockExplodeEvent event) {
        if (!activeIn(event.getBlock().getWorld())) {
            return;
        }
        explosions++;
        destroyedBlocks += event.blockList().size();
        int selfDamage = countSelfDamage(event.blockList());
        selfDamageBlocks += selfDamage;
        try {
            writeEvent(
                    "BLOCK_EXPLOSION",
                    event.getBlock().getType().name(),
                    null,
                    event.getBlock().getLocation(),
                    new Vector(),
                    -1,
                    event.blockList().size()
            );
            if (causalEnabled()) {
                writeCausal(
                        "BLOCK_EXPLOSION",
                        event.getBlock(),
                        event.getBlock().getLocation(),
                        -1,
                        -1,
                        "",
                        0,
                        "",
                        null,
                        null,
                        new Vector(),
                        -1,
                        "affected_blocks=" + event.blockList().size()
                                + ";self_damage_blocks=" + selfDamage
                );
            }
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record block explosion: " + exception.getMessage());
        }
    }

    void recordCustomEvent(
            String event,
            String type,
            Location location,
            int affectedBlocks
    ) {
        World eventWorld = location.getWorld();
        if (eventWorld == null || !activeIn(eventWorld)) {
            return;
        }
        try {
            writeEvent(
                    event,
                    type,
                    null,
                    location,
                    new Vector(),
                    -1,
                    affectedBlocks
            );
            if (causalEnabled()) {
                writeCausal(
                        event,
                        location.getBlock(),
                        location,
                        -1,
                        -1,
                        "",
                        0,
                        "",
                        null,
                        null,
                        new Vector(),
                        -1,
                        "affected_blocks=" + affectedBlocks + ";type=" + type
                );
            }
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record custom event "
                    + event + ": " + exception.getMessage());
        }
    }

    void recordControlEvent(String event, Location location, String details) {
        if (!causalEnabled() || location == null || !activeAt(location)) {
            return;
        }
        controlEvents++;
        writeCausalSafely(
                event,
                location.getBlock(),
                -1,
                -1,
                "",
                0,
                "",
                null,
                null,
                new Vector(),
                -1,
                details
        );
    }

    private void writeCausalSafely(
            String event,
            Block block,
            int oldPower,
            int newPower,
            String direction,
            int movedBlocks,
            String item,
            UUID entityUuid,
            String entityType,
            Vector velocity,
            int fuse,
            String details
    ) {
        Location location = block == null ? origin : block.getLocation();
        writeCausalSafely(
                event,
                block,
                oldPower,
                newPower,
                direction,
                movedBlocks,
                item,
                entityUuid,
                entityType,
                velocity,
                fuse,
                details,
                location
        );
    }

    private void writeCausalSafely(
            String event,
            Block block,
            int oldPower,
            int newPower,
            String direction,
            int movedBlocks,
            String item,
            UUID entityUuid,
            String entityType,
            Vector velocity,
            int fuse,
            String details,
            Location location
    ) {
        try {
            writeCausal(
                    event,
                    block,
                    location,
                    oldPower,
                    newPower,
                    direction,
                    movedBlocks,
                    item,
                    entityUuid,
                    entityType,
                    velocity,
                    fuse,
                    details
            );
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record causal event "
                    + event + ": " + exception.getMessage());
        }
    }

    private boolean activeAt(Location location) {
        if (location == null || !activeIn(location.getWorld())) {
            return false;
        }
        int radiusX = plugin.getConfig().getInt("arena.radius-x", 256);
        int radiusY = plugin.getConfig().getInt("arena.radius-y", 128);
        int radiusZ = plugin.getConfig().getInt("arena.radius-z", 96);
        return Math.abs(location.getX() - origin.getX()) <= radiusX
                && Math.abs(location.getY() - origin.getY()) <= radiusY
                && Math.abs(location.getZ() - origin.getZ()) <= radiusZ;
    }

    private boolean activeIn(World eventWorld) {
        return task != null && world != null && world.equals(eventWorld);
    }

    private void writeEvent(
            String event,
            String type,
            UUID uuid,
            Location location,
            Vector velocity,
            int fuse,
            int affectedBlocks
    ) throws IOException {
        if (writer == null) {
            return;
        }
        writer.write(String.format(Locale.ROOT,
                "%d,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%d%n",
                tick,
                event,
                type,
                uuid == null ? "" : uuid,
                location.getX(), location.getY(), location.getZ(),
                velocity.getX(), velocity.getY(), velocity.getZ(),
                fuse,
                affectedBlocks));
    }

    private void writeCausal(
            String event,
            Block block,
            Location location,
            int oldPower,
            int newPower,
            String direction,
            int movedBlocks,
            String item,
            UUID entityUuid,
            String entityType,
            Vector velocity,
            int fuse,
            String details
    ) throws IOException {
        if (causalWriter == null || location == null) {
            return;
        }
        causalEvents++;
        causalSequence++;
        String componentId = block == null ? "" : componentId(block);
        String blockType = block == null ? "" : block.getType().name();
        double relativeX = location.getX() - cannonOrigin.getX();
        double relativeY = location.getY() - cannonOrigin.getY();
        double relativeZ = location.getZ() - cannonOrigin.getZ();
        Vector safeVelocity = velocity == null ? new Vector() : velocity;
        causalWriter.write(String.format(Locale.ROOT,
                "%d,%d,%d,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%d,%s,%d,%s,%s,%s,%.6f,%.6f,%.6f,%d,%s%n",
                tick,
                Bukkit.getCurrentTick(),
                causalSequence,
                csv(event),
                csv(componentId),
                csv(blockType),
                location.getX(), location.getY(), location.getZ(),
                relativeX, relativeY, relativeZ,
                oldPower,
                newPower,
                csv(direction),
                movedBlocks,
                csv(item),
                entityUuid == null ? "" : entityUuid,
                csv(entityType),
                safeVelocity.getX(), safeVelocity.getY(), safeVelocity.getZ(),
                fuse,
                csv(details)
        ));
    }

    private String componentId(Block block) {
        int x = block.getX() - cannonOrigin.getBlockX();
        int y = block.getY() - cannonOrigin.getBlockY();
        int z = block.getZ() - cannonOrigin.getBlockZ();
        return prefix(block.getType()) + "[" + x + "," + y + "," + z + "]";
    }

    private String prefix(Material material) {
        return switch (material) {
            case DISPENSER -> "D";
            case DROPPER -> "DR";
            case REPEATER -> "R";
            case COMPARATOR -> "C";
            case OBSERVER -> "O";
            case PISTON, STICKY_PISTON, MOVING_PISTON, PISTON_HEAD -> "P";
            case REDSTONE_WIRE -> "W";
            case REDSTONE_TORCH, REDSTONE_WALL_TORCH -> "T";
            case LEVER, STONE_BUTTON, POLISHED_BLACKSTONE_BUTTON,
                 OAK_BUTTON, SPRUCE_BUTTON, BIRCH_BUTTON, JUNGLE_BUTTON,
                 ACACIA_BUTTON, DARK_OAK_BUTTON, MANGROVE_BUTTON,
                 CHERRY_BUTTON, BAMBOO_BUTTON, CRIMSON_BUTTON, WARPED_BUTTON -> "I";
            default -> "B";
        };
    }

    private Vector directionVector(org.bukkit.block.BlockFace face) {
        return new Vector(face.getModX(), face.getModY(), face.getModZ());
    }

    private String directionName(Vector direction) {
        return ((int) direction.getX()) + "," + ((int) direction.getY()) + "," + ((int) direction.getZ());
    }

    private String summarizeMovedBlocks(List<Block> blocks) {
        StringBuilder result = new StringBuilder();
        int limit = Math.min(blocks.size(), MAX_MOVED_COMPONENTS_IN_DETAIL);
        for (int index = 0; index < limit; index++) {
            if (index > 0) {
                result.append('|');
            }
            Block moved = blocks.get(index);
            result.append(componentId(moved))
                    .append(':')
                    .append(moved.getType().name());
        }
        if (blocks.size() > limit) {
            result.append("|...").append(blocks.size() - limit).append(" more");
        }
        return result.toString();
    }

    private String csv(String value) {
        if (value == null) {
            return "";
        }
        String normalized = value.replace("\r", "\\r").replace("\n", "\\n");
        if (normalized.contains(",") || normalized.contains("\"") || normalized.contains(";")) {
            return "\"" + normalized.replace("\"", "\"\"") + "\"";
        }
        return normalized;
    }

    private int countSelfDamage(List<Block> blocks) {
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

    private boolean causalEnabled() {
        return plugin.getConfig().getBoolean("telemetry.causal.enabled", true);
    }

    private boolean causalFlag(String key, boolean defaultValue) {
        return causalEnabled()
                && plugin.getConfig().getBoolean("telemetry.causal." + key, defaultValue);
    }

    private void finish(String reason) {
        if (finishing) {
            return;
        }
        finishing = true;

        Consumer<ShotResult> callback = completion;
        ShotResult result = new ShotResult(
                reason,
                tick,
                sawPayload,
                explosions,
                destroyedBlocks,
                selfDamageBlocks,
                maximumTnt,
                maximumFallingBlocks,
                causalEvents,
                redstoneEvents,
                dispenseEvents,
                pistonEvents,
                entityAddEvents,
                tntPrimeEvents,
                fluidEvents,
                controlEvents,
                shotDirectory,
                Instant.now().toString()
        );

        try {
            recordControlEvent("RECORDING_STOP", origin, "reason=" + reason);
            writeSummary(result);
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to write shot summary: " + exception.getMessage());
        }

        stopWithoutCallback();
        if (callback != null) {
            callback.accept(result);
        }
    }

    void cancel() {
        stopWithoutCallback();
    }

    private void writeSummary(ShotResult result) throws IOException {
        if (shotDirectory == null) {
            return;
        }
        String json = """
                {
                  "finished_at": "%s",
                  "finish_reason": "%s",
                  "ticks": %d,
                  "saw_payload": %s,
                  "explosions": %d,
                  "destroyed_blocks": %d,
                  "self_damage_blocks": %d,
                  "maximum_tnt_entities": %d,
                  "maximum_falling_blocks": %d,
                  "causal_events": %d,
                  "redstone_events": %d,
                  "dispense_events": %d,
                  "piston_events": %d,
                  "entity_add_events": %d,
                  "tnt_prime_events": %d,
                  "fluid_events": %d,
                  "control_events": %d
                }
                """.formatted(
                result.finishedAt(),
                result.finishReason(),
                result.ticks(),
                result.sawPayload(),
                result.explosions(),
                result.destroyedBlocks(),
                result.selfDamageBlocks(),
                result.maximumTnt(),
                result.maximumFallingBlocks(),
                result.causalEvents(),
                result.redstoneEvents(),
                result.dispenseEvents(),
                result.pistonEvents(),
                result.entityAddEvents(),
                result.tntPrimeEvents(),
                result.fluidEvents(),
                result.controlEvents()
        );
        Files.writeString(shotDirectory.resolve("summary.json"), json, StandardCharsets.UTF_8);
    }

    private void stopWithoutCallback() {
        if (task != null) {
            task.cancel();
            task = null;
        }
        if (writer != null) {
            try {
                writer.close();
            } catch (IOException ignored) {
                // Best effort during shutdown.
            }
            writer = null;
        }
        if (causalWriter != null) {
            try {
                causalWriter.close();
            } catch (IOException ignored) {
                // Best effort during shutdown.
            }
            causalWriter = null;
        }
        world = null;
        origin = null;
        cannonOrigin = null;
        cannonBounds = null;
        completion = null;
        finishing = false;
    }

    record BlockBounds(
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

    record ShotResult(
            String finishReason,
            long ticks,
            boolean sawPayload,
            int explosions,
            int destroyedBlocks,
            int selfDamageBlocks,
            int maximumTnt,
            int maximumFallingBlocks,
            int causalEvents,
            int redstoneEvents,
            int dispenseEvents,
            int pistonEvents,
            int entityAddEvents,
            int tntPrimeEvents,
            int fluidEvents,
            int controlEvents,
            Path directory,
            String finishedAt
    ) {
    }
}
