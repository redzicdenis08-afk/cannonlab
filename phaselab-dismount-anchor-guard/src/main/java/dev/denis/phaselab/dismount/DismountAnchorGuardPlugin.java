package dev.denis.phaselab.dismount;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDismountEvent;
import org.bukkit.event.entity.EntityMountEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.BoundingBox;
import org.bukkit.util.Vector;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * Defensive dismount validator that keeps a distinct pre-mount escape anchor.
 *
 * Vehicle rollback coordinates and safe dismount coordinates are different
 * concepts. This module deliberately never replaces the pre-mount anchor with a
 * later boat-local position.
 */
public final class DismountAnchorGuardPlugin extends JavaPlugin implements Listener {
    private double minimumX;
    private double maximumX;
    private double collisionEpsilon;
    private int quarantineTicks;

    private long logicalTick;
    private long capturedMounts;
    private long correctedDismounts;

    private final Map<UUID, Location> lastClearOutsideLocations = new HashMap<>();
    private final Map<UUID, Location> preMountAnchors = new HashMap<>();
    private final Map<UUID, Long> quarantineUntil = new HashMap<>();

    @Override
    public void onEnable() {
        getConfig().addDefault("claim-zone.minimum-x", 0.0D);
        getConfig().addDefault("claim-zone.maximum-x", 255.999D);
        getConfig().addDefault("quarantine.ticks", 60);
        getConfig().addDefault("collision.epsilon", 0.001D);
        getConfig().options().copyDefaults(true);
        saveConfig();

        loadSettings();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, this::guardTick, 1L, 1L);
        getLogger().info("PhaseLab DismountAnchorGuard enabled: claimX=["
            + minimumX + "," + maximumX + "] quarantineTicks=" + quarantineTicks);
    }

    @Override
    public void onDisable() {
        lastClearOutsideLocations.clear();
        preMountAnchors.clear();
        quarantineUntil.clear();
    }

    private void loadSettings() {
        minimumX = getConfig().getDouble("claim-zone.minimum-x", 0.0D);
        maximumX = getConfig().getDouble("claim-zone.maximum-x", 255.999D);
        if (minimumX > maximumX) {
            double swap = minimumX;
            minimumX = maximumX;
            maximumX = swap;
        }
        quarantineTicks = Math.max(20, getConfig().getInt("quarantine.ticks", 60));
        collisionEpsilon = Math.max(0.0001D,
            getConfig().getDouble("collision.epsilon", 0.001D));
    }

    private void guardTick() {
        logicalTick++;
        for (Map.Entry<UUID, Long> entry : new ArrayList<>(quarantineUntil.entrySet())) {
            UUID playerId = entry.getKey();
            if (entry.getValue() < logicalTick) {
                quarantineUntil.remove(playerId);
                preMountAnchors.remove(playerId);
                continue;
            }

            Player player = Bukkit.getPlayer(playerId);
            Location anchor = preMountAnchors.get(playerId);
            if (player == null || !player.isOnline() || anchor == null) {
                continue;
            }
            if (isProtected(player.getLocation()) || overlapsSolid(player, player.getLocation())) {
                forceAnchor(player, anchor, "QUARANTINE_TICK");
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlayerMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        Location to = event.getTo();
        if (to == null || player.getVehicle() != null) {
            return;
        }
        if (!isProtected(to) && !overlapsSolid(player, to)) {
            lastClearOutsideLocations.put(player.getUniqueId(), to.clone());
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void onMount(EntityMountEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }

        Location anchor = lastClearOutsideLocations.get(player.getUniqueId());
        if (anchor == null) {
            Location current = player.getLocation();
            if (!isProtected(current) && !overlapsSolid(player, current)) {
                anchor = current.clone();
            }
        }
        if (anchor != null) {
            preMountAnchors.put(player.getUniqueId(), anchor.clone());
            capturedMounts++;
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDismount(EntityDismountEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }

        Location anchor = preMountAnchors.get(player.getUniqueId());
        if (anchor == null) {
            return;
        }
        quarantineUntil.put(player.getUniqueId(), logicalTick + quarantineTicks);
        Location finalAnchor = anchor.clone();

        for (long delay : new long[] {0L, 1L, 2L, 5L, 10L}) {
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (!player.isOnline()) {
                    return;
                }
                Location current = player.getLocation();
                if (isProtected(current) || overlapsSolid(player, current)) {
                    correctedDismounts++;
                    forceAnchor(player, finalAnchor, "DISMOUNT_VALIDATION");
                }
            }, delay);
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        UUID playerId = event.getPlayer().getUniqueId();
        lastClearOutsideLocations.remove(playerId);
        preMountAnchors.remove(playerId);
        quarantineUntil.remove(playerId);
    }

    private void forceAnchor(Player player, Location anchor, String reason) {
        player.leaveVehicle();
        player.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
        player.teleport(anchor, PlayerTeleportEvent.TeleportCause.PLUGIN);
        getLogger().warning("DismountAnchorGuard corrected " + player.getName()
            + " reason=" + reason + " anchor=" + format(anchor));
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

    private String format(Location location) {
        return String.format(Locale.ROOT, "%.3f,%.3f,%.3f",
            location.getX(), location.getY(), location.getZ());
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            sender.sendMessage(String.format(Locale.ROOT,
                "DismountAnchorGuard claimX=[%.3f,%.3f] tick=%d captured=%d corrected=%d anchors=%d quarantines=%d",
                minimumX, maximumX, logicalTick, capturedMounts, correctedDismounts,
                preMountAnchors.size(), quarantineUntil.size()));
            return true;
        }

        if (args[0].equalsIgnoreCase("zone")) {
            if (args.length != 3) {
                sender.sendMessage("Usage: /dismountguard zone <minimum-x> <maximum-x>");
                return true;
            }
            try {
                double first = Double.parseDouble(args[1]);
                double second = Double.parseDouble(args[2]);
                minimumX = Math.min(first, second);
                maximumX = Math.max(first, second);
                sender.sendMessage("DismountAnchorGuard zone set to X=["
                    + minimumX + "," + maximumX + "]");
            } catch (NumberFormatException exception) {
                sender.sendMessage("Zone coordinates must be numbers.");
            }
            return true;
        }

        if (args[0].equalsIgnoreCase("reset")) {
            lastClearOutsideLocations.clear();
            preMountAnchors.clear();
            quarantineUntil.clear();
            capturedMounts = 0L;
            correctedDismounts = 0L;
            sender.sendMessage("DismountAnchorGuard runtime state reset.");
            return true;
        }

        sender.sendMessage("Usage: /dismountguard <status|zone|reset>");
        return true;
    }
}
