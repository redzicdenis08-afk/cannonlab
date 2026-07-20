package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.Dispenser;
import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.Powerable;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.FallingBlock;
import org.bukkit.entity.TNTPrimed;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class CannonLabPlugin extends JavaPlugin {
    private BukkitTask telemetryTask;
    private BufferedWriter telemetryWriter;
    private long shotTick;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        getLogger().info("CannonLab stage 1 enabled.");
    }

    @Override
    public void onDisable() {
        stopRecording();
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0) {
            sender.sendMessage("CannonLab: status, smoke, fill, fire, record <start|stop>, wall <dry|watered>");
            return true;
        }

        try {
            return switch (args[0].toLowerCase(Locale.ROOT)) {
                case "status" -> status(sender);
                case "smoke" -> smoke(sender);
                case "fill" -> fill(sender);
                case "fire" -> fire(sender);
                case "record" -> record(sender, args);
                case "wall" -> wall(sender, args);
                default -> false;
            };
        } catch (RuntimeException exception) {
            getLogger().severe("Command failed: " + exception.getMessage());
            sender.sendMessage("CannonLab command failed. Check console.");
            return true;
        }
    }

    private boolean status(CommandSender sender) {
        World world = arenaWorld();
        sender.sendMessage("CannonLab enabled | world=" + world.getName()
                + " | recording=" + (telemetryTask != null));
        return true;
    }

    private boolean smoke(CommandSender sender) {
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        world.getChunkAt(origin).load(true);
        sender.sendMessage("Smoke PASS | world and origin loaded at "
                + origin.getBlockX() + "," + origin.getBlockY() + "," + origin.getBlockZ());
        return true;
    }

    private boolean fill(CommandSender sender) {
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        int radius = getConfig().getInt("cannon.fill-radius", 128);
        int filled = 0;

        for (int x = origin.getBlockX() - radius; x <= origin.getBlockX() + radius; x++) {
            for (int y = Math.max(world.getMinHeight(), origin.getBlockY() - radius);
                 y <= Math.min(world.getMaxHeight() - 1, origin.getBlockY() + radius); y++) {
                for (int z = origin.getBlockZ() - radius; z <= origin.getBlockZ() + radius; z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (block.getState() instanceof Dispenser dispenser) {
                        dispenser.getInventory().clear();
                        for (int slot = 0; slot < dispenser.getInventory().getSize(); slot++) {
                            dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, 64));
                        }
                        filled++;
                    }
                }
            }
        }

        sender.sendMessage("Filled " + filled + " dispensers.");
        return true;
    }

    private boolean fire(CommandSender sender) {
        World world = arenaWorld();
        Block block = world.getBlockAt(
                getConfig().getInt("cannon.fire-input.x"),
                getConfig().getInt("cannon.fire-input.y"),
                getConfig().getInt("cannon.fire-input.z")
        );

        BlockData data = block.getBlockData();
        if (!(data instanceof Powerable powerable)) {
            sender.sendMessage("Configured fire-input is not a powerable block: " + block.getType());
            return true;
        }

        powerable.setPowered(true);
        block.setBlockData(powerable, true);
        Bukkit.getScheduler().runTaskLater(this, () -> {
            BlockData current = block.getBlockData();
            if (current instanceof Powerable resettable) {
                resettable.setPowered(false);
                block.setBlockData(resettable, true);
            }
        }, 2L);

        sender.sendMessage("Fire input pulsed.");
        return true;
    }

    private boolean wall(CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /cannonlab wall <dry|watered>");
            return true;
        }

        boolean watered = args[1].equalsIgnoreCase("watered");
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        int wallX = origin.getBlockX() + 160;
        int baseY = origin.getBlockY();
        int centerZ = origin.getBlockZ();

        for (int y = baseY; y < baseY + 32; y++) {
            for (int z = centerZ - 8; z <= centerZ + 8; z++) {
                world.getBlockAt(wallX, y, z).setType(Material.OBSIDIAN, false);
                if (watered) {
                    world.getBlockAt(wallX - 1, y, z).setType(Material.WATER, false);
                }
            }
        }

        sender.sendMessage("Built " + (watered ? "watered" : "dry") + " obsidian test wall.");
        return true;
    }

    private boolean record(CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /cannonlab record <start|stop>");
            return true;
        }
        if (args[1].equalsIgnoreCase("start")) {
            startRecording();
            sender.sendMessage("Telemetry recording started.");
        } else if (args[1].equalsIgnoreCase("stop")) {
            stopRecording();
            sender.sendMessage("Telemetry recording stopped.");
        }
        return true;
    }

    private void startRecording() {
        stopRecording();
        try {
            Path outputDirectory = getDataFolder().toPath()
                    .resolve(getConfig().getString("telemetry.output-directory", "results"));
            Files.createDirectories(outputDirectory);
            Path output = outputDirectory.resolve("shot-" + Instant.now().toEpochMilli() + ".csv");
            telemetryWriter = Files.newBufferedWriter(output);
            telemetryWriter.write("tick,type,uuid,x,y,z,vx,vy,vz,fuse\n");
            shotTick = 0;
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to open telemetry file", exception);
        }

        int maxTicks = getConfig().getInt("telemetry.max-shot-ticks", 200);
        telemetryTask = Bukkit.getScheduler().runTaskTimer(this, () -> {
            try {
                captureTick();
                shotTick++;
                if (shotTick >= maxTicks) {
                    stopRecording();
                }
            } catch (IOException exception) {
                getLogger().severe("Telemetry write failed: " + exception.getMessage());
                stopRecording();
            }
        }, 0L, 1L);
    }

    private void captureTick() throws IOException {
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        int rx = getConfig().getInt("arena.radius-x", 96);
        int ry = getConfig().getInt("arena.radius-y", 64);
        int rz = getConfig().getInt("arena.radius-z", 256);

        List<Entity> entities = new ArrayList<>(world.getNearbyEntities(origin, rx, ry, rz));
        for (Entity entity : entities) {
            if (!(entity instanceof TNTPrimed) && !(entity instanceof FallingBlock)) {
                continue;
            }
            int fuse = entity instanceof TNTPrimed tnt ? tnt.getFuseTicks() : -1;
            telemetryWriter.write(String.format(Locale.ROOT,
                    "%d,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d%n",
                    shotTick,
                    entity.getType().name(),
                    entity.getUniqueId(),
                    entity.getX(), entity.getY(), entity.getZ(),
                    entity.getVelocity().getX(),
                    entity.getVelocity().getY(),
                    entity.getVelocity().getZ(),
                    fuse));
        }
        telemetryWriter.flush();
    }

    private void stopRecording() {
        if (telemetryTask != null) {
            telemetryTask.cancel();
            telemetryTask = null;
        }
        if (telemetryWriter != null) {
            try {
                telemetryWriter.close();
            } catch (IOException ignored) {
                // Best effort on shutdown.
            }
            telemetryWriter = null;
        }
    }

    private World arenaWorld() {
        String worldName = getConfig().getString("arena.world", "world");
        World world = Bukkit.getWorld(worldName);
        if (world == null) {
            throw new IllegalStateException("Arena world is not loaded: " + worldName);
        }
        return world;
    }

    private Location arenaOrigin(World world) {
        return new Location(world,
                getConfig().getInt("arena.origin.x"),
                getConfig().getInt("arena.origin.y"),
                getConfig().getInt("arena.origin.z"));
    }
}
