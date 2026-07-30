package dev.denis.phaselab.server;

import org.bukkit.Bukkit;
import org.bukkit.FluidCollisionMode;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.messaging.PluginMessageListener;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;
import org.jetbrains.annotations.NotNull;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public final class PhaseLabServerPlugin extends JavaPlugin implements PluginMessageListener, CommandExecutor, Listener {
    private static final String CHANNEL = "phaselab:control";
    private static final Set<String> SCENARIOS = Set.of(
        "PRESS_FORWARD",
        "PULSE_FORWARD",
        "DISMOUNT_EDGE",
        "BRAKE_RELEASE"
    );

    private final Map<UUID, Session> sessions = new ConcurrentHashMap<>();

    @Override
    public void onEnable() {
        saveDefaultConfig();
        getServer().getMessenger().registerOutgoingPluginChannel(this, CHANNEL);
        getServer().getMessenger().registerIncomingPluginChannel(this, CHANNEL, this);
        getServer().getPluginManager().registerEvents(this, this);
        if (getCommand("phaselab") != null) {
            getCommand("phaselab").setExecutor(this);
        }
        getServer().getScheduler().runTaskTimer(this, this::tickSessions, 1L, 1L);
        getLogger().info("PhaseLab Server v5.1 active. Mount a test vehicle, face the wall, and run /phaselab quickstart.");
    }

    @Override
    public void onDisable() {
        for (Session session : new ArrayList<>(sessions.values())) {
            if (session.running) {
                rollback(session);
            }
        }
        sessions.clear();
        getServer().getMessenger().unregisterIncomingPluginChannel(this, CHANNEL, this);
        getServer().getMessenger().unregisterOutgoingPluginChannel(this, CHANNEL);
    }

    @Override
    public boolean onCommand(
        @NotNull CommandSender sender,
        @NotNull Command command,
        @NotNull String label,
        @NotNull String[] args
    ) {
        if (!sender.hasPermission("phaselab.admin")) {
            sender.sendMessage("[PhaseLab] No permission.");
            return true;
        }

        String sub = args.length == 0 ? "help" : args[0].toLowerCase(Locale.ROOT);
        switch (sub) {
            case "quickstart" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                int seconds = getConfig().getInt("authorization-seconds", 1800);
                if (args.length >= 2) {
                    try {
                        seconds = Integer.parseInt(args[1]);
                    } catch (NumberFormatException exception) {
                        sender.sendMessage("[PhaseLab] Seconds must be a number.");
                        return true;
                    }
                }
                seconds = Math.max(60, Math.min(1800, seconds));
                quickstart(player, seconds);
            }
            case "status" -> sendStatus(sender);
            case "abort" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                Session session = sessions.get(player.getUniqueId());
                if (session == null) {
                    sender.sendMessage("[PhaseLab] No active authorization.");
                } else {
                    finish(session, "ABORTED", "operator_abort", true);
                    sender.sendMessage("[PhaseLab] Test aborted and rolled back.");
                }
            }
            default -> sender.sendMessage("[PhaseLab] Usage: /phaselab <quickstart [seconds]|status|abort>");
        }
        return true;
    }

    private void quickstart(Player player, int seconds) {
        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            player.sendMessage("[PhaseLab] Mount the test boat/vehicle first.");
            return;
        }

        Barrier barrier = detectBarrier(player, vehicle);
        if (barrier == null) {
            player.sendMessage("[PhaseLab] Face a solid wall within 16 blocks, then run /phaselab quickstart again.");
            return;
        }

        Session old = sessions.get(player.getUniqueId());
        if (old != null && old.running) {
            finish(old, "ABORTED", "replaced_by_quickstart", true);
        }

        Location vehicleLocation = vehicle.getLocation();
        Block hit = barrier.block;
        int minX = Math.min(vehicleLocation.getBlockX(), hit.getX()) - 12;
        int maxX = Math.max(vehicleLocation.getBlockX(), hit.getX()) + 12;
        int minY = Math.min(vehicleLocation.getBlockY(), hit.getY()) - 6;
        int maxY = Math.max(vehicleLocation.getBlockY(), hit.getY()) + 8;
        int minZ = Math.min(vehicleLocation.getBlockZ(), hit.getZ()) - 12;
        int maxZ = Math.max(vehicleLocation.getBlockZ(), hit.getZ()) + 12;

        Region region = new Region(
            player.getWorld().getName(),
            minX, minY, minZ,
            maxX, maxY, maxZ,
            barrier.axis,
            barrier.coordinate
        );
        long expires = System.currentTimeMillis() + seconds * 1000L;
        String nonce = UUID.randomUUID().toString();
        Session session = new Session(player, nonce, expires, region);
        sessions.put(player.getUniqueId(), session);

        send(player, String.join("|",
            "AUTH",
            "1",
            player.getUniqueId().toString(),
            Long.toString(expires),
            Integer.toString(region.minX),
            Integer.toString(region.minY),
            Integer.toString(region.minZ),
            Integer.toString(region.maxX),
            Integer.toString(region.maxY),
            Integer.toString(region.maxZ),
            nonce
        ));

        player.sendMessage("[PhaseLab] READY for " + seconds + " seconds. Wall=" + region.axis + "="
            + String.format(Locale.ROOT, "%.2f", region.barrier) + ". Press F6 to select and F12 to run.");
        writeReport(session, "AUTHORIZED", "quickstart");
    }

    private Barrier detectBarrier(Player player, Entity vehicle) {
        Vector direction = player.getLocation().getDirection().setY(0.0D);
        if (direction.lengthSquared() < 0.0001D) {
            return null;
        }
        direction.normalize();
        World world = player.getWorld();
        Location origin = vehicle.getLocation();
        Block hit = null;

        double[] heights = {0.45D, 1.20D, 1.95D};
        for (double height : heights) {
            Location start = origin.clone().add(0.0D, height, 0.0D);
            RayTraceResult result = world.rayTraceBlocks(
                start,
                direction,
                16.0D,
                FluidCollisionMode.NEVER,
                true
            );
            if (result != null && result.getHitBlock() != null) {
                hit = result.getHitBlock();
                break;
            }
        }
        if (hit == null) {
            return null;
        }

        boolean xAxis = Math.abs(direction.getX()) >= Math.abs(direction.getZ());
        if (xAxis) {
            double coordinate = direction.getX() >= 0.0D ? hit.getX() : hit.getX() + 1.0D;
            return new Barrier("X", coordinate, hit);
        }
        double coordinate = direction.getZ() >= 0.0D ? hit.getZ() : hit.getZ() + 1.0D;
        return new Barrier("Z", coordinate, hit);
    }

    private void sendStatus(CommandSender sender) {
        sender.sendMessage("[PhaseLab] v5.1 sessions=" + sessions.size());
        if (sender instanceof Player player) {
            Session session = sessions.get(player.getUniqueId());
            if (session == null) {
                sender.sendMessage("[PhaseLab] You are not authorized. Mount, face wall, run /phaselab quickstart.");
            } else {
                long seconds = Math.max(0L, (session.expiresEpochMs - System.currentTimeMillis()) / 1000L);
                sender.sendMessage("[PhaseLab] authorized=" + seconds + "s running=" + session.running
                    + " scenario=" + safe(session.scenario)
                    + " barrier=" + session.region.axis + "=" + session.region.barrier);
            }
        }
    }

    @Override
    public void onPluginMessageReceived(@NotNull String channel, @NotNull Player player, byte @NotNull [] bytes) {
        if (!CHANNEL.equals(channel)) {
            return;
        }

        String message;
        try {
            message = decodeUtf(bytes);
        } catch (RuntimeException exception) {
            send(player, "ERROR|malformed_payload");
            return;
        }

        String[] parts = message.split("\\|", -1);
        if (parts.length < 2) {
            send(player, "ERROR|malformed_command");
            return;
        }

        Session session = sessions.get(player.getUniqueId());
        if (!validSession(session, player, parts[1])) {
            send(player, "LOCKED|run_quickstart_again");
            return;
        }

        switch (parts[0]) {
            case "READY" -> {
                session.clientReady = true;
                send(player, "ACK|" + session.nonce + "|READY|" + value(parts, 2));
            }
            case "START" -> {
                if (parts.length < 3) {
                    send(player, "ERROR|missing_scenario");
                } else {
                    start(session, parts[2]);
                }
            }
            case "FINISH" -> {
                if (session.running) {
                    finish(session, classify(session), detail(session, "client_finish"), true);
                }
            }
            case "ABORT" -> finish(session, "ABORTED", clean(value(parts, 2)), true);
            default -> send(player, "ERROR|unknown_command");
        }
    }

    private boolean validSession(Session session, Player player, String suppliedNonce) {
        return session != null
            && session.playerId.equals(player.getUniqueId())
            && session.nonce.equals(suppliedNonce)
            && System.currentTimeMillis() < session.expiresEpochMs;
    }

    private void start(Session session, String scenario) {
        Player player = Bukkit.getPlayer(session.playerId);
        if (player == null || !player.isOnline()) {
            sessions.remove(session.playerId);
            return;
        }
        if (!SCENARIOS.contains(scenario)) {
            send(player, "ERROR|scenario_not_allowed");
            return;
        }
        if (!session.clientReady) {
            send(player, "ERROR|client_not_ready_run_quickstart_again");
            return;
        }
        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            send(player, "ERROR|mount_required");
            return;
        }
        if (!session.region.contains(player.getLocation()) || !session.region.contains(vehicle.getLocation())) {
            send(player, "LOCKED|outside_quickstart_region");
            return;
        }

        session.scenario = scenario;
        session.running = true;
        session.ticks = 0;
        session.playerStart = player.getLocation().clone();
        session.vehicle = vehicle;
        session.vehicleStart = vehicle.getLocation().clone();
        session.direction = session.region.coordinate(session.vehicleStart) <= session.region.barrier ? 1.0D : -1.0D;
        session.maxPlayerProgress = Double.NEGATIVE_INFINITY;
        session.maxVehicleProgress = Double.NEGATIVE_INFINITY;
        session.persistentCrossingTicks = 0;
        session.dismountedTick = -1;
        session.startedAt = Instant.now();

        send(player, "ACK|" + session.nonce + "|START|" + scenario);
        writeReport(session, "STARTED", "scenario_started");
    }

    private void tickSessions() {
        for (Session session : new ArrayList<>(sessions.values())) {
            Player player = Bukkit.getPlayer(session.playerId);
            if (player == null || !player.isOnline()) {
                sessions.remove(session.playerId);
                continue;
            }

            if (System.currentTimeMillis() >= session.expiresEpochMs) {
                if (session.running) {
                    finish(session, "EXPIRED", "authorization_expired", true);
                }
                sessions.remove(session.playerId);
                continue;
            }
            if (!session.running) {
                continue;
            }

            session.ticks++;
            Entity vehicle = session.vehicle;
            if (vehicle == null || !vehicle.isValid()) {
                finish(session, "SAFETY_ABORT", "vehicle_missing", true);
                continue;
            }

            Location playerLocation = player.getLocation();
            Location vehicleLocation = vehicle.getLocation();
            if (!session.region.contains(playerLocation) || !session.region.contains(vehicleLocation)) {
                finish(session, "SAFETY_ABORT", "left_quickstart_region", true);
                continue;
            }

            double maxDistance = getConfig().getDouble("max-displacement-blocks", 24.0D);
            if (distance(playerLocation, session.playerStart) > maxDistance
                || distance(vehicleLocation, session.vehicleStart) > maxDistance) {
                finish(session, "SAFETY_ABORT", "displacement_cap", true);
                continue;
            }

            double playerProgress = session.direction
                * (session.region.coordinate(playerLocation) - session.region.barrier);
            double vehicleProgress = session.direction
                * (session.region.coordinate(vehicleLocation) - session.region.barrier);
            session.maxPlayerProgress = Math.max(session.maxPlayerProgress, playerProgress);
            session.maxVehicleProgress = Math.max(session.maxVehicleProgress, vehicleProgress);

            double threshold = getConfig().getDouble("penetration-threshold-blocks", 0.35D);
            if (vehicleProgress > threshold) {
                session.persistentCrossingTicks++;
            } else {
                session.persistentCrossingTicks = 0;
            }

            if (session.dismountedTick < 0 && player.getVehicle() == null) {
                session.dismountedTick = session.ticks;
            }

            int required = getConfig().getInt("required-persistent-crossing-ticks", 5);
            if (session.persistentCrossingTicks >= required) {
                finish(session, "REPRODUCED", detail(session, "persistent_crossing"), true);
                continue;
            }

            int maxTicks = getConfig().getInt("max-runtime-ticks", 240);
            if (session.ticks >= maxTicks) {
                finish(session, classify(session), detail(session, "server_timeout"), true);
            }
        }
    }

    private String classify(Session session) {
        int required = getConfig().getInt("required-persistent-crossing-ticks", 5);
        double threshold = getConfig().getDouble("penetration-threshold-blocks", 0.35D);
        if (session.persistentCrossingTicks >= required) {
            return "REPRODUCED";
        }
        if (session.maxVehicleProgress > threshold) {
            return "TRANSIENT_CROSSING";
        }
        if (session.dismountedTick >= 0) {
            return "DISMOUNT_EDGE".equals(session.scenario) ? "EXPECTED_DISMOUNT" : "FORCED_DISMOUNT";
        }
        return "BLOCKED";
    }

    private String detail(Session session, String reason) {
        return clean("reason=" + reason
            + ";scenario=" + safe(session.scenario)
            + ";ticks=" + session.ticks
            + ";vehicle_progress=" + decimal(session.maxVehicleProgress)
            + ";player_progress=" + decimal(session.maxPlayerProgress)
            + ";dismount_tick=" + session.dismountedTick);
    }

    private void finish(Session session, String verdict, String detail, boolean restore) {
        Player player = Bukkit.getPlayer(session.playerId);
        boolean wasRunning = session.running;
        if (restore && wasRunning) {
            rollback(session);
        }
        session.running = false;
        writeReport(session, verdict, detail);
        if (player != null && player.isOnline()) {
            send(player, "RESULT|" + session.nonce + "|" + clean(verdict) + "|" + clean(detail));
        }
        session.ticks = 0;
        session.scenario = "NONE";
        session.playerStart = null;
        session.vehicleStart = null;
        session.vehicle = null;
        session.persistentCrossingTicks = 0;
        session.dismountedTick = -1;
    }

    private void rollback(Session session) {
        Player player = Bukkit.getPlayer(session.playerId);
        if (player == null || !player.isOnline() || session.playerStart == null) {
            return;
        }

        Entity vehicle = session.vehicle;
        if (vehicle != null && vehicle.isValid() && session.vehicleStart != null) {
            vehicle.eject();
            vehicle.teleport(session.vehicleStart);
        }
        player.teleport(session.playerStart);

        if (vehicle != null && vehicle.isValid()) {
            Bukkit.getScheduler().runTask(this, () -> {
                Player current = Bukkit.getPlayer(session.playerId);
                if (current != null && current.isOnline() && vehicle.isValid()) {
                    vehicle.addPassenger(current);
                }
            });
        }
    }

    private void writeReport(Session session, String verdict, String detail) {
        Path reports = getDataFolder().toPath().resolve("reports");
        Path file = reports.resolve(LocalDate.now() + ".jsonl");
        String line = "{"
            + "\"timestamp\":\"" + json(Instant.now().toString()) + "\","
            + "\"player_uuid\":\"" + json(session.playerId.toString()) + "\","
            + "\"player_name\":\"" + json(session.playerName) + "\","
            + "\"scenario\":\"" + json(safe(session.scenario)) + "\","
            + "\"verdict\":\"" + json(verdict) + "\","
            + "\"detail\":\"" + json(detail) + "\","
            + "\"ticks\":" + session.ticks + ","
            + "\"barrier_axis\":\"" + json(session.region.axis) + "\","
            + "\"barrier_coordinate\":" + decimal(session.region.barrier) + ","
            + "\"max_vehicle_progress\":" + decimal(session.maxVehicleProgress) + ","
            + "\"max_player_progress\":" + decimal(session.maxPlayerProgress)
            + "}\n";
        try {
            Files.createDirectories(reports);
            Files.writeString(
                file,
                line,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.APPEND,
                StandardOpenOption.WRITE
            );
        } catch (IOException exception) {
            getLogger().warning("Could not write report: " + exception.getMessage());
        }
    }

    private void send(Player player, String message) {
        player.sendPluginMessage(this, CHANNEL, encodeUtf(message));
    }

    private static byte[] encodeUtf(String value) {
        byte[] utf8 = value.getBytes(StandardCharsets.UTF_8);
        ByteArrayOutputStream output = new ByteArrayOutputStream(utf8.length + 5);
        writeVarInt(output, utf8.length);
        output.writeBytes(utf8);
        return output.toByteArray();
    }

    private static String decodeUtf(byte[] bytes) {
        int[] cursor = {0};
        int length = readVarInt(bytes, cursor);
        if (length < 0 || length > 32767 || cursor[0] + length > bytes.length) {
            throw new IllegalArgumentException("invalid utf length");
        }
        return new String(bytes, cursor[0], length, StandardCharsets.UTF_8);
    }

    private static void writeVarInt(ByteArrayOutputStream output, int value) {
        while ((value & -128) != 0) {
            output.write(value & 127 | 128);
            value >>>= 7;
        }
        output.write(value);
    }

    private static int readVarInt(byte[] bytes, int[] cursor) {
        int value = 0;
        int position = 0;
        while (true) {
            if (cursor[0] >= bytes.length || position >= 32) {
                throw new IllegalArgumentException("invalid varint");
            }
            int current = bytes[cursor[0]++] & 0xFF;
            value |= (current & 0x7F) << position;
            if ((current & 0x80) == 0) {
                return value;
            }
            position += 7;
        }
    }

    private static double distance(Location first, Location second) {
        if (first == null || second == null || first.getWorld() != second.getWorld()) {
            return Double.POSITIVE_INFINITY;
        }
        return first.distance(second);
    }

    private Player requirePlayer(CommandSender sender) {
        if (sender instanceof Player player) {
            return player;
        }
        sender.sendMessage("[PhaseLab] This command requires a player.");
        return null;
    }

    private static String value(String[] parts, int index) {
        return index >= 0 && index < parts.length ? parts[index] : "";
    }

    private static String clean(String value) {
        return value == null ? "" : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static String safe(String value) {
        return value == null ? "NONE" : value;
    }

    private static String json(String value) {
        return clean(value).replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static String decimal(double value) {
        if (!Double.isFinite(value)) {
            return "0.000000";
        }
        return String.format(Locale.ROOT, "%.6f", value);
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        Session session = sessions.remove(event.getPlayer().getUniqueId());
        if (session != null && session.running) {
            rollback(session);
        }
    }

    private record Barrier(String axis, double coordinate, Block block) {
    }

    private record Region(
        String worldName,
        int minX,
        int minY,
        int minZ,
        int maxX,
        int maxY,
        int maxZ,
        String axis,
        double barrier
    ) {
        boolean contains(Location location) {
            if (location == null || location.getWorld() == null || !worldName.equals(location.getWorld().getName())) {
                return false;
            }
            double x = location.getX();
            double y = location.getY();
            double z = location.getZ();
            return x >= minX && x <= maxX + 1.0D
                && y >= minY && y <= maxY + 1.0D
                && z >= minZ && z <= maxZ + 1.0D;
        }

        double coordinate(Location location) {
            return "X".equals(axis) ? location.getX() : location.getZ();
        }
    }

    private static final class Session {
        private final UUID playerId;
        private final String playerName;
        private final String nonce;
        private final long expiresEpochMs;
        private final Region region;
        private boolean clientReady;
        private boolean running;
        private String scenario = "NONE";
        private int ticks;
        private Location playerStart;
        private Location vehicleStart;
        private Entity vehicle;
        private double direction;
        private double maxPlayerProgress = Double.NEGATIVE_INFINITY;
        private double maxVehicleProgress = Double.NEGATIVE_INFINITY;
        private int persistentCrossingTicks;
        private int dismountedTick = -1;
        private Instant startedAt;

        private Session(Player player, String nonce, long expiresEpochMs, Region region) {
            this.playerId = player.getUniqueId();
            this.playerName = player.getName();
            this.nonce = nonce;
            this.expiresEpochMs = expiresEpochMs;
            this.region = region;
        }
    }
}
