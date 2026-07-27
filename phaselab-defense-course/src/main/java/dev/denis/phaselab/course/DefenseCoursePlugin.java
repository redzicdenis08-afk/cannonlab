package dev.denis.phaselab.course;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
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
import org.bukkit.event.player.PlayerDeathEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.vehicle.VehicleDamageEvent;
import org.bukkit.event.vehicle.VehicleDestroyEvent;
import org.bukkit.event.vehicle.VehicleEnterEvent;
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
 * Builds and continuously rewrites a 240-block, fifteen-chunk mixed defense
 * course. It is a lab fixture, not a factions implementation.
 *
 * The physical region contains solid collision planes, water, lava, cobblestone,
 * basalt, crying obsidian and chunk-seam obsidian. During an active run, selected
 * planes are regenerated every few ticks with normal physics updates. Telemetry
 * records chunk progress, health, fire, vehicle damage/destruction, dismounts,
 * deaths and authoritative coordinates.
 */
public final class DefenseCoursePlugin extends JavaPlugin implements Listener {
    private enum Profile {
        MIXED,
        WATER_HEAVY,
        LAVA_HEAVY
    }

    private record ActiveRun(
        UUID playerId,
        UUID rootVehicleId,
        String runId,
        Profile profile,
        long startedTick
    ) {
    }

    private String worldName;
    private int startX;
    private int endX;
    private int minimumY;
    private int maximumY;
    private int minimumZ;
    private int maximumZ;
    private int witnessX;
    private int witnessY;
    private int witnessZ;
    private boolean regenerationEnabled;
    private int regenerationPeriodTicks;
    private int planesPerPass;

    private long logicalTick;
    private Profile builtProfile = Profile.MIXED;
    private final List<Integer> regeneratingPlanes = new ArrayList<>();
    private int regenerationCursor;
    private BukkitTask regenerationTask;
    private final Map<UUID, ActiveRun> activeRuns = new HashMap<>();
    private final Map<UUID, Integer> lastVehicleChunk = new HashMap<>();

