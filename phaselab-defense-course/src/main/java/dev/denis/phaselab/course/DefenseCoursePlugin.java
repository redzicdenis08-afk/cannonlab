package dev.denis.phaselab.course;

import org.bukkit.Bukkit;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.entity.Vehicle;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityCombustEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.vehicle.VehicleDamageEvent;
import org.bukkit.event.vehicle.VehicleDestroyEvent;
import org.bukkit.event.vehicle.VehicleExitEvent;
import org.bukkit.event.vehicle.VehicleMoveEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * Dynamic fifteen-chunk mixed defense fixture for authorized Sakura testing.
 *
 * The plugin builds a 240-block solid course containing obsidian, water, lava,
 * cobblestone, basalt and crying obsidian. Selected planes are regenerated with
 * normal physics updates while a trial runs. All important coordinates are read
 * directly from the server and written to CSV.
 */
public final class DefenseCoursePlugin extends JavaPlugin implements Listener {
    private enum Profile {
        MIXED,
        WATER_HEAVY,
        LAVA_HEAVY
    }

    private record Run(
        UUID playerId,
        UUID vehicleId,
        String id,
        Profile profile,
        long startedTick
    ) {
    }

    private String worldName;
    private int startX;
    private int endX;
    private int minY;
    private int maxY;
    private int minZ;
    private int maxZ;
    private int witnessX;
    private int witnessY;
    private int witnessZ;
    private int regenPeriod;
    private int planesPerPass;
    private boolean regenEnabled;

    private long tick;
    private Profile builtProfile = Profile.MIXED;
    private final List<Integer> regenPlanes = new ArrayList<>();
    private int regenCursor;
    private BukkitTask regenTask;
    private final Map<UUID, Run> runs = new HashMap<>();
    private final Map<UUID, Integer> lastChunk = new HashMap<>();

