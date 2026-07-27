package dev.denis.phaselab.input;

import org.bukkit.Bukkit;
import org.bukkit.Input;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDismountEvent;
import org.bukkit.event.player.PlayerInputEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerToggleSneakEvent;
import org.bukkit.event.vehicle.VehicleExitEvent;
import org.bukkit.plugin.java.JavaPlugin;

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
 * Server-side truth recorder for mounted input packets.
 *
 * It answers whether a translated 1.21.11 client actually delivered sneak/jump,
 * whether Bukkit changed the player's sneak state, and whether the passenger
 * relation was removed. It does not alter or cancel any event.
 */
public final class InputProbePlugin extends JavaPlugin implements Listener {
    private final Map<UUID, String> activeLabels = new HashMap<>();
    private long tick;
    private BufferedWriter writer;
    private Path telemetryPath;

    @Override
    public void onEnable() {
        Bukkit.getPluginManager().registerEvents(this, this);
        Bukkit.getScheduler().runTaskTimer(this, () -> tick++, 1L, 1L);
        openTelemetry();
        getLogger().info("PhaseLab InputProbe enabled");
    }

    @Override
    public void onDisable() {
        activeLabels.clear();
        closeTelemetry();
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onInput(PlayerInputEvent event) {
        Player player = event.getPlayer();
        if (!activeLabels.containsKey(player.getUniqueId())) {
            return;
        }
        Input input = event.getInput();
        record("PLAYER_INPUT", player, player.getVehicle(),
            String.format(Locale.ROOT,
                "forward=%s;backward=%s;left=%s;right=%s;jump=%s;sneak=%s;sprint=%s",
                input.isForward(), input.isBackward(), input.isLeft(), input.isRight(),
                input.isJump(), input.isSneak(), input.isSprint()));
        snapshotLater(player, 0, "POST_INPUT_T0");
        snapshotLater(player, 1, "POST_INPUT_T1");
        snapshotLater(player, 2, "POST_INPUT_T2");
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onToggleSneak(PlayerToggleSneakEvent event) {
        Player player = event.getPlayer();
        if (!activeLabels.containsKey(player.getUniqueId())) {
            return;
        }
        record("TOGGLE_SNEAK", player, player.getVehicle(),
            "target=" + event.isSneaking() + ";cancelled=" + event.isCancelled());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onDismount(EntityDismountEvent event) {
        if (!(event.getEntity() instanceof Player player)
            || !activeLabels.containsKey(player.getUniqueId())) {
            return;
        }
        record("ENTITY_DISMOUNT", player, event.getDismounted(),
            "cancelled=" + event.isCancelled() + ";cancellable=" + event.isCancellable());
        snapshotLater(player, 0, "POST_DISMOUNT_T0");
        snapshotLater(player, 1, "POST_DISMOUNT_T1");
        snapshotLater(player, 2, "POST_DISMOUNT_T2");
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleExit(VehicleExitEvent event) {
        if (!(event.getExited() instanceof Player player)
            || !activeLabels.containsKey(player.getUniqueId())) {
            return;
        }
        record("VEHICLE_EXIT", player, event.getVehicle(),
            "cancelled=" + event.isCancelled());
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        activeLabels.remove(event.getPlayer().getUniqueId());
    }

    private void snapshotLater(Player player, int delay, String event) {
        Bukkit.getScheduler().runTaskLater(this, () -> {
            if (!player.isOnline() || !activeLabels.containsKey(player.getUniqueId())) {
                return;
            }
            Input current = player.getCurrentInput();
            record(event, player, player.getVehicle(),
                String.format(Locale.ROOT,
                    "sneakingState=%s;inputJump=%s;inputSneak=%s",
                    player.isSneaking(), current.isJump(), current.isSneak()));
        }, delay);
    }

    private void record(String event, Player player, Entity vehicle, String detail) {
        if (writer == null) {
            return;
        }
        String label = activeLabels.getOrDefault(player.getUniqueId(), "none");
        try {
            writer.write(String.format(Locale.ROOT,
                "%s,%d,%s,%s,%s,%s,%s,%.6f,%.6f,%.6f,%s%n",
                Instant.now(),
                tick,
                csv(label),
                event,
                csv(player.getName()),
                vehicle == null ? "none" : vehicle.getType(),
                vehicle == null ? "none" : vehicle.getUniqueId(),
                player.getLocation().getX(),
                player.getLocation().getY(),
                player.getLocation().getZ(),
                csv(detail)
            ));
            writer.flush();
        } catch (IOException ignored) {
        }
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage("Run this command as the test player.");
            return true;
        }
        if (args.length == 0 || args[0].equalsIgnoreCase("status")) {
            player.sendMessage("InputProbe active=" + activeLabels.containsKey(player.getUniqueId())
                + " label=" + activeLabels.getOrDefault(player.getUniqueId(), "none")
                + " vehicle=" + (player.getVehicle() == null ? "none" : player.getVehicle().getType())
                + " telemetry=" + telemetryPath);
            return true;
        }
        switch (args[0].toLowerCase(Locale.ROOT)) {
            case "start", "mark" -> {
                String testLabel = args.length >= 2 ? args[1] : "trial-" + Instant.now().toEpochMilli();
                activeLabels.put(player.getUniqueId(), testLabel);
                record("PROBE_START", player, player.getVehicle(), "label=" + testLabel);
                player.sendMessage("InputProbe started: " + testLabel);
                return true;
            }
            case "stop" -> {
                record("PROBE_STOP", player, player.getVehicle(), "stopped=true");
                activeLabels.remove(player.getUniqueId());
                player.sendMessage("InputProbe stopped.");
                return true;
            }
            default -> {
                player.sendMessage("Usage: /inputlab <status|start [label]|mark [label]|stop>");
                return true;
            }
        }
    }

    private void openTelemetry() {
        try {
            Files.createDirectories(getDataFolder().toPath());
            telemetryPath = getDataFolder().toPath().resolve(
                "input-probe-" + Instant.now().toString().replace(':', '-') + ".csv");
            writer = Files.newBufferedWriter(
                telemetryPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            writer.write("time,tick,label,event,player,vehicle,vehicle_uuid,x,y,z,detail\n");
            writer.flush();
        } catch (IOException exception) {
            getLogger().warning("Unable to open input telemetry: " + exception.getMessage());
            writer = null;
            telemetryPath = null;
        }
    }

    private String csv(String value) {
        return value == null ? "" : value.replace(',', ';').replace('\n', ' ').replace('\r', ' ');
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
