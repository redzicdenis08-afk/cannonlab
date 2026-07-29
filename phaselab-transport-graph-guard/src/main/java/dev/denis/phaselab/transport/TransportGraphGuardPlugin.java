package dev.denis.phaselab.transport;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDismountEvent;
import org.bukkit.event.entity.EntityMountEvent;
import org.bukkit.event.entity.EntityPortalEvent;
import org.bukkit.event.entity.EntityTeleportEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
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
 * Defensive passenger-graph transport validator.
 *
 * Root-entity movement is not equivalent to an ordinary player teleport. This
 * guard snapshots the full graph before mounting and validates entity teleports,
 * portal transitions and the dismount that follows them.
 */
public final class TransportGraphGuardPlugin extends JavaPlugin implements Listener {
    private double minimumX;
    private double maximumX;
    private int quarantineTicks;

    private long logicalTick;
    private long blockedTeleports;
    private long blockedPortals;
    private long correctedDismounts;

    private final Map<UUID, Location> playerAnchors = new HashMap<>();
    private final Map<UUID, Location> rootAnchors = new HashMap<>();
    private final Map<UUID, Long> quarantineUntil = new HashMap<>();
    private final Map<UUID, Long> allowedUntil = new HashMap<>();
    private final Set<UUID> internalMoves = new HashSet<>();