    private BufferedWriter writer;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        loadSettings();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> tick++, 1L, 1L);
        openTelemetry();
        getLogger().info("PhaseLab DefenseCourse enabled: X=[" + startX + ',' + endX + "]");
    }

    @Override
    public void onDisable() {
        stopRegeneration();
        runs.clear();
        lastChunk.clear();
        closeTelemetry();
    }

    private void loadSettings() {
        worldName = getConfig().getString("course.world", "world");
        startX = getConfig().getInt("course.start-x", 0);
        endX = getConfig().getInt("course.end-x", 239);
        minY = getConfig().getInt("course.minimum-y", 65);
        maxY = getConfig().getInt("course.maximum-y", 69);
        minZ = getConfig().getInt("course.minimum-z", -3);
        maxZ = getConfig().getInt("course.maximum-z", 3);
        witnessX = getConfig().getInt("course.witness-x", 244);
        witnessY = getConfig().getInt("course.witness-y", 65);
        witnessZ = getConfig().getInt("course.witness-z", 0);
        regenEnabled = getConfig().getBoolean("regeneration.enabled", true);
        regenPeriod = Math.max(1, getConfig().getInt("regeneration.period-ticks", 2));
        planesPerPass = Math.max(1, getConfig().getInt("regeneration.planes-per-pass", 8));
    }

    private World world() {
        return Bukkit.getWorld(worldName);
    }

    private void build(Profile profile) {
        World world = world();
        if (world == null) {
            throw new IllegalStateException("World is not loaded: " + worldName);
        }

        stopRegeneration();
        builtProfile = profile;
        regenPlanes.clear();
        regenCursor = 0;

        for (int x = startX; x <= endX; x++) {
            Material material = materialAt(profile, x);
            setPlane(world, x, material);
            if (shouldRegenerate(profile, x)) {
                regenPlanes.add(x);
            }
        }

        for (int x = startX - 8; x <= endX + 12; x++) {
            for (int z = minZ - 3; z <= maxZ + 3; z++) {
                world.getBlockAt(x, minY - 1, z).setType(Material.STONE, false);
            }
        }
        for (int x = endX + 1; x <= endX + 10; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    world.getBlockAt(x, y, z).setType(Material.AIR, false);
                }
            }
        }
        world.getBlockAt(witnessX, witnessY, witnessZ).setType(Material.BARREL, false);

        if (regenEnabled) {
            regenTask = Bukkit.getScheduler().runTaskTimer(
                this,
                this::regenerate,
                regenPeriod,
                regenPeriod
            );
        }
        telemetry("COURSE_BUILT", null, null, null,
            startX, minY, 0.0D,
            "profile=" + profile + ";regenPlanes=" + regenPlanes.size());
    }

    private void setPlane(World world, int x, Material material) {
        boolean physics = material == Material.WATER || material == Material.LAVA;
        for (int y = minY; y <= maxY; y++) {
            for (int z = minZ; z <= maxZ; z++) {
                world.getBlockAt(x, y, z).setType(material, physics);
            }
        }
    }

    private Material materialAt(Profile profile, int x) {
        int lane = Math.floorMod(x - startX, 16);
        return switch (profile) {
            case MIXED -> switch (lane) {
                case 0, 15 -> Material.OBSIDIAN;
                case 2, 10 -> Material.WATER;
                case 5, 13 -> Material.LAVA;
                case 7 -> Material.COBBLESTONE;
                case 9 -> Material.BASALT;
                case 11 -> Material.CRYING_OBSIDIAN;
                default -> Material.OBSIDIAN;
            };
            case WATER_HEAVY -> switch (lane) {
                case 0, 15 -> Material.OBSIDIAN;
                case 1, 2, 5, 6, 9, 10, 13, 14 -> Material.WATER;
                case 7 -> Material.COBBLESTONE;
                case 11 -> Material.CRYING_OBSIDIAN;
                default -> Material.OBSIDIAN;
            };
            case LAVA_HEAVY -> switch (lane) {
                case 0, 15 -> Material.OBSIDIAN;
                case 1, 4, 7, 10, 13 -> Material.LAVA;
                case 2, 8 -> Material.WATER;
                case 5 -> Material.COBBLESTONE;
                case 11 -> Material.BASALT;
                default -> Material.OBSIDIAN;
            };
        };
    }

    private boolean shouldRegenerate(Profile profile, int x) {
        Material material = materialAt(profile, x);
        int lane = Math.floorMod(x - startX, 16);
        return lane == 0
            || lane == 15
            || material == Material.WATER
            || material == Material.LAVA
            || material == Material.COBBLESTONE
            || material == Material.BASALT;
    }

    private void regenerate() {
        World world = world();
        if (world == null || regenPlanes.isEmpty()) {
            return;
        }
        int count = Math.min(planesPerPass, regenPlanes.size());
        for (int index = 0; index < count; index++) {
            int x = regenPlanes.get(Math.floorMod(regenCursor++, regenPlanes.size()));
            setPlane(world, x, materialAt(builtProfile, x));
        }
    }

    private void stopRegeneration() {
        if (regenTask != null) {
            regenTask.cancel();
            regenTask = null;
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleMove(VehicleMoveEvent event) {
        Vehicle vehicle = event.getVehicle();
        for (Entity passenger : vehicle.getPassengers()) {
            if (!(passenger instanceof Player player)) {
                continue;
            }
            Run run = runs.get(player.getUniqueId());
            if (run == null) {
                continue;
            }
            int chunk = Math.floorDiv(event.getTo().getBlockX(), 16);
            int previous = lastChunk.getOrDefault(player.getUniqueId(), Integer.MIN_VALUE);
            if (chunk != previous) {
                lastChunk.put(player.getUniqueId(), chunk);
                telemetry("CHUNK_PROGRESS", run, player, vehicle,
                    event.getTo().getX(), event.getTo().getY(), player.getHealth(),
                    "chunk=" + chunk + ";fire=" + player.getFireTicks());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleDamage(VehicleDamageEvent event) {
        Run run = runForVehicle(event.getVehicle());
        if (run != null) {
            Player player = Bukkit.getPlayer(run.playerId());
            telemetry("VEHICLE_DAMAGE", run, player, event.getVehicle(),
                event.getVehicle().getLocation().getX(),
                event.getVehicle().getLocation().getY(),
                player == null ? -1.0D : player.getHealth(),
                "damage=" + event.getDamage() + ";cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleDestroy(VehicleDestroyEvent event) {
        Run run = runForVehicle(event.getVehicle());
        if (run != null) {
            Player player = Bukkit.getPlayer(run.playerId());
            telemetry("VEHICLE_DESTROY", run, player, event.getVehicle(),
                event.getVehicle().getLocation().getX(),
                event.getVehicle().getLocation().getY(),
                player == null ? -1.0D : player.getHealth(),
                "cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleExit(VehicleExitEvent event) {
        if (event.getExited() instanceof Player player) {
            Run run = runs.get(player.getUniqueId());
            if (run != null) {
                telemetry("VEHICLE_EXIT", run, player, event.getVehicle(),
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "cancelled=" + event.isCancelled());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onDamage(EntityDamageEvent event) {
        if (event.getEntity() instanceof Player player) {
            Run run = runs.get(player.getUniqueId());
            if (run != null) {
                telemetry("PLAYER_DAMAGE", run, player, player.getVehicle(),
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "cause=" + event.getCause() + ";damage=" + event.getFinalDamage()
                        + ";cancelled=" + event.isCancelled());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onCombust(EntityCombustEvent event) {
        if (event.getEntity() instanceof Player player) {
            Run run = runs.get(player.getUniqueId());
            if (run != null) {
                telemetry("PLAYER_COMBUST", run, player, player.getVehicle(),
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "duration=" + event.getDuration() + ";cancelled=" + event.isCancelled());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onDeath(PlayerDeathEvent event) {
        Player player = event.getEntity();
        Run run = runs.get(player.getUniqueId());
        if (run != null) {
            telemetry("PLAYER_DEATH", run, player, player.getVehicle(),
                player.getLocation().getX(), player.getLocation().getY(), 0.0D,
                "message=" + event.getDeathMessage());
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        runs.remove(event.getPlayer().getUniqueId());
        lastChunk.remove(event.getPlayer().getUniqueId());
    }

    private Run runForVehicle(Entity vehicle) {
        for (Run run : runs.values()) {
            if (run.vehicleId().equals(vehicle.getUniqueId())) {
                return run;
            }
        }
        return null;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage("DefenseCourse profile=" + builtProfile
                + " X=[" + startX + ',' + endX + "] regen=" + (regenTask != null)
                + " active=" + runs.size()
                + " telemetry=" + (telemetryPath == null ? "disabled" : telemetryPath));
            return true;
        }

        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "build" -> {
                Profile profile;
                try {
                    profile = args.length >= 2
                        ? Profile.valueOf(args[1].toUpperCase(Locale.ROOT))
                        : Profile.MIXED;
                    build(profile);
                    sender.sendMessage("Defense course built: " + profile);
                } catch (RuntimeException exception) {
                    sender.sendMessage("Course build failed: " + exception.getMessage());
                }
                return true;
            }
            case "start" -> {
                if (!(sender instanceof Player player)) {
                    sender.sendMessage("Run this command as the test player.");
                    return true;
                }
                Entity vehicle = player.getVehicle();
                if (vehicle == null) {
                    sender.sendMessage("Mount the test vehicle first.");
                    return true;
                }
                String id = args.length >= 2
                    ? args[1]
                    : "run-" + Instant.now().toEpochMilli();
                Run run = new Run(player.getUniqueId(), vehicle.getUniqueId(), id, builtProfile, tick);
                runs.put(player.getUniqueId(), run);
                lastChunk.remove(player.getUniqueId());
                telemetry("RUN_START", run, player, vehicle,
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "fire=" + player.getFireTicks());
                sender.sendMessage("Defense course telemetry started: " + id);
                return true;
            }
            case "stop" -> {
                if (!(sender instanceof Player player)) {
                    sender.sendMessage("Run this command as the test player.");
                    return true;
                }
                Run run = runs.remove(player.getUniqueId());
                lastChunk.remove(player.getUniqueId());
                if (run != null) {
                    telemetry("RUN_STOP", run, player, player.getVehicle(),
                        player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                        "z=" + player.getLocation().getZ() + ";fire=" + player.getFireTicks());
                }
                sender.sendMessage("Defense course telemetry stopped.");
                return true;
            }
            case "snapshot" -> {
                if (!(sender instanceof Player player)) {
                    sender.sendMessage("Run this command as the test player.");
                    return true;
                }
                Entity vehicle = player.getVehicle();
                sender.sendMessage(String.format(Locale.ROOT,
                    "COURSE_SNAPSHOT player=%.6f,%.6f,%.6f health=%.3f fire=%d vehicle=%s",
                    player.getLocation().getX(),
                    player.getLocation().getY(),
                    player.getLocation().getZ(),
                    player.getHealth(),
                    player.getFireTicks(),
                    vehicle == null
                        ? "none"
                        : String.format(Locale.ROOT, "%.6f,%.6f,%.6f",
                            vehicle.getLocation().getX(),
                            vehicle.getLocation().getY(),
                            vehicle.getLocation().getZ())
                ));
                return true;
            }
            case "reset" -> {
                runs.clear();
                lastChunk.clear();
                sender.sendMessage("Defense course runtime state reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /courselab <status|build|start|stop|snapshot|reset>");
                return true;
            }
        }
    }

    private void openTelemetry() {
        if (!getConfig().getBoolean("telemetry.enabled", true)) {
            return;
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            telemetryPath = getDataFolder().toPath().resolve(
                "defense-course-" + Instant.now().toString().replace(':', '-') + ".csv");
            writer = Files.newBufferedWriter(
                telemetryPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            writer.write("time,tick,event,run_id,profile,player,vehicle,vehicle_uuid,x,y,health,action\n");
            writer.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open defense telemetry: " + exception.getMessage());
            writer = null;
            telemetryPath = null;
        }
    }

    private void telemetry(
        String event,
        Run run,
        Player player,
        Entity vehicle,
        double x,
        double y,
        double health,
        String action
    ) {
        if (writer == null) {
            return;
        }
        try {
            writer.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%s,%s,%s,%.6f,%.6f,%.3f,%s%n",
                Instant.now(),
                tick,
                event,
                run == null ? "none" : csv(run.id()),
                run == null ? builtProfile : run.profile(),
                player == null ? "none" : csv(player.getName()),
                vehicle == null ? "none" : vehicle.getType(),
                vehicle == null ? "none" : vehicle.getUniqueId(),
                x,
                y,
                health,
                csv(action)
            ));
            writer.flush();
        } catch (IOException ignored) {
        }
    }

    private String csv(String value) {
        return value == null
            ? ""
            : value.replace(',', ';').replace('\n', ' ').replace('\r', ' ');
    }

    private void closeTelemetry() {
        if (writer == null) {
            return;
        }
        try {
            writer.close();
        } catch (IOException ignored) {
        } finally {
            writer = null;
        }
    }
}
