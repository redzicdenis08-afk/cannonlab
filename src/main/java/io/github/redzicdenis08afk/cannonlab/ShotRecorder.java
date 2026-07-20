package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockExplodeEvent;
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
    private final CannonLabPlugin plugin;

    private BukkitTask task;
    private BufferedWriter writer;
    private World world;
    private Location origin;
    private Path shotDirectory;
    private Consumer<ShotResult> completion;
    private long tick;
    private int maxTicks;
    private int quietTicksRequired;
    private int quietTicks;
    private int explosions;
    private int destroyedBlocks;
    private int maximumTnt;
    private int maximumFallingBlocks;
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

        world = recordingWorld;
        origin = recordingOrigin.clone();
        maxTicks = shotMaxTicks;
        quietTicksRequired = requiredQuietTicks;
        completion = onComplete;
        tick = 0;
        quietTicks = 0;
        explosions = 0;
        destroyedBlocks = 0;
        maximumTnt = 0;
        maximumFallingBlocks = 0;
        sawPayload = false;
        finishing = false;

        task = Bukkit.getScheduler().runTaskTimer(plugin, this::captureSafely, 0L, 1L);
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
        tick++;

        if (tick >= maxTicks) {
            finish("max_ticks");
        } else if (sawPayload && quietTicks >= quietTicksRequired) {
            finish("quiet");
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onEntityExplode(EntityExplodeEvent event) {
        if (!activeIn(event.getLocation().getWorld())) {
            return;
        }
        explosions++;
        destroyedBlocks += event.blockList().size();
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
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record explosion: " + exception.getMessage());
        }
    }

    @EventHandler(ignoreCancelled = true)
    public void onBlockExplode(BlockExplodeEvent event) {
        if (!activeIn(event.getBlock().getWorld())) {
            return;
        }
        explosions++;
        destroyedBlocks += event.blockList().size();
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
        } catch (IOException exception) {
            plugin.getLogger().warning("Unable to record block explosion: " + exception.getMessage());
        }
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
                maximumTnt,
                maximumFallingBlocks,
                shotDirectory,
                Instant.now().toString()
        );

        try {
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
        if (task != null) {
            finish("cancelled");
        }
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
                  "maximum_tnt_entities": %d,
                  "maximum_falling_blocks": %d
                }
                """.formatted(
                result.finishedAt(),
                result.finishReason(),
                result.ticks(),
                result.sawPayload(),
                result.explosions(),
                result.destroyedBlocks(),
                result.maximumTnt(),
                result.maximumFallingBlocks()
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
        world = null;
        origin = null;
        completion = null;
        finishing = false;
    }

    record ShotResult(
            String finishReason,
            long ticks,
            boolean sawPayload,
            int explosions,
            int destroyedBlocks,
            int maximumTnt,
            int maximumFallingBlocks,
            Path directory,
            String finishedAt
    ) {
    }
}