    @Override
    public void onEnable() {
        getConfig().addDefault("claim-zone.minimum-x", 0.0D);
        getConfig().addDefault("claim-zone.maximum-x", 255.999D);
        getConfig().addDefault("quarantine.ticks", 60);
        getConfig().options().copyDefaults(true);
        saveConfig();

        minimumX = getConfig().getDouble("claim-zone.minimum-x", 0.0D);
        maximumX = getConfig().getDouble("claim-zone.maximum-x", 255.999D);
        if (minimumX > maximumX) {
            double swap = minimumX;
            minimumX = maximumX;
            maximumX = swap;
        }
        quarantineTicks = Math.max(20, getConfig().getInt("quarantine.ticks", 60));

        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, this::tick, 1L, 1L);
        getLogger().info("PhaseLab TransportGraphGuard enabled: claimX=["
            + minimumX + "," + maximumX + "] quarantineTicks=" + quarantineTicks);
    }

    private void tick() {
        logicalTick++;
        quarantineUntil.entrySet().removeIf(entry -> entry.getValue() < logicalTick);
        allowedUntil.entrySet().removeIf(entry -> entry.getValue() < logicalTick);

        for (Map.Entry<UUID, Long> entry : new ArrayList<>(quarantineUntil.entrySet())) {
            Player player = Bukkit.getPlayer(entry.getKey());
            Location anchor = playerAnchors.get(entry.getKey());
            if (player != null && player.isOnline() && anchor != null && isProtected(player.getLocation())) {
                forcePlayer(player, anchor, "QUARANTINE_TICK");
            }
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void onMount(EntityMountEvent event) {
        if (!(event.getEntity() instanceof Player player) || isAllowed(player)) {
            return;
        }
        Entity root = rootVehicle(event.getMount());
        Location playerLocation = player.getLocation();
        if (!isProtected(playerLocation)) {
            playerAnchors.put(player.getUniqueId(), playerLocation.clone());
        }
        Location rootLocation = root.getLocation();
        if (!isProtected(rootLocation)) {
            rootAnchors.put(root.getUniqueId(), rootLocation.clone());
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onEntityTeleport(EntityTeleportEvent event) {
        inspectTransport(event.getEntity(), event.getFrom(), event.getTo(), () -> event.setCancelled(true), false);
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onEntityPortal(EntityPortalEvent event) {
        inspectTransport(event.getEntity(), event.getFrom(), event.getTo(), () -> event.setCancelled(true), true);
    }

    private void inspectTransport(Entity entity, Location from, Location to,
                                  Runnable cancel, boolean portal) {
        if (to == null) {
            return;
        }
        Entity root = rootVehicle(entity);
        if (internalMoves.contains(root.getUniqueId())) {
            return;
        }
        List<Player> players = recursivePlayers(root);
        List<Player> guarded = players.stream().filter(player -> !isAllowed(player)).toList();
        if (guarded.isEmpty()) {
            return;
        }

        if (!isProtected(from)) {
            rootAnchors.putIfAbsent(root.getUniqueId(), from.clone());
            for (Player player : guarded) {
                playerAnchors.putIfAbsent(player.getUniqueId(), player.getLocation().clone());
            }
        }
        if (!isProtected(to)) {
            return;
        }

        cancel.run();
        if (portal) blockedPortals++; else blockedTeleports++;
        rollbackGraph(root, guarded, portal ? "ENTITY_PORTAL" : "ENTITY_TELEPORT");
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDismount(EntityDismountEvent event) {
        if (!(event.getEntity() instanceof Player player) || isAllowed(player)) {
            return;
        }
        Location anchor = playerAnchors.get(player.getUniqueId());
        if (anchor == null) {
            return;
        }
        quarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        for (long delay : new long[] {0L, 1L, 2L, 5L}) {
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (player.isOnline() && isProtected(player.getLocation())) {
                    correctedDismounts++;
                    forcePlayer(player, anchor, "POST_TRANSPORT_DISMOUNT");
                }
            }, delay);
        }
    }

    private void rollbackGraph(Entity root, List<Player> players, String reason) {
        Location rootAnchor = rootAnchors.get(root.getUniqueId());
        if (rootAnchor == null) {
            return;
        }
        internalMoves.add(root.getUniqueId());
        Map<UUID, Location> anchors = new HashMap<>();
        for (Player player : players) {
            Location anchor = playerAnchors.getOrDefault(player.getUniqueId(), rootAnchor).clone();
            anchors.put(player.getUniqueId(), anchor);
            quarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        }

        Bukkit.getScheduler().runTask(this, () -> {
            if (root.isValid()) {
                root.eject();
                root.setVelocity(new Vector());
                root.teleport(rootAnchor);
            }
            for (Player player : players) {
                Location anchor = anchors.get(player.getUniqueId());
                if (anchor != null) {
                    forcePlayer(player, anchor, reason);
                }
            }
            internalMoves.remove(root.getUniqueId());
        });
    }

    private void forcePlayer(Player player, Location anchor, String reason) {
        player.leaveVehicle();
        player.setVelocity(new Vector());
        player.teleport(anchor, PlayerTeleportEvent.TeleportCause.PLUGIN);
        getLogger().warning("TransportGraphGuard anchored " + player.getName()
            + " reason=" + reason + " at=" + format(anchor));
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        UUID id = event.getPlayer().getUniqueId();
        playerAnchors.remove(id);
        quarantineUntil.remove(id);
        allowedUntil.remove(id);
    }

    private boolean isAllowed(Player player) {
        Long until = allowedUntil.get(player.getUniqueId());
        return until != null && until >= logicalTick;
    }

    private boolean isProtected(Location location) {
        return location != null && location.getX() >= minimumX && location.getX() <= maximumX;
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
        List<Player> result = new ArrayList<>();
        collect(root, result, new HashSet<>());
        return result;
    }

    private void collect(Entity entity, List<Player> result, Set<UUID> visited) {
        if (!visited.add(entity.getUniqueId())) return;
        if (entity instanceof Player player) result.add(player);
        for (Entity passenger : entity.getPassengers()) collect(passenger, result, visited);
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage(String.format(Locale.ROOT,
                "TransportGraphGuard claimX=[%.3f,%.3f] tick=%d teleports=%d portals=%d dismounts=%d roots=%d players=%d",
                minimumX, maximumX, logicalTick, blockedTeleports, blockedPortals,
                correctedDismounts, rootAnchors.size(), playerAnchors.size()));
            return true;
        }
        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "zone" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /transportguard zone <minimum-x> <maximum-x>");
                    return true;
                }
                try {
                    double first = Double.parseDouble(args[1]);
                    double second = Double.parseDouble(args[2]);
                    minimumX = Math.min(first, second);
                    maximumX = Math.max(first, second);
                    sender.sendMessage("TransportGraphGuard zone set to X=[" + minimumX + "," + maximumX + "]");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Zone coordinates must be numbers.");
                }
                return true;
            }
            case "allow" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /transportguard allow <player> <ticks>");
                    return true;
                }
                Player target = Bukkit.getPlayerExact(args[1]);
                if (target == null) {
                    sender.sendMessage("Target player is not online.");
                    return true;
                }
                try {
                    long ticks = Math.max(1, Long.parseLong(args[2]));
                    allowedUntil.put(target.getUniqueId(), logicalTick + ticks);
                    sender.sendMessage("Transport allowed for " + target.getName() + " for " + ticks + " ticks.");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Ticks must be an integer.");
                }
                return true;
            }
            case "probe" -> {
                if (!(sender instanceof Player player) || args.length != 4) {
                    sender.sendMessage("Usage: /transportguard probe <x> <y> <z>");
                    return true;
                }
                Entity root = rootVehicle(player);
                if (root == player) {
                    sender.sendMessage("Mount a transport entity first.");
                    return true;
                }
                try {
                    Location destination = new Location(player.getWorld(),
                        Double.parseDouble(args[1]), Double.parseDouble(args[2]),
                        Double.parseDouble(args[3]), root.getYaw(), root.getPitch());
                    boolean result = root.teleport(destination);
                    sender.sendMessage("Transport probe apiResult=" + result + " root=" + root.getType());
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Coordinates must be numbers.");
                }
                return true;
            }
            case "snapshot" -> {
                Player target = args.length >= 2 ? Bukkit.getPlayerExact(args[1])
                    : sender instanceof Player player ? player : null;
                if (target == null) {
                    sender.sendMessage("Usage: /transportguard snapshot [player]");
                    return true;
                }
                Entity root = rootVehicle(target);
                Location playerLocation = target.getLocation();
                Location rootLocation = root.getLocation();
                sender.sendMessage(String.format(Locale.ROOT,
                    "TRANSPORT_SNAPSHOT player=%.6f,%.6f,%.6f root=%s@%.6f,%.6f,%.6f protected=%s mounted=%s",
                    playerLocation.getX(), playerLocation.getY(), playerLocation.getZ(),
                    root.getType(), rootLocation.getX(), rootLocation.getY(), rootLocation.getZ(),
                    isProtected(playerLocation), root != target));
                return true;
            }
            case "reset" -> {
                playerAnchors.clear();
                rootAnchors.clear();
                quarantineUntil.clear();
                allowedUntil.clear();
                internalMoves.clear();
                blockedTeleports = blockedPortals = correctedDismounts = 0;
                sender.sendMessage("TransportGraphGuard reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /transportguard <status|zone|allow|probe|snapshot|reset>");
                return true;
            }
        }
    }

    private String format(Location location) {
        return String.format(Locale.ROOT, "%.3f,%.3f,%.3f",
            location.getX(), location.getY(), location.getZ());
    }
}
