package dev.denis.phaselab.surface;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDismountEvent;
import org.bukkit.event.entity.EntityMountEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.vehicle.VehicleMoveEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.BoundingBox;
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
 * Unified defensive phase regression guard for an authorized Sakura laboratory.
 *
 * The guard never trusts a client-local position. It maintains server-side safe
 * anchors and validates mounted movement, guarded teleport causes, dismount
 * placement, post-ejection stale packets, and solid-block overlap.
 */
public final class SurfaceGuardPlugin extends JavaPlugin implements Listener {
    private enum Relation {
        ENEMY,
        TRUCE
    }

    private double minimumX;
    private double maximumX;
    private int rollbackRepetitions;
    private int rollbackSpacingTicks;
    private int quarantineTicks;
    private double collisionEpsilon;

    private long logicalTick;
    private long mountedBlocks;
    private long teleportBlocks;
    private long dismountBlocks;
    private long collisionBlocks;

    private final Map<UUID, Relation> relations = new HashMap<>();
    private final Map<UUID, Location> safePlayerLocations = new HashMap<>();
    private final Map<UUID, Location> safeVehicleLocations = new HashMap<>();
    private final Map<UUID, Long> playerQuarantineUntil = new HashMap<>();
    private final Map<UUID, Long> temporaryAllowUntil = new HashMap<>();
    private final Set<UUID> activeRollbacks = new HashSet<>();

    private BufferedWriter telemetryWriter;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        getConfig().addDefault("claim-zone.minimum-x", 0.0D);
        getConfig().addDefault("claim-zone.maximum-x", 255.999D);
        getConfig().addDefault("rollback.repetitions", 4);
        getConfig().addDefault("rollback.spacing-ticks", 1);
        getConfig().addDefault("rollback.player-quarantine-ticks", 60);
        getConfig().addDefault("collision.epsilon", 0.001D);
        getConfig().addDefault("telemetry.enabled", true);
        getConfig().options().copyDefaults(true);
        saveConfig();

