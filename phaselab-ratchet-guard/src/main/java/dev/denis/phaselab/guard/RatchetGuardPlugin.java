package dev.denis.phaselab.guard;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.vehicle.VehicleMoveEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.Vector;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Defensive regression guard for mounted claim-cancellation ratchets.
 *
 * A cancellation-only player listener can leave the vehicle's authoritative
 * position inside the protected interval. Later vehicle packets then begin
 * inside the interval and no longer look like a border crossing. This guard
 * stores an outside anchor and rolls the complete vehicle/passenger graph back
 * together whenever any anchored vehicle is observed inside the protected zone.
 */
public final class RatchetGuardPlugin extends JavaPlugin implements Listener {
    private double minimumX;
    private double maximumX;
    private int rollbackRepetitions;
    private int rollbackSpacingTicks;

    private long logicalTick;
    private long blockedTransitions;

    private final Map<UUID, Location> safeVehicleLocations = new HashMap<>();
    private final Map<UUID, Location> safePlayerLocations = new HashMap<>();
    private final Set<UUID> rollbackEntities = new HashSet<>();

    @Override
    public void onEnable() {
        getConfig().addDefault("claim-zone.minimum-x", 0.0D);
        getConfig().addDefault("claim-zone.maximum-x", 255.999D);
        getConfig().addDefault("rollback.repetitions", 4);
        getConfig().addDefault("rollback.spacing-ticks", 1);
        getConfig().options().copyDefaults(true);
        saveConfig();

        minimumX = getConfig().getDouble("claim-zone.minimum-x", 0.0D);
        maximumX = getConfig().getDouble("claim-zone.maximum-x", 255.999D);
        if (minimumX > maximumX) {
            double swap = minimumX;
            minimumX = maximumX;
            maximumX = swap;
        }
        rollbackRepetitions = Math.max(2,
            getConfig().getInt("rollback.repetitions", 4));
        rollbackSpacingTicks = Math.max(1,
            getConfig().getInt("rollback.spacing-ticks", 1));

        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> logicalTick++, 1L, 1L);
        getLogger().info("PhaseLab RatchetGuard enabled: claimX=[" + minimumX + ","
            + maximumX + "] repetitions=" + rollbackRepetitions);
    }

    @Override
    public void onDisable() {
        safeVehicleLocations.clear();
        safePlayerLocations.clear();
        rollbackEntities.clear();
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onVehicleMove(VehicleMoveEvent event) {
        Entity root = rootVehicle(event.getVehicle());
        if (rollbackEntities.contains(root.getUniqueId())) {
            return;
        }

        List<Player> players = recursivePlayers(root);
        if (players.isEmpty()) {
            return;
        }

        if (!isClaim(event.getFrom())) {
            rememberSafe(root, players, event.getFrom());
        }

        // Deliberately checks every inside destination, not only outside->inside.
        // That closes the ratchet where later packets already start inside.
        if (isClaim(event.getTo()) && safeVehicleLocations.containsKey(root.getUniqueId())) {
            scheduleAtomicRollback(root, players, "VEHICLE_INSIDE_PROTECTED_ZONE");
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onMountedPlayerMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        Entity mounted = player.getVehicle();
        if (mounted == null) {
            return;
        }

        Entity root = rootVehicle(mounted);
        if (rollbackEntities.contains(root.getUniqueId())) {
            return;
        }

        List<Player> players = recursivePlayers(root);
        if (!isClaim(event.getFrom())) {
            rememberSafe(root, players, event.getFrom());
        }

        if (isClaim(event.getTo()) && safeVehicleLocations.containsKey(root.getUniqueId())) {
            event.setCancelled(true);
            scheduleAtomicRollback(root, players, "PLAYER_INSIDE_PROTECTED_ZONE");
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        UUID playerId = event.getPlayer().getUniqueId();
        safePlayerLocations.remove(playerId);
        rollbackEntities.remove(playerId);
    }

    private void rememberSafe(Entity root, List<Player> players, Location fallback) {
        Location rootLocation = root.getLocation();
        safeVehicleLocations.put(root.getUniqueId(),
            isClaim(rootLocation) ? fallback.clone() : rootLocation.clone());

        for (Player player : players) {
            Location playerLocation = player.getLocation();
            safePlayerLocations.put(player.getUniqueId(),
                isClaim(playerLocation) ? fallback.clone() : playerLocation.clone());
        }
    }

    private void scheduleAtomicRollback(Entity root, List<Player> players, String reason) {
        if (!rollbackEntities.add(root.getUniqueId())) {
            return;
        }
        players.forEach(player -> rollbackEntities.add(player.getUniqueId()));

        Location safeVehicle = safeVehicleLocations.get(root.getUniqueId());
        if (safeVehicle == null) {
            releaseRollback(root, players, 1L);
            return;
        }

        Map<UUID, Location> playerAnchors = new HashMap<>();
        for (Player player : players) {
            Location anchor = safePlayerLocations.get(player.getUniqueId());
            playerAnchors.put(player.getUniqueId(),
                anchor == null ? safeVehicle.clone() : anchor.clone());
        }

        blockedTransitions++;
        getLogger().warning("RatchetGuard blocked mounted protected-zone advance tick="
            + logicalTick + " reason=" + reason + " vehicle=" + root.getType()
            + " passengers=" + players.size());

        for (int iteration = 0; iteration < rollbackRepetitions; iteration++) {
            long delay = (long) iteration * rollbackSpacingTicks;
            Bukkit.getScheduler().runTaskLater(this, () -> rollbackOnce(
                root,
                players,
                safeVehicle,
                playerAnchors
            ), delay);
        }

        long releaseDelay = (long) rollbackRepetitions * rollbackSpacingTicks + 2L;
        releaseRollback(root, players, releaseDelay);
    }

    private void rollbackOnce(
        Entity root,
        List<Player> players,
        Location safeVehicle,
        Map<UUID, Location> playerAnchors
    ) {
        if (root.isValid()) {
            root.eject();
            root.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
            root.teleport(safeVehicle);
        }

        for (Player player : players) {
            if (!player.isOnline()) {
                continue;
            }
            player.leaveVehicle();
            player.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
            Location anchor = playerAnchors.get(player.getUniqueId());
            if (anchor != null) {
                player.teleport(anchor);
            }
        }
    }

    private void releaseRollback(Entity root, List<Player> players, long delay) {
        Bukkit.getScheduler().runTaskLater(this, () -> {
            rollbackEntities.remove(root.getUniqueId());
            players.forEach(player -> rollbackEntities.remove(player.getUniqueId()));
        }, delay);
    }

    private Entity rootVehicle(Entity entity) {
        Entity current = entity;
        Set<UUID> visited = new HashSet<>();
        while (current.getVehicle() != null && visited.add(current.getUniqueId())) {
            current = current.getVehicle();
        }
        return current;
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

    private boolean isClaim(Location location) {
        return location != null
            && location.getX() >= minimumX
            && location.getX() <= maximumX;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage(String.format(Locale.ROOT,
                "RatchetGuard claimX=[%.3f,%.3f] blocked=%d anchors=%d activeRollbacks=%d",
                minimumX,
                maximumX,
                blockedTransitions,
                safeVehicleLocations.size(),
                rollbackEntities.size()
            ));
            return true;
        }

        if (args[0].equalsIgnoreCase("reset")) {
            safeVehicleLocations.clear();
            safePlayerLocations.clear();
            rollbackEntities.clear();
            blockedTransitions = 0L;
            sender.sendMessage("RatchetGuard runtime state reset.");
            return true;
        }

        sender.sendMessage("Usage: /ratchetguard <status|reset>");
        return true;
    }
}