    private BufferedWriter telemetryWriter;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        loadSettings();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> logicalTick++, 1L, 1L);
        openTelemetry();
        getLogger().info("PhaseLab DefenseCourse enabled: X=[" + startX + ',' + endX
            + "] profile=" + builtProfile + " regenPeriod=" + regenerationPeriodTicks);
    }

    @Override
    public void onDisable() {
        stopRegeneration();
        closeTelemetry();
        activeRuns.clear();
        lastVehicleChunk.clear();
    }

    private void loadSettings() {
        worldName = getConfig().getString("course.world", "world");
        startX = getConfig().getInt("course.start-x", 0);
        endX = getConfig().getInt("course.end-x", 239);
        minimumY = getConfig().getInt("course.minimum-y", 65);
        maximumY = getConfig().getInt("course.maximum-y", 69);
        minimumZ = getConfig().getInt("course.minimum-z", -3);
        maximumZ = getConfig().getInt("course.maximum-z", 3);
        witnessX = getConfig().getInt("course.witness-x", 244);
        witnessY = getConfig().getInt("course.witness-y", 65);
        witnessZ = getConfig().getInt("course.witness-z", 0);
        if (startX > endX) {
            int swap = startX;
            startX = endX;
            endX = swap;
        }
        if (minimumY > maximumY) {
            int swap = minimumY;
            minimumY = maximumY;
            maximumY = swap;
        }
        if (minimumZ > maximumZ) {
            int swap = minimumZ;
            minimumZ = maximumZ;
            maximumZ = swap;
        }
        regenerationEnabled = getConfig().getBoolean("regeneration.enabled", true);
        regenerationPeriodTicks = Math.max(1,
            getConfig().getInt("regeneration.period-ticks", 2));
        planesPerPass = Math.max(1,
            getConfig().getInt("regeneration.planes-per-pass", 8));
    }

    private World world() {
        return Bukkit.getWorld(worldName);
    }

    private void buildCourse(Profile profile) {
        World world = world();
        if (world == null) {
            throw new IllegalStateException("World is not loaded: " + worldName);
        }

        stopRegeneration();
        builtProfile = profile;
        regeneratingPlanes.clear();
        regenerationCursor = 0;

        for (int x = startX; x <= endX; x++) {
            Material material = materialAt(profile, x);
            boolean physics = material == Material.WATER || material == Material.LAVA;
            for (int y = minimumY; y <= maximumY; y++) {
                for (int z = minimumZ; z <= maximumZ; z++) {
                    world.getBlockAt(x, y, z).setType(material, physics);
                }
            }
            if (isRegeneratingPlane(profile, x)) {
                regeneratingPlanes.add(x);
            }
        }

        for (int x = startX - 8; x <= endX + 12; x++) {
            for (int z = minimumZ - 3; z <= maximumZ + 3; z++) {
                world.getBlockAt(x, minimumY - 1, z).setType(Material.STONE, false);
            }
        }
        for (int x = endX + 1; x <= endX + 10; x++) {
            for (int y = minimumY; y <= maximumY; y++) {
                for (int z = minimumZ; z <= maximumZ; z++) {
                    world.getBlockAt(x, y, z).setType(Material.AIR, false);
                }
            }
        }
        Block witness = world.getBlockAt(witnessX, witnessY, witnessZ);
        witness.setType(Material.BARREL, false);

        if (regenerationEnabled) {
            startRegeneration();
        }
        telemetry("COURSE_BUILT", null, null, null,
            startX, minimumY, 0.0D, "profile=" + profile + ";planes=" + regeneratingPlanes.size());
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

    private boolean isRegeneratingPlane(Profile profile, int x) {
        int lane = Math.floorMod(x - startX, 16);
        return lane == 0
            || lane == 15
            || materialAt(profile, x) == Material.WATER
            || materialAt(profile, x) == Material.LAVA
            || materialAt(profile, x) == Material.COBBLESTONE
            || materialAt(profile, x) == Material.BASALT;
    }

    private void startRegeneration() {
        stopRegeneration();
        regenerationTask = Bukkit.getScheduler().runTaskTimer(
            this,
            this::regeneratePass,
            regenerationPeriodTicks,
            regenerationPeriodTicks
        );
    }

    private void stopRegeneration() {
        if (regenerationTask != null) {
            regenerationTask.cancel();
            regenerationTask = null;
        }
    }

    private void regeneratePass() {
        World world = world();
        if (world == null || regeneratingPlanes.isEmpty()) {
            return;
        }
        int count = Math.min(planesPerPass, regeneratingPlanes.size());
        for (int index = 0; index < count; index++) {
            int planeIndex = Math.floorMod(regenerationCursor++, regeneratingPlanes.size());
            int x = regeneratingPlanes.get(planeIndex);
            Material material = materialAt(builtProfile, x);
            boolean physics = material == Material.WATER || material == Material.LAVA;
            for (int y = minimumY; y <= maximumY; y++) {
                for (int z = minimumZ; z <= maximumZ; z++) {
                    world.getBlockAt(x, y, z).setType(material, physics);
                }
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleMove(VehicleMoveEvent event) {
        Vehicle vehicle = event.getVehicle();
        for (Entity passenger : vehicle.getPassengers()) {
            if (!(passenger instanceof Player player)) {
                continue;
            }
            ActiveRun run = activeRuns.get(player.getUniqueId());
            if (run == null) {
                continue;
            }
            int chunk = Math.floorDiv(event.getTo().getBlockX(), 16);
            int previous = lastVehicleChunk.getOrDefault(player.getUniqueId(), Integer.MIN_VALUE);
            if (chunk != previous) {
                lastVehicleChunk.put(player.getUniqueId(), chunk);
                telemetry("CHUNK_PROGRESS", run, player, vehicle,
                    event.getTo().getX(), event.getTo().getY(), player.getHealth(),
                    "chunk=" + chunk + ";fire=" + player.getFireTicks());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleDamage(VehicleDamageEvent event) {
        Vehicle vehicle = event.getVehicle();
        ActiveRun run = runForVehicle(vehicle);
        if (run != null) {
            Player player = Bukkit.getPlayer(run.playerId());
            telemetry("VEHICLE_DAMAGE", run, player, vehicle,
                vehicle.getLocation().getX(), vehicle.getLocation().getY(),
                player == null ? -1.0D : player.getHealth(),
                "damage=" + event.getDamage() + ";cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleDestroy(VehicleDestroyEvent event) {
        Vehicle vehicle = event.getVehicle();
        ActiveRun run = runForVehicle(vehicle);
        if (run != null) {
            Player player = Bukkit.getPlayer(run.playerId());
            telemetry("VEHICLE_DESTROY", run, player, vehicle,
                vehicle.getLocation().getX(), vehicle.getLocation().getY(),
                player == null ? -1.0D : player.getHealth(),
                "cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleEnter(VehicleEnterEvent event) {
        if (event.getEntered() instanceof Player player) {
            ActiveRun run = activeRuns.get(player.getUniqueId());
            if (run != null) {
                telemetry("VEHICLE_ENTER", run, player, event.getVehicle(),
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "cancelled=" + event.isCancelled());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleExit(VehicleExitEvent event) {
        if (event.getExited() instanceof Player player) {
            ActiveRun run = activeRuns.get(player.getUniqueId());
            if (run != null) {
                telemetry("VEHICLE_EXIT", run, player, event.getVehicle(),
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "cancelled=" + event.isCancelled());
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onPlayerDamage(EntityDamageEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }
        ActiveRun run = activeRuns.get(player.getUniqueId());
        if (run != null) {
            telemetry("PLAYER_DAMAGE", run, player, player.getVehicle(),
                player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                "cause=" + event.getCause() + ";damage=" + event.getFinalDamage()
                    + ";cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onCombust(EntityCombustEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }
        ActiveRun run = activeRuns.get(player.getUniqueId());
        if (run != null) {
            telemetry("PLAYER_COMBUST", run, player, player.getVehicle(),
                player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                "duration=" + event.getDuration() + ";cancelled=" + event.isCancelled());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onDeath(PlayerDeathEvent event) {
        Player player = event.getEntity();
        ActiveRun run = activeRuns.get(player.getUniqueId());
        if (run != null) {
            telemetry("PLAYER_DEATH", run, player, player.getVehicle(),
                player.getLocation().getX(), player.getLocation().getY(), 0.0D,
                "message=" + event.getDeathMessage());
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        activeRuns.remove(event.getPlayer().getUniqueId());
        lastVehicleChunk.remove(event.getPlayer().getUniqueId());
    }

    private ActiveRun runForVehicle(Entity vehicle) {
        for (ActiveRun run : activeRuns.values()) {
            if (run.rootVehicleId().equals(vehicle.getUniqueId())) {
                return run;
            }
        }
        return null;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage("DefenseCourse profile=" + builtProfile
                + " X=[" + startX + ',' + endX + "] regen=" + (regenerationTask != null)
                + " activeRuns=" + activeRuns.size()
                + " telemetry=" + (telemetryPath == null ? "disabled" : telemetryPath));
            return true;
        }

        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "build" -> {
                Profile profile = args.length >= 2 ? parseProfile(args[1]) : Profile.MIXED;
                try {
                    buildCourse(profile);
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
                Entity vehicle = player.getRootVehicle();
                if (vehicle == player) {
                    sender.sendMessage("Mount the test vehicle before starting telemetry.");
                    return true;
                }
                String runId = args.length >= 2
                    ? args[1]
                    : "run-" + Instant.now().toEpochMilli();
                ActiveRun run = new ActiveRun(
                    player.getUniqueId(),
                    vehicle.getUniqueId(),
                    runId,
                    builtProfile,
                    logicalTick
                );
                activeRuns.put(player.getUniqueId(), run);
                lastVehicleChunk.remove(player.getUniqueId());
                telemetry("RUN_START", run, player, vehicle,
                    player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                    "fire=" + player.getFireTicks());
                sender.sendMessage("Defense course telemetry started: " + runId);
                return true;
            }
            case "stop" -> {
                if (!(sender instanceof Player player)) {
                    sender.sendMessage("Run this command as the test player.");
                    return true;
                }
                ActiveRun run = activeRuns.remove(player.getUniqueId());
                lastVehicleChunk.remove(player.getUniqueId());
                if (run != null) {
                    telemetry("RUN_STOP", run, player, player.getVehicle(),
                        player.getLocation().getX(), player.getLocation().getY(), player.getHealth(),
                        "fire=" + player.getFireTicks());
                }
                sender.sendMessage("Defense course telemetry stopped.");
                return true;
            }
            case "reset" -> {
                activeRuns.clear();
                lastVehicleChunk.clear();
                sender.sendMessage("Defense course runtime state reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /courselab <status|build [mixed|water_heavy|lava_heavy]|start [id]|stop|reset>");
                return true;
            }
        }
    }

    private Profile parseProfile(String text) {
        try {
            return Profile.valueOf(text.toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Profile must be MIXED, WATER_HEAVY, or LAVA_HEAVY.");
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
            telemetryWriter = Files.newBufferedWriter(
                telemetryPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            telemetryWriter.write(
                "time,tick,event,run_id,profile,player,vehicle,vehicle_uuid,x,y,health,action\n");
            telemetryWriter.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open defense course telemetry: " + exception.getMessage());
            telemetryWriter = null;
            telemetryPath = null;
        }
    }

    private void telemetry(
        String event,
        ActiveRun run,
        Player player,
        Entity vehicle,
        double x,
        double y,
        double health,
        String action
    ) {
        if (telemetryWriter == null) {
            return;
        }
        try {
            telemetryWriter.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%s,%s,%s,%.6f,%.6f,%.3f,%s%n",
                Instant.now(),
                logicalTick,
                event,
                run == null ? "none" : csv(run.runId()),
                run == null ? builtProfile : run.profile(),
                player == null ? "none" : csv(player.getName()),
                vehicle == null ? "none" : vehicle.getType(),
                vehicle == null ? "none" : vehicle.getUniqueId(),
                x,
                y,
                health,
                csv(action)
            ));
            telemetryWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private String csv(String value) {
        return value == null
            ? ""
            : value.replace(',', ';').replace('\n', ' ').replace('\r', ' ');
    }

    private void closeTelemetry() {
        if (telemetryWriter == null) {
            return;
        }
        try {
            telemetryWriter.close();
        } catch (IOException ignored) {
        } finally {
            telemetryWriter = null;
        }
    }
}