        loadSettings();
        openTelemetry();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, this::guardTick, 1L, 1L);

        getLogger().info("PhaseLab SurfaceGuard enabled: claimX=[" + minimumX + ","
            + maximumX + "] quarantineTicks=" + quarantineTicks);
    }

    @Override
    public void onDisable() {
        closeTelemetry();
        relations.clear();
        safePlayerLocations.clear();
        safeVehicleLocations.clear();
        playerQuarantineUntil.clear();
        temporaryAllowUntil.clear();
        activeRollbacks.clear();
    }

    private void loadSettings() {
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
        quarantineTicks = Math.max(20,
            getConfig().getInt("rollback.player-quarantine-ticks", 60));
        collisionEpsilon = Math.max(0.0001D,
            getConfig().getDouble("collision.epsilon", 0.001D));
    }

    private void guardTick() {
        logicalTick++;
        expireMap(playerQuarantineUntil);
        expireMap(temporaryAllowUntil);

        for (Map.Entry<UUID, Long> entry : new ArrayList<>(playerQuarantineUntil.entrySet())) {
            if (entry.getValue() < logicalTick) {
                continue;
            }
            Player player = Bukkit.getPlayer(entry.getKey());
            Location anchor = safePlayerLocations.get(entry.getKey());
            if (player == null || !player.isOnline() || anchor == null) {
                continue;
            }
            if (isProtected(player.getLocation()) || overlapsSolid(player, player.getLocation())) {
                forcePlayerAnchor(player, anchor, "QUARANTINE_TICK");
            }
        }
    }

    private void expireMap(Map<UUID, Long> map) {
        map.entrySet().removeIf(entry -> entry.getValue() < logicalTick);
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onPlayerMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        Location to = event.getTo();
        if (to == null || !isEnemy(player) || isTemporarilyAllowed(player)) {
            rememberOrdinarySafe(player, to);
            return;
        }

        UUID playerId = player.getUniqueId();
        Long quarantineUntil = playerQuarantineUntil.get(playerId);
        if (quarantineUntil != null && quarantineUntil >= logicalTick
            && (isProtected(to) || overlapsSolid(player, to))) {
            event.setCancelled(true);
            collisionBlocks++;
            rollbackPlayer(player, "POST_TRANSITION_QUARANTINE", event.getFrom(), to);
            return;
        }

        Entity mounted = player.getVehicle();
        if (mounted != null) {
            Entity root = rootVehicle(mounted);
            List<Player> passengers = recursivePlayers(root);
            if (!isProtected(event.getFrom())) {
                rememberMountedSafe(root, passengers, event.getFrom());
            }
            if (isProtected(to) && safeVehicleLocations.containsKey(root.getUniqueId())) {
                event.setCancelled(true);
                mountedBlocks++;
                telemetry("MOUNTED_PLAYER_BLOCK", player, root, event.getFrom(), to,
                    "PROTECTED_DESTINATION");
                scheduleAtomicRollback(root, passengers, "MOUNTED_PLAYER_MOVE");
                return;
            }
        } else {
            rememberOrdinarySafe(player, to);
            if (overlapsSolid(player, to) && safePlayerLocations.containsKey(playerId)) {
                event.setCancelled(true);
                collisionBlocks++;
                rollbackPlayer(player, "SOLID_OVERLAP_MOVE", event.getFrom(), to);
            }
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onVehicleMove(VehicleMoveEvent event) {
        Entity root = rootVehicle(event.getVehicle());
        if (activeRollbacks.contains(root.getUniqueId())) {
            return;
        }

        List<Player> enemies = recursivePlayers(root).stream()
            .filter(this::isEnemy)
            .filter(player -> !isTemporarilyAllowed(player))
            .toList();
        if (enemies.isEmpty()) {
            return;
        }

        if (!isProtected(event.getFrom())) {
            rememberMountedSafe(root, enemies, event.getFrom());
        }
        if (isProtected(event.getTo()) && safeVehicleLocations.containsKey(root.getUniqueId())) {
            mountedBlocks++;
            for (Player player : enemies) {
                telemetry("VEHICLE_BLOCK", player, root, event.getFrom(), event.getTo(),
                    "PROTECTED_DESTINATION");
            }
            scheduleAtomicRollback(root, enemies, "VEHICLE_MOVE");
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onMount(EntityMountEvent event) {
        if (!(event.getEntity() instanceof Player player)
            || !isEnemy(player)
            || isTemporarilyAllowed(player)) {
            return;
        }
        if (isProtected(event.getMount().getLocation())) {
            event.setCancelled(true);
            mountedBlocks++;
            telemetry("MOUNT_BLOCK", player, event.getMount(), player.getLocation(),
                event.getMount().getLocation(), "MOUNT_INSIDE_PROTECTED_ZONE");
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDismount(EntityDismountEvent event) {
        if (!(event.getEntity() instanceof Player player)
            || !isEnemy(player)
            || isTemporarilyAllowed(player)) {
            return;
        }

        Location anchor = safePlayerLocations.get(player.getUniqueId());
        if (anchor == null && !isProtected(event.getDismounted().getLocation())) {
            anchor = event.getDismounted().getLocation().clone();
            safePlayerLocations.put(player.getUniqueId(), anchor.clone());
        }
        if (anchor == null) {
            return;
        }

        playerQuarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        Location finalAnchor = anchor.clone();
        for (long delay : new long[] {0L, 1L, 2L, 5L}) {
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (!player.isOnline()) {
                    return;
                }
                Location current = player.getLocation();
                if (isProtected(current) || overlapsSolid(player, current)) {
                    dismountBlocks++;
                    telemetry("DISMOUNT_BLOCK", player, event.getDismounted(), finalAnchor,
                        current, "INVALID_DISMOUNT_DESTINATION");
                    forcePlayerAnchor(player, finalAnchor, "DISMOUNT_VALIDATION");
                }
            }, delay);
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onTeleport(PlayerTeleportEvent event) {
        Player player = event.getPlayer();
        Location to = event.getTo();
        if (to == null || !isEnemy(player) || isTemporarilyAllowed(player)
            || !isGuardedCause(event.getCause())) {
            return;
        }

        boolean crossesProtection = !isProtected(event.getFrom()) && isProtected(to);
        boolean collides = overlapsSolid(player, to);
        if (crossesProtection || collides) {
            event.setCancelled(true);
            teleportBlocks++;
            Location anchor = safePlayerLocations.getOrDefault(player.getUniqueId(),
                event.getFrom()).clone();
            safePlayerLocations.put(player.getUniqueId(), anchor.clone());
            playerQuarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
            telemetry("TELEPORT_BLOCK", player, player, event.getFrom(), to,
                event.getCause() + (collides ? ":COLLISION" : ":PROTECTED_CROSSING"));
            Bukkit.getScheduler().runTask(this,
                () -> forcePlayerAnchor(player, anchor, "TELEPORT_VALIDATION"));
            return;
        }

        Bukkit.getScheduler().runTask(this, () -> {
            if (!player.isOnline()) {
                return;
            }
            Location current = player.getLocation();
            if (overlapsSolid(player, current)) {
                teleportBlocks++;
                Location anchor = safePlayerLocations.getOrDefault(player.getUniqueId(),
                    event.getFrom()).clone();
                playerQuarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
                forcePlayerAnchor(player, anchor, "POST_TELEPORT_COLLISION");
            }
        });
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        UUID id = event.getPlayer().getUniqueId();
        relations.remove(id);
        safePlayerLocations.remove(id);
        playerQuarantineUntil.remove(id);
        temporaryAllowUntil.remove(id);
        activeRollbacks.remove(id);
    }

    private boolean isGuardedCause(PlayerTeleportEvent.TeleportCause cause) {
        return cause == PlayerTeleportEvent.TeleportCause.ENDER_PEARL
            || cause == PlayerTeleportEvent.TeleportCause.CHORUS_FRUIT
            || cause == PlayerTeleportEvent.TeleportCause.NETHER_PORTAL
            || cause == PlayerTeleportEvent.TeleportCause.END_PORTAL;
    }

    private void rememberOrdinarySafe(Player player, Location location) {
        if (location == null || isProtected(location) || overlapsSolid(player, location)) {
            return;
        }
        safePlayerLocations.put(player.getUniqueId(), location.clone());
    }

    private void rememberMountedSafe(Entity root, List<Player> players, Location fallback) {
        Location rootLocation = root.getLocation();
        safeVehicleLocations.put(root.getUniqueId(),
            isProtected(rootLocation) ? fallback.clone() : rootLocation.clone());
        for (Player player : players) {
            Location playerLocation = player.getLocation();
            safePlayerLocations.put(player.getUniqueId(),
                isProtected(playerLocation) ? fallback.clone() : playerLocation.clone());
        }
    }

    private void scheduleAtomicRollback(Entity root, List<Player> players, String reason) {
        if (!activeRollbacks.add(root.getUniqueId())) {
            return;
        }
        players.forEach(player -> activeRollbacks.add(player.getUniqueId()));

        Location vehicleAnchor = safeVehicleLocations.get(root.getUniqueId());
        if (vehicleAnchor == null) {
            activeRollbacks.remove(root.getUniqueId());
            players.forEach(player -> activeRollbacks.remove(player.getUniqueId()));
            return;
        }

        Map<UUID, Location> playerAnchors = new HashMap<>();
        for (Player player : players) {
            Location anchor = safePlayerLocations.getOrDefault(player.getUniqueId(),
                vehicleAnchor).clone();
            playerAnchors.put(player.getUniqueId(), anchor);
            playerQuarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        }

        for (int iteration = 0; iteration < rollbackRepetitions; iteration++) {
            long delay = (long) iteration * rollbackSpacingTicks;
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (root.isValid()) {
                    root.eject();
                    root.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
                    root.teleport(vehicleAnchor);
                }
                for (Player player : players) {
                    if (!player.isOnline()) {
                        continue;
                    }
                    Location anchor = playerAnchors.get(player.getUniqueId());
                    if (anchor != null) {
                        forcePlayerAnchor(player, anchor, reason);
                    }
                }
            }, delay);
        }

        long releaseDelay = (long) rollbackRepetitions * rollbackSpacingTicks + 2L;
        Bukkit.getScheduler().runTaskLater(this, () -> {
            activeRollbacks.remove(root.getUniqueId());
            players.forEach(player -> activeRollbacks.remove(player.getUniqueId()));
        }, releaseDelay);
    }

    private void rollbackPlayer(Player player, String reason, Location from, Location to) {
        Location anchor = safePlayerLocations.get(player.getUniqueId());
        if (anchor == null) {
            anchor = from.clone();
            safePlayerLocations.put(player.getUniqueId(), anchor.clone());
        }
        playerQuarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        telemetry("PLAYER_ROLLBACK", player, player, from, to, reason);
        Location finalAnchor = anchor.clone();
        Bukkit.getScheduler().runTask(this,
            () -> forcePlayerAnchor(player, finalAnchor, reason));
    }

    private void forcePlayerAnchor(Player player, Location anchor, String reason) {
        if (!player.isOnline()) {
            return;
        }
        player.leaveVehicle();
        player.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
        player.teleport(anchor, PlayerTeleportEvent.TeleportCause.PLUGIN);
        telemetry("FORCE_ANCHOR", player, player, player.getLocation(), anchor, reason);
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

    private boolean overlapsSolid(Player player, Location location) {
        World world = location.getWorld();
        if (world == null) {
            return false;
        }

        BoundingBox current = player.getBoundingBox();
        double halfWidthX = (current.getMaxX() - current.getMinX()) * 0.5D;
        double halfWidthZ = (current.getMaxZ() - current.getMinZ()) * 0.5D;
        double height = current.getMaxY() - current.getMinY();
        BoundingBox box = new BoundingBox(
            location.getX() - halfWidthX + collisionEpsilon,
            location.getY() + collisionEpsilon,
            location.getZ() - halfWidthZ + collisionEpsilon,
            location.getX() + halfWidthX - collisionEpsilon,
            location.getY() + height - collisionEpsilon,
            location.getZ() + halfWidthZ - collisionEpsilon
        );

        int minX = (int) Math.floor(box.getMinX());
        int maxX = (int) Math.floor(box.getMaxX() - collisionEpsilon);
        int minY = (int) Math.floor(box.getMinY());
        int maxY = (int) Math.floor(box.getMaxY() - collisionEpsilon);
        int minZ = (int) Math.floor(box.getMinZ());
        int maxZ = (int) Math.floor(box.getMaxZ() - collisionEpsilon);

        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (block.getType().isSolid() && !block.isPassable()) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private boolean isProtected(Location location) {
        return location != null
            && location.getX() >= minimumX
            && location.getX() <= maximumX;
    }

    private boolean isEnemy(Player player) {
        return relations.getOrDefault(player.getUniqueId(), Relation.ENEMY) == Relation.ENEMY;
    }

    private boolean isTemporarilyAllowed(Player player) {
        Long allowedUntil = temporaryAllowUntil.get(player.getUniqueId());
        return allowedUntil != null && allowedUntil >= logicalTick;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage(String.format(Locale.ROOT,
                "SurfaceGuard claimX=[%.3f,%.3f] tick=%d mounted=%d teleports=%d dismounts=%d collisions=%d anchors=%d quarantines=%d telemetry=%s",
                minimumX, maximumX, logicalTick, mountedBlocks, teleportBlocks,
                dismountBlocks, collisionBlocks, safePlayerLocations.size(),
                playerQuarantineUntil.size(), telemetryPath == null ? "off" : telemetryPath));
            return true;
        }

        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "zone" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /surfaceguard zone <minimum-x> <maximum-x>");
                    return true;
                }
                try {
                    double first = Double.parseDouble(args[1]);
                    double second = Double.parseDouble(args[2]);
                    minimumX = Math.min(first, second);
                    maximumX = Math.max(first, second);
                    sender.sendMessage("SurfaceGuard zone set to X=[" + minimumX + "," + maximumX + "]");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Zone coordinates must be numbers.");
                }
                return true;
            }
            case "relation" -> {
                return relationCommand(sender, args);
            }
            case "allow" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /surfaceguard allow <player> <ticks>");
                    return true;
                }
                Player target = Bukkit.getPlayerExact(args[1]);
                if (target == null) {
                    sender.sendMessage("Target player is not online.");
                    return true;
                }
                try {
                    long ticks = Math.max(1L, Long.parseLong(args[2]));
                    temporaryAllowUntil.put(target.getUniqueId(), logicalTick + ticks);
                    sender.sendMessage("Allowed SurfaceGuard transitions for " + target.getName()
                        + " for " + ticks + " ticks.");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Ticks must be an integer.");
                }
                return true;
            }
            case "snapshot" -> {
                Player target = args.length >= 2 ? Bukkit.getPlayerExact(args[1])
                    : sender instanceof Player player ? player : null;
                if (target == null) {
                    sender.sendMessage("Usage: /surfaceguard snapshot [player]");
                    return true;
                }
                Location location = target.getLocation();
                Entity vehicle = target.getVehicle();
                sender.sendMessage(String.format(Locale.ROOT,
                    "SURFACE_SNAPSHOT player=%.6f,%.6f,%.6f health=%.3f vehicle=%s protected=%s collision=%s quarantine=%s",
                    location.getX(), location.getY(), location.getZ(), target.getHealth(),
                    vehicle == null ? "none" : vehicle.getType() + "@"
                        + String.format(Locale.ROOT, "%.6f,%.6f,%.6f",
                        vehicle.getLocation().getX(), vehicle.getLocation().getY(),
                        vehicle.getLocation().getZ()),
                    isProtected(location), overlapsSolid(target, location),
                    playerQuarantineUntil.getOrDefault(target.getUniqueId(), -1L)));
                return true;
            }
            case "probe" -> {
                if (!(sender instanceof Player player) || args.length != 5) {
                    sender.sendMessage("Usage: /surfaceguard probe <pearl|chorus|nether|end> <x> <y> <z>");
                    return true;
                }
                try {
                    PlayerTeleportEvent.TeleportCause cause = switch (args[1].toLowerCase(Locale.ROOT)) {
                        case "pearl" -> PlayerTeleportEvent.TeleportCause.ENDER_PEARL;
                        case "chorus" -> PlayerTeleportEvent.TeleportCause.CHORUS_FRUIT;
                        case "nether" -> PlayerTeleportEvent.TeleportCause.NETHER_PORTAL;
                        case "end" -> PlayerTeleportEvent.TeleportCause.END_PORTAL;
                        default -> throw new IllegalArgumentException("Unknown probe cause.");
                    };
                    Location destination = new Location(player.getWorld(),
                        Double.parseDouble(args[2]), Double.parseDouble(args[3]),
                        Double.parseDouble(args[4]), player.getYaw(), player.getPitch());
                    boolean result = player.teleport(destination, cause);
                    sender.sendMessage("SurfaceGuard probe cause=" + cause + " apiResult=" + result);
                } catch (IllegalArgumentException exception) {
                    sender.sendMessage(exception.getMessage());
                }
                return true;
            }
            case "reset" -> {
                safePlayerLocations.clear();
                safeVehicleLocations.clear();
                playerQuarantineUntil.clear();
                temporaryAllowUntil.clear();
                activeRollbacks.clear();
                mountedBlocks = 0L;
                teleportBlocks = 0L;
                dismountBlocks = 0L;
                collisionBlocks = 0L;
                sender.sendMessage("SurfaceGuard runtime state reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /surfaceguard <status|zone|relation|allow|snapshot|probe|reset>");
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
            sender.sendMessage("Usage: /surfaceguard relation [player] <enemy|truce>");
            return true;
        }

        if (target == null) {
            sender.sendMessage("Target player is not online.");
            return true;
        }
        try {
            Relation relation = Relation.valueOf(relationText.toUpperCase(Locale.ROOT));
            relations.put(target.getUniqueId(), relation);
            sender.sendMessage("SurfaceGuard relation for " + target.getName() + " set to " + relation);
        } catch (IllegalArgumentException exception) {
            sender.sendMessage("Relation must be ENEMY or TRUCE.");
        }
        return true;
    }

    private void openTelemetry() {
        if (!getConfig().getBoolean("telemetry.enabled", true)) {
            return;
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            telemetryPath = getDataFolder().toPath().resolve(
                "surface-guard-" + Instant.now().toString().replace(':', '-') + ".csv");
            telemetryWriter = Files.newBufferedWriter(telemetryPath,
                StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE);
            telemetryWriter.write("time,tick,event,player,vehicle,from_x,from_y,from_z,to_x,to_y,to_z,reason\n");
            telemetryWriter.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open SurfaceGuard telemetry: " + exception.getMessage());
            telemetryWriter = null;
            telemetryPath = null;
        }
    }

    private void telemetry(String event, Player player, Entity vehicle,
                           Location from, Location to, String reason) {
        if (telemetryWriter == null) {
            return;
        }
        Location safeFrom = from == null ? zeroLocation(player.getWorld()) : from;
        Location safeTo = to == null ? zeroLocation(player.getWorld()) : to;
        try {
            telemetryWriter.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s%n",
                Instant.now(), logicalTick, csv(event), csv(player.getName()),
                vehicle == null ? "none" : csv(vehicle.getType().toString()),
                safeFrom.getX(), safeFrom.getY(), safeFrom.getZ(),
                safeTo.getX(), safeTo.getY(), safeTo.getZ(), csv(reason)));
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
