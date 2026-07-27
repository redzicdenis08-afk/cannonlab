package dev.denis.phaselab.dismount;

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
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.Vector;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * Observes the server-selected player position after a real client dismount.
 * STRICT mode is a defensive patch: when a player dismounts from an outside
 * vehicle into the protected X interval, the player is repeatedly restored to
 * the pre-dismount position.
 */
public final class DismountLabPlugin extends JavaPlugin implements Listener {
    private enum Mode {
        OBSERVE,
        STRICT
    }

    private record Pending(
        UUID playerId,
        UUID vehicleId,
        String vehicleType,
        Location playerBefore,
        Location vehicleBefore,
        boolean vehicleStartedInClaim,
        long startedTick
    ) {
    }

    private Mode mode;
    private double minimumX;
    private double maximumX;
    private int rollbackRepetitions;
    private int rollbackSpacingTicks;
    private long logicalTick;

    private final Map<UUID, Pending> pending = new HashMap<>();
    private BufferedWriter telemetryWriter;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        loadSettings();
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> logicalTick++, 1L, 1L);
        openTelemetry();
        getLogger().info("PhaseLab DismountLab enabled: mode=" + mode
            + " claimX=[" + minimumX + "," + maximumX + "]");
    }

    @Override
    public void onDisable() {
        closeTelemetry();
        pending.clear();
    }

    private void loadSettings() {
        mode = parseMode(getConfig().getString("mode", "OBSERVE"));
        minimumX = getConfig().getDouble("claim-zone.minimum-x", 0.0D);
        maximumX = getConfig().getDouble("claim-zone.maximum-x", 15.999D);
        if (minimumX > maximumX) {
            double swap = minimumX;
            minimumX = maximumX;
            maximumX = swap;
        }
        rollbackRepetitions = Math.max(1,
            getConfig().getInt("rollback.repetitions", 3));
        rollbackSpacingTicks = Math.max(1,
            getConfig().getInt("rollback.spacing-ticks", 1));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onDismount(EntityDismountEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }

        Entity vehicle = event.getDismounted();
        Pending attempt = new Pending(
            player.getUniqueId(),
            vehicle.getUniqueId(),
            vehicle.getType().toString(),
            player.getLocation().clone(),
            vehicle.getLocation().clone(),
            isClaim(vehicle.getLocation()),
            logicalTick
        );
        pending.put(player.getUniqueId(), attempt);
        telemetry("DISMOUNT_EVENT", attempt, player.getLocation(),
            vehicle.getLocation(), event.isCancelled(), false, "EVENT");

        int[] observationDelays = {0, 1, 2, 5};
        for (int delay : observationDelays) {
            Bukkit.getScheduler().runTaskLater(this,
                () -> observe(player.getUniqueId(), delay), delay);
        }
    }

    private void observe(UUID playerId, int delay) {
        Pending attempt = pending.get(playerId);
        Player player = Bukkit.getPlayer(playerId);
        if (attempt == null || player == null || !player.isOnline()) {
            return;
        }

        Entity vehicle = Bukkit.getEntity(attempt.vehicleId());
        Location playerNow = player.getLocation().clone();
        Location vehicleNow = vehicle == null
            ? attempt.vehicleBefore().clone()
            : vehicle.getLocation().clone();

        boolean playerInside = isClaim(playerNow);
        boolean outsideVehicleToInsidePlayer = !attempt.vehicleStartedInClaim()
            && playerInside;
        telemetry("POST_DISMOUNT_T" + delay, attempt, playerNow, vehicleNow,
            false, outsideVehicleToInsidePlayer,
            outsideVehicleToInsidePlayer ? "OUTSIDE_TO_INSIDE" : "NO_CROSS");

        if (mode == Mode.STRICT && outsideVehicleToInsidePlayer) {
            defensiveRollback(player, attempt);
        }

        if (delay == 5) {
            pending.remove(playerId);
        }
    }

    private void defensiveRollback(Player player, Pending attempt) {
        for (int iteration = 0; iteration < rollbackRepetitions; iteration++) {
            long delay = (long) iteration * rollbackSpacingTicks;
            Bukkit.getScheduler().runTaskLater(this, () -> {
                if (!player.isOnline()) {
                    return;
                }
                player.leaveVehicle();
                player.setVelocity(new Vector());
                player.teleport(attempt.playerBefore());
                Entity vehicle = Bukkit.getEntity(attempt.vehicleId());
                telemetry("STRICT_DISMOUNT_ROLLBACK", attempt,
                    player.getLocation(),
                    vehicle == null ? attempt.vehicleBefore() : vehicle.getLocation(),
                    false, true, "ROLLBACK");
            }, delay);
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
            sender.sendMessage("DismountLab mode=" + mode
                + " claimX=[" + minimumX + "," + maximumX + "]"
                + " pending=" + pending.size()
                + " telemetry=" + (telemetryPath == null ? "disabled" : telemetryPath));
            return true;
        }

        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "mode" -> {
                if (args.length != 2) {
                    sender.sendMessage("Usage: /dismountlab mode <observe|strict>");
                    return true;
                }
                try {
                    mode = parseMode(args[1]);
                    getConfig().set("mode", mode.name());
                    saveConfig();
                    sender.sendMessage("DismountLab mode set to " + mode);
                } catch (IllegalArgumentException exception) {
                    sender.sendMessage(exception.getMessage());
                }
                return true;
            }
            case "zone" -> {
                if (args.length != 3) {
                    sender.sendMessage("Usage: /dismountlab zone <minimum-x> <maximum-x>");
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
                    sender.sendMessage("Dismount zone set to X=[" + minimumX + "," + maximumX + "]");
                } catch (NumberFormatException exception) {
                    sender.sendMessage("Both zone values must be numbers.");
                }
                return true;
            }
            case "reset" -> {
                pending.clear();
                sender.sendMessage("DismountLab runtime state reset.");
                return true;
            }
            default -> {
                sender.sendMessage("Usage: /dismountlab <status|mode|zone|reset>");
                return true;
            }
        }
    }

    private Mode parseMode(String text) {
        try {
            return Mode.valueOf(text.toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Mode must be OBSERVE or STRICT.");
        }
    }

    private void openTelemetry() {
        if (!getConfig().getBoolean("telemetry.enabled", true)) {
            return;
        }
        try {
            Files.createDirectories(getDataFolder().toPath());
            telemetryPath = getDataFolder().toPath().resolve(
                "dismount-" + Instant.now().toString().replace(':', '-') + ".csv");
            telemetryWriter = Files.newBufferedWriter(
                telemetryPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            telemetryWriter.write(
                "time,tick,event,mode,player,vehicle_type,vehicle_started_claim,event_cancelled,crossed,player_before_x,player_before_y,player_before_z,vehicle_before_x,vehicle_before_y,vehicle_before_z,player_now_x,player_now_y,player_now_z,vehicle_now_x,vehicle_now_y,vehicle_now_z,action\n");
            telemetryWriter.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open dismount telemetry: " + exception.getMessage());
            telemetryWriter = null;
            telemetryPath = null;
        }
    }

    private void telemetry(
        String event,
        Pending attempt,
        Location playerNow,
        Location vehicleNow,
        boolean eventCancelled,
        boolean crossed,
        String action
    ) {
        if (telemetryWriter == null) {
            return;
        }
        Player player = Bukkit.getPlayer(attempt.playerId());
        String playerName = player == null ? attempt.playerId().toString() : player.getName();
        try {
            telemetryWriter.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%s,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s%n",
                Instant.now(),
                logicalTick,
                event,
                mode,
                csv(playerName),
                attempt.vehicleType(),
                attempt.vehicleStartedInClaim(),
                eventCancelled,
                crossed,
                attempt.playerBefore().getX(),
                attempt.playerBefore().getY(),
                attempt.playerBefore().getZ(),
                attempt.vehicleBefore().getX(),
                attempt.vehicleBefore().getY(),
                attempt.vehicleBefore().getZ(),
                playerNow.getX(), playerNow.getY(), playerNow.getZ(),
                vehicleNow.getX(), vehicleNow.getY(), vehicleNow.getZ(),
                csv(action)
            ));
            telemetryWriter.flush();
        } catch (IOException ignored) {
        }
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
