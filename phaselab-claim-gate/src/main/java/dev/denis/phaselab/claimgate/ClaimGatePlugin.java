package dev.denis.phaselab.claimgate;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.entity.Vehicle;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityMountEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.vehicle.VehicleMoveEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.Vector;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Defensive laboratory reconstruction of a mounted hostile-claim gate.
 *
 * The plugin intentionally supports three enforcement strengths:
 *  OBSERVE - telemetry only.
 *  LIKELY  - deny hostile mounting inside the claim and cancel mounted player
 *            transitions into the claim.
 *  STRICT  - LIKELY plus root-vehicle rollback, recursive passenger ejection,
 *            repeated rollback for several ticks, and movement-rate enforcement.
 *
 * It is deliberately independent from a real factions plugin. The X interval is
 * treated as hostile territory and per-player relation is controlled by command,
 * allowing reproducible ENEMY versus TRUCE tests on an authorized Sakura clone.
 */
public final class ClaimGatePlugin extends JavaPlugin implements Listener {
    private enum GateMode {
        OBSERVE,
        LIKELY,
        STRICT
    }

    private enum Relation {
        ENEMY,
        TRUCE
    }

    private GateMode mode;
    private double minimumX;
    private double maximumX;
    private int maxMountedEventsPerTick;
    private int rollbackRepetitions;
    private int rollbackSpacingTicks;

    private long logicalTick;
    private final Map<UUID, Relation> relations = new HashMap<>();
    private final Map<UUID, Integer> movementCountThisTick = new HashMap<>();
    private final Map<UUID, Location> lastSafePlayerLocation = new HashMap<>();
    private final Map<UUID, Location> lastSafeVehicleLocation = new HashMap<>();
    private final Set<UUID> internalRollbackPlayers = new HashSet<>();
    private final Set<UUID> internalRollbackVehicles = new HashSet<>();

    private BufferedWriter telemetryWriter;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        loadSettings();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> {
            logicalTick++;
            movementCountThisTick.clear();
        }, 1L, 1L);
        openTelemetry();
        getLogger().info("PhaseLab ClaimGate enabled: mode=" + mode
            + " claimX=[" + minimumX + "," + maximumX + "]"
            + " maxMountedEventsPerTick=" + maxMountedEventsPerTick);
    }

    @Override
    public void onDisable() {
        closeTelemetry();
        relations.clear();
        movementCountThisTick.clear();
        lastSafePlayerLocation.clear();
        lastSafeVehicleLocation.clear();
        internalRollbackPlayers.clear();
        internalRollbackVehicles.clear();
    }

    private void loadSettings() {
        mode = parseMode(getConfig().getString("mode", "STRICT"));
        minimumX = getConfig().getDouble("claim-zone.minimum-x", 0.0D);
        maximumX = getConfig().getDouble("claim-zone.maximum-x", 255.999D);
        if (minimumX > maximumX) {
            double oldMinimum = minimumX;
            minimumX = maximumX;
            maximumX = oldMinimum;
        }
        maxMountedEventsPerTick = Math.max(1,
            getConfig().getInt("movement.max-mounted-events-per-tick", 20));
        rollbackRepetitions = Math.max(1,
            getConfig().getInt("movement.rollback-repetitions", 3));
        rollbackSpacingTicks = Math.max(1,
            getConfig().getInt("movement.rollback-spacing-ticks", 1));
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onMountedPlayerMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (internalRollbackPlayers.contains(player.getUniqueId())) {
            return;
        }

        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            return;
        }

        int movementCount = movementCountThisTick.merge(player.getUniqueId(), 1, Integer::sum);
        Relation relation = relation(player);
        boolean fromClaim = isClaim(event.getFrom());
        boolean toClaim = isClaim(event.getTo());

        if (!fromClaim) {
            rememberSafe(player, vehicle, event.getFrom());
        }

        boolean enteringHostileClaim = relation == Relation.ENEMY && !fromClaim && toClaim;
        boolean movementFlood = relation == Relation.ENEMY
            && movementCount > maxMountedEventsPerTick;

        if (!enteringHostileClaim && !(mode == GateMode.STRICT && movementFlood)) {
            if (fromClaim != toClaim) {
                telemetry("PLAYER_BORDER_ALLOWED", player, vehicle,
                    event.getFrom(), event.getTo(), movementCount, "ALLOW");
            }
            return;
        }

        String trigger = enteringHostileClaim ? "HOSTILE_BORDER" : "RATE_LIMIT";
        if (mode == GateMode.OBSERVE) {
            telemetry("PLAYER_MOVE_OBSERVED", player, vehicle,
                event.getFrom(), event.getTo(), movementCount, trigger);
            return;
        }

        event.setCancelled(true);
        telemetry("PLAYER_MOVE_CANCELLED", player, vehicle,
            event.getFrom(), event.getTo(), movementCount, trigger);

        if (mode == GateMode.STRICT) {
            scheduleStrictRollback(vehicle, event.getFrom(), trigger);
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleMove(VehicleMoveEvent event) {
        Vehicle vehicle = event.getVehicle();
        if (internalRollbackVehicles.contains(vehicle.getUniqueId())) {
            return;
        }

        List<Player> passengers = recursivePlayers(vehicle);
        if (passengers.isEmpty()) {
            return;
        }

        boolean fromClaim = isClaim(event.getFrom());
        boolean toClaim = isClaim(event.getTo());
        if (!fromClaim) {
            lastSafeVehicleLocation.put(vehicle.getUniqueId(), event.getFrom().clone());
            for (Player passenger : passengers) {
                lastSafePlayerLocation.put(passenger.getUniqueId(), passenger.getLocation().clone());
            }
        }

        List<Player> hostilePassengers = passengers.stream()
            .filter(player -> relation(player) == Relation.ENEMY)
            .toList();
        if (hostilePassengers.isEmpty() || fromClaim || !toClaim) {
            return;
        }

        for (Player hostile : hostilePassengers) {
            telemetry("VEHICLE_BORDER_OBSERVED", hostile, vehicle,
                event.getFrom(), event.getTo(),
                movementCountThisTick.getOrDefault(hostile.getUniqueId(), 0),
                mode == GateMode.STRICT ? "ROLLBACK" : "OBSERVE");
        }

        if (mode == GateMode.STRICT) {
            scheduleStrictRollback(vehicle, event.getFrom(), "VEHICLE_MOVE_EVENT");
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onMount(EntityMountEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }
        if (internalRollbackPlayers.contains(player.getUniqueId())) {
            return;
        }

        Entity mount = event.getMount();
        Relation relation = relation(player);
        boolean denied = relation == Relation.ENEMY && isClaim(mount.getLocation());
        if (!denied) {
            telemetry("MOUNT_ALLOWED", player, mount,
                player.getLocation(), mount.getLocation(), 0, "ALLOW");
            return;
        }

        telemetry("MOUNT_DENIED", player, mount,
            player.getLocation(), mount.getLocation(), 0,
            mode == GateMode.OBSERVE ? "OBSERVE" : "CANCEL");
        if (mode != GateMode.OBSERVE) {
            event.setCancelled(true);
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        UUID id = event.getPlayer().getUniqueId();
        movementCountThisTick.remove(id);
        lastSafePlayerLocation.remove(id);
        internalRollbackPlayers.remove(id);
    }

    private void rememberSafe(Player player, Entity vehicle, Location fallback) {
        lastSafePlayerLocation.put(player.getUniqueId(), fallback.clone());
        lastSafeVehicleLocation.put(vehicle.getUniqueId(), vehicle.getLocation().clone());
    }

    private void scheduleStrictRollback(Entity rootVehicle, Location fallback, String reason) {
        if (internalRollbackVehicles.contains(rootVehicle.getUniqueId())) {
            return;
        }

        Location safeVehicle = lastSafeVehicleLocation
            .getOrDefault(rootVehicle.getUniqueId(), fallback)
            .clone();
        List<Player> passengers = recursivePlayers(rootVehicle);
        Map<UUID, Location> safePlayers = new HashMap<>();
        for (Player passenger : passengers) {
            safePlayers.put(passenger.getUniqueId(), lastSafePlayerLocation
                .getOrDefault(passenger.getUniqueId(), fallback)
                .clone());
        }

        internalRollbackVehicles.add(rootVehicle.getUniqueId());
        passengers.forEach(player -> internalRollbackPlayers.add(player.getUniqueId()));

        for (int iteration = 0; iteration < rollbackRepetitions; iteration++) {
            long delay = (long) iteration * rollbackSpacingTicks;
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (rootVehicle.isValid()) {
                    rootVehicle.eject();
                    rootVehicle.setVelocity(new Vector());
                    rootVehicle.teleport(safeVehicle);
                }
                for (Player passenger : passengers) {
                    if (!passenger.isOnline()) {
                        continue;
                    }
                    passenger.leaveVehicle();
                    passenger.setVelocity(new Vector());
                    Location safe = safePlayers.get(passenger.getUniqueId());
                    if (safe != null) {
                        passenger.teleport(safe);
                    }
                    telemetry("STRICT_ROLLBACK", passenger, rootVehicle,
                        passenger.getLocation(), safe, 0, reason);
                }
            }, delay);
        }

        long releaseDelay = (long) rollbackRepetitions * rollbackSpacingTicks + 1L;
        Bukkit.getScheduler().runTaskLater(this, () -> {
            internalRollbackVehicles.remove(rootVehicle.getUniqueId());
            passengers.forEach(player -> internalRollbackPlayers.remove(player.getUniqueId()));
        }, releaseDelay);
    }

    private List<Player> recursivePlayers(Entity root) {
        List<Player> players = new ArrayList<>();
        collectPlayers(root, players, new HashSet<>());
        return players;
    }

    private void collectPlayers(Entity entity, List<Player> output, Set<UUID> visited) {
        if (!visited.add(entity.getUniqueId())) {
            return;
        }
        if (entity instanceof Player player) {
            output.add(player);
        }
        for (Entity passenger : entity.getPassengers()) {
            collectPlayers(passenger, output, visited);
        }
    }

    private Relation relation(Player player) {
        return relations.getOrDefault(player.getUniqueId(), Relation.ENEMY);
    }

    private boolean isClaim(Location location) {
        return location != null
            && location.getX() >= minimumX
            && location.getX() <= maximumX;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage("ClaimGate mode=" + mode
                + " claimX=[" + minimumX + "," + maximumX + "]"
                + " maxEvents/tick=" + maxMountedEventsPerTick
                + " telemetry=" + (telemetryPath == null ? "disabled" : telemetryPath));
            return true;
        }

        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "mode" -> {
                if (args.length != 2) {
                    sender.sendMessage("Usage: /claimlab mode <observe|likely|strict>");
                    return true;
                }
                try {
                    mode = parseMode(args[1]);
                    getConfig().set("mode", mode.name());
                    saveConfig();
                    sender.sendMessage("ClaimGate mode set to " + mode);
                } catch (IllegalArgumentException exception) {
                    sender.sendMessage(exception.getMessage());
                }
                return true;
            }
            case "relation" -> {
                return relationCommand(sender, args);
            }
            case "zone" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /claimlab zone <minimum-x> <maximum-x>");
                    return true;
                }
                try {
                    double first = Double.parseDouble(args[1]);
                    double second = Double.parseDouble(args[2]);
                    minimumX = Math.min(first, second);
                    maximumX = Math.max(first, second);
                    getConfig().set("claim-zone.minimum-x", minimumX);
                    getConfig().set("claim-zone.maximum-x", maximumX);
                    saveConfig();
                    sender.sendMessage("Claim zone set to X=[" + minimumX + "," + maximumX + "]");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Both zone values must be numbers.");
                }
                return true;
            }
            case "reset" -> {
                movementCountThisTick.clear();
                lastSafePlayerLocation.clear();
                lastSafeVehicleLocation.clear();
                internalRollbackPlayers.clear();
                internalRollbackVehicles.clear();
                sender.sendMessage("ClaimGate runtime state reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /claimlab <status|mode|relation|zone|reset>");
                return true;
            }
        }
    }

    private boolean relationCommand(CommandSender sender, String[] args) {
        Player target;
        String relationText;
        if (args.length == 2 && sender instanceof Player player) {
            target = player;
            relationText = args[1];
        } else if (args.length == 3) {
            target = Bukkit.getPlayerExact(args[1]);
            relationText = args[2];
        } else {
            sender.sendMessage("Usage: /claimlab relation [player] <enemy|truce>");
            return true;
        }

        if (target == null) {
            sender.sendMessage("Target player is not online.");
            return true;
        }

        try {
            Relation relation = Relation.valueOf(relationText.toUpperCase(Locale.ROOT));
            relations.put(target.getUniqueId(), relation);
            sender.sendMessage("Claim relation for " + target.getName() + " set to " + relation);
            target.sendMessage("[PhaseLab] Claim relation set to " + relation);
        } catch (IllegalArgumentException exception) {
            sender.sendMessage("Relation must be ENEMY or TRUCE.");
        }
        return true;
    }

    private GateMode parseMode(String text) {
        try {
            return GateMode.valueOf(text.toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Mode must be OBSERVE, LIKELY, or STRICT.");
        }
    }

    private void openTelemetry() {
        if (!getConfig().getBoolean("telemetry.enabled", true)) {
            return;
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            telemetryPath = getDataFolder().toPath().resolve(
                "claim-gate-" + Instant.now().toString().replace(':', '-') + ".csv");
            telemetryWriter = Files.newBufferedWriter(
                telemetryPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            telemetryWriter.write(
                "time,tick,event,mode,player,relation,vehicle,from_x,from_y,from_z,to_x,to_y,to_z,events_this_tick,action\n");
            telemetryWriter.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open ClaimGate telemetry: " + exception.getMessage());
            telemetryWriter = null;
            telemetryPath = null;
        }
    }

    private void telemetry(
        String event,
        Player player,
        Entity vehicle,
        Location from,
        Location to,
        int eventCount,
        String action
    ) {
        if (telemetryWriter == null) {
            return;
        }
        Location safeFrom = from == null ? zeroLocation(player.getWorld()) : from;
        Location safeTo = to == null ? zeroLocation(player.getWorld()) : to;
        try {
            telemetryWriter.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%d,%s%n",
                Instant.now(),
                logicalTick,
                event,
                mode,
                csv(player.getName()),
                relation(player),
                vehicle == null ? "none" : csv(vehicle.getType().toString()),
                safeFrom.getX(), safeFrom.getY(), safeFrom.getZ(),
                safeTo.getX(), safeTo.getY(), safeTo.getZ(),
                eventCount,
                csv(action)
            ));
            telemetryWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private Location zeroLocation(World world) {
        return new Location(world, 0.0D, 0.0D, 0.0D);
    }

    private String csv(String value) {
        return value.replace(',', ';').replace('\n', ' ').replace('\r', ' ');
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
