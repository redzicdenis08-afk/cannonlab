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
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.messaging.PluginMessageListener;
import org.bukkit.util.BoundingBox;
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

/**
 * Server-authoritative PhaseLab campaign referee.
 *
 * This plugin does not disable or bypass anti-cheat. Grim/NCE, claim checks,
 * proxy handling, and the rest of the live test stack remain active. The plugin
 * only authorizes a bounded lab session, observes server state, records verdicts,
 * and restores the player/vehicle after every case.
 */
public final class PhaseLabServerPlugin extends JavaPlugin implements PluginMessageListener, CommandExecutor, Listener {
    private static final String VERSION = "6.0.0";
    private static final String CHANNEL = "phaselab:control";
    private static final Set<String> SCENARIOS = Set.of(
        "PRESS_FORWARD",
        "PULSE_FORWARD",
        "FORWARD_LEFT",
        "FORWARD_RIGHT",
        "BRAKE_RELEASE",
        "FORWARD_BACK_PULSE",
        "DISMOUNT_EDGE",
        "IDLE_CONTROL"
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
        getLogger().info("PhaseLab Server v" + VERSION + " active. Grim/NCE remain enabled. Mount, face wall, /phaselab quickstart.");
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
                quickstart(player, Math.max(60, Math.min(1800, seconds)));
            }
            case "status" -> sendStatus(sender);
            case "abort" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                Session session = sessions.get(player.getUniqueId());
                if (session == null) {
                    sender.sendMessage("[PhaseLab] No active lab session.");
                } else {
                    finish(session, "ABORTED", "operator_abort", true);
                    sender.sendMessage("[PhaseLab] Active case aborted and rolled back.");
                }
            }
            default -> sender.sendMessage("[PhaseLab] Usage: /phaselab <quickstart [seconds]|status|abort>");
        }
        return true;
    }

    private void quickstart(Player player, int seconds) {
        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            player.sendMessage("[PhaseLab] Mount the lab boat/vehicle first.");
            return;
        }

        Barrier barrier = detectBarrier(player, vehicle);
        if (barrier == null) {
            player.sendMessage("[PhaseLab] Face a solid wall within 16 blocks, then run /phaselab quickstart again.");
            return;
        }

        Session previous = sessions.remove(player.getUniqueId());
        if (previous != null && previous.running) {
            finish(previous, "ABORTED", "replaced_by_quickstart", true);
        }

        Location vehicleLocation = vehicle.getLocation();
        Block hit = barrier.block();
        Region region = new Region(
            player.getWorld().getName(),
            Math.min(vehicleLocation.getBlockX(), hit.getX()) - 12,
            Math.min(vehicleLocation.getBlockY(), hit.getY()) - 6,
            Math.min(vehicleLocation.getBlockZ(), hit.getZ()) - 12,
            Math.max(vehicleLocation.getBlockX(), hit.getX()) + 12,
            Math.max(vehicleLocation.getBlockY(), hit.getY()) + 8,
            Math.max(vehicleLocation.getBlockZ(), hit.getZ()) + 12,
            barrier.axis(),
            barrier.coordinate()
        );

        long expires = System.currentTimeMillis() + seconds * 1000L;
        String nonce = UUID.randomUUID().toString();
        Session session = new Session(player, nonce, expires, region);
        sessions.put(player.getUniqueId(), session);

        send(player, String.join("|",
            "AUTH",
            "2",
            player.getUniqueId().toString(),
            Long.toString(expires),
            Integer.toString(region.minX()),
            Integer.toString(region.minY()),
            Integer.toString(region.minZ()),
            Integer.toString(region.maxX()),
            Integer.toString(region.maxY()),
            Integer.toString(region.maxZ()),
            nonce,
            region.axis(),
            decimal(region.barrier())
        ));

        player.sendMessage("[PhaseLab] AUTHORIZED LAB READY for " + seconds + "s. Wall=" + region.axis() + "="
            + decimal(region.barrier()) + ". Press F6 for mode and F12 to start the campaign.");
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
            RayTraceResult result = world.rayTraceBlocks(
                origin.clone().add(0.0D, height, 0.0D),
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
        if (hit == null || hit.isPassable()) {
            return null;
        }

        boolean xAxis = Math.abs(direction.getX()) >= Math.abs(direction.getZ());
        if (xAxis) {
            double coordinate = direction.getX() >= 0.0D ? hit.getX() + 1.0D : hit.getX();
            return new Barrier("X", coordinate, hit);
        }
        double coordinate = direction.getZ() >= 0.0D ? hit.getZ() + 1.0D : hit.getZ();
        return new Barrier("Z", coordinate, hit);
    }

    private void sendStatus(CommandSender sender) {
        sender.sendMessage("[PhaseLab] server_v=" + VERSION + " sessions=" + sessions.size());
        if (sender instanceof Player player) {
            Session session = sessions.get(player.getUniqueId());
            if (session == null) {
                sender.sendMessage("[PhaseLab] Not authorized. Mount, face wall, /phaselab quickstart.");
                return;
            }
            long seconds = Math.max(0L, (session.expiresEpochMs - System.currentTimeMillis()) / 1000L);
            sender.sendMessage("[PhaseLab] authorized=" + seconds + "s ready=" + session.clientReady
                + " running=" + session.running + " case=" + safe(session.caseId)
                + " scenario=" + safe(session.scenario));
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
                send(player, "ACK|" + session.nonce + "|READY|" + clean(value(parts, 2)));
            }
            case "START" -> {
                if (parts.length < 4) {
                    send(player, "ERROR|missing_case_or_scenario");
                } else {
                    start(session, parts[2], parts[3]);
                }
            }
            case "FINISH" -> {
                String suppliedCase = value(parts, 2);
                if (session.running && session.caseId.equals(suppliedCase)) {
                    finish(session, classify(session), detail(session, "client_finish"), true);
                } else {
                    send(player, "ERROR|finish_case_mismatch");
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

    private void start(Session session, String caseId, String scenario) {
        Player player = Bukkit.getPlayer(session.playerId);
        if (player == null || !player.isOnline()) {
            sessions.remove(session.playerId);
            return;
        }
        if (session.running) {
            send(player, "ERROR|case_already_running");
            return;
        }
        if (!session.clientReady) {
            send(player, "ERROR|client_not_ready_run_quickstart_again");
            return;
        }
        if (!SCENARIOS.contains(scenario)) {
            send(player, "ERROR|scenario_not_allowed");
            return;
        }
        if (caseId == null || !caseId.matches("[A-Z0-9_]{3,64}")) {
            send(player, "ERROR|invalid_case_id");
            return;
        }

        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            send(player, "ERROR|mount_required");
            return;
        }
        if (!session.region.contains(player.getLocation()) || !session.region.contains(vehicle.getLocation())) {
            send(player, "LOCKED|outside_authorized_region");
            return;
        }
        if (hasNearbyOtherPlayer(player, 8.0D)) {
            send(player, "ERROR|another_player_near_lab");
            return;
        }

        session.caseId = caseId;
        session.scenario = scenario;
        session.running = true;
        session.ticks = 0;
        session.playerStart = player.getLocation().clone();
        session.vehicle = vehicle;
        session.vehicleStart = vehicle.getLocation().clone();
        session.playerVelocity = player.getVelocity().clone();
        session.vehicleVelocity = vehicle.getVelocity().clone();
        session.direction = session.region.coordinate(session.vehicleStart) <= session.region.barrier() ? 1.0D : -1.0D;
        session.maxPlayerProgress = Double.NEGATIVE_INFINITY;
        session.maxVehicleProgress = Double.NEGATIVE_INFINITY;
        session.persistentCrossingTicks = 0;
        session.maxPersistentCrossingTicks = 0;
        session.solidOverlapTicks = 0;
        session.maxSolidOverlapTicks = 0;
        session.dismountedTick = -1;
        session.startedAt = Instant.now();

        send(player, "ACK|" + session.nonce + "|START|" + caseId);
        writeReport(session, "STARTED", "case_started");
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
            if (hasNearbyOtherPlayer(player, 8.0D)) {
                finish(session, "SAFETY_ABORT", "another_player_entered_lab", true);
                continue;
            }

            Location playerLocation = player.getLocation();
            Location vehicleLocation = vehicle.getLocation();
            if (!session.region.contains(playerLocation) || !session.region.contains(vehicleLocation)) {
                finish(session, "SAFETY_ABORT", "left_authorized_region", true);
                continue;
            }

            double maxDistance = getConfig().getDouble("max-displacement-blocks", 24.0D);
            if (distance(playerLocation, session.playerStart) > maxDistance
                || distance(vehicleLocation, session.vehicleStart) > maxDistance) {
                finish(session, "SAFETY_ABORT", "displacement_cap", true);
                continue;
            }

            double playerProgress = session.direction
                * (session.region.coordinate(playerLocation) - session.region.barrier());
            double vehicleProgress = session.direction
                * (session.region.coordinate(vehicleLocation) - session.region.barrier());
            session.maxPlayerProgress = Math.max(session.maxPlayerProgress, playerProgress);
            session.maxVehicleProgress = Math.max(session.maxVehicleProgress, vehicleProgress);

            double threshold = getConfig().getDouble("penetration-threshold-blocks", 0.35D);
            if (vehicleProgress > threshold) {
                session.persistentCrossingTicks++;
                session.maxPersistentCrossingTicks = Math.max(
                    session.maxPersistentCrossingTicks,
                    session.persistentCrossingTicks
                );
            } else {
                session.persistentCrossingTicks = 0;
            }

            if (overlapsSolid(vehicle)) {
                session.solidOverlapTicks++;
                session.maxSolidOverlapTicks = Math.max(session.maxSolidOverlapTicks, session.solidOverlapTicks);
            } else {
                session.solidOverlapTicks = 0;
            }

            if (session.dismountedTick < 0 && player.getVehicle() == null) {
                session.dismountedTick = session.ticks;
            }

            int required = getConfig().getInt("required-persistent-crossing-ticks", 5);
            if (session.persistentCrossingTicks >= required) {
                finish(session, "REPRODUCED", detail(session, "persistent_server_crossing"), true);
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
        if (session.maxPersistentCrossingTicks >= required) {
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
            + ";case=" + safe(session.caseId)
            + ";scenario=" + safe(session.scenario)
            + ";ticks=" + session.ticks
            + ";vehicle_progress=" + decimal(session.maxVehicleProgress)
            + ";player_progress=" + decimal(session.maxPlayerProgress)
            + ";max_crossing_ticks=" + session.maxPersistentCrossingTicks
            + ";max_solid_overlap_ticks=" + session.maxSolidOverlapTicks
            + ";dismount_tick=" + session.dismountedTick);
    }

    private void finish(Session session, String verdict, String detail, boolean restore) {
        Player player = Bukkit.getPlayer(session.playerId);
        boolean wasRunning = session.running;
        String finishedCase = safe(session.caseId);
        if (restore && wasRunning) {
            rollback(session);
        }
        session.running = false;
        writeReport(session, verdict, detail);
        if (player != null && player.isOnline()) {
            send(player, "RESULT|" + session.nonce + "|" + clean(verdict) + "|" + clean(detail) + "|" + finishedCase);
        }
        resetCase(session);
    }

    private void resetCase(Session session) {
        session.ticks = 0;
        session.caseId = "NONE";
        session.scenario = "NONE";
        session.playerStart = null;
        session.vehicleStart = null;
        session.playerVelocity = null;
        session.vehicleVelocity = null;
        session.vehicle = null;
        session.persistentCrossingTicks = 0;
        session.maxPersistentCrossingTicks = 0;
        session.solidOverlapTicks = 0;
        session.maxSolidOverlapTicks = 0;
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
            vehicle.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
            vehicle.teleport(session.vehicleStart);
        }
        player.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
        player.teleport(session.playerStart);

        if (vehicle != null && vehicle.isValid()) {
            Bukkit.getScheduler().runTaskLater(this, () -> {
                Player current = Bukkit.getPlayer(session.playerId);
                if (current != null && current.isOnline() && vehicle.isValid()) {
                    vehicle.setVelocity(new Vector(0.0D, 0.0D, 0.0D));
                    vehicle.addPassenger(current);
                }
            }, 2L);
        }
    }

    private boolean overlapsSolid(Entity entity) {
        BoundingBox box = entity.getBoundingBox().expand(-0.001D);
        World world = entity.getWorld();
        int minX = (int) Math.floor(box.getMinX());
        int minY = (int) Math.floor(box.getMinY());
        int minZ = (int) Math.floor(box.getMinZ());
        int maxX = (int) Math.floor(box.getMaxX());
        int maxY = (int) Math.floor(box.getMaxY());
        int maxZ = (int) Math.floor(box.getMaxZ());

        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    Block block = world.getBlockAt(x, y, z);
                    if (!block.isPassable() && block.getBoundingBox().overlaps(box)) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private boolean hasNearbyOtherPlayer(Player player, double radius) {
        double radiusSquared = radius * radius;
        for (Player other : player.getWorld().getPlayers()) {
            if (other.getUniqueId().equals(player.getUniqueId())) {
                continue;
            }
            if (other.getLocation().distanceSquared(player.getLocation()) <= radiusSquared) {
                return true;
            }
        }
        return false;
    }

    private void writeReport(Session session, String verdict, String detail) {
        Path reports = getDataFolder().toPath().resolve("reports");
        Path file = reports.resolve(LocalDate.now() + ".jsonl");
        String line = "{"
            + "\"timestamp\":\"" + json(Instant.now().toString()) + "\","
            + "\"server_version\":\"" + VERSION + "\","
            + "\"player_uuid\":\"" + json(session.playerId.toString()) + "\","
            + "\"player_name\":\"" + json(session.playerName) + "\","
            + "\"case_id\":\"" + json(safe(session.caseId)) + "\","
            + "\"scenario\":\"" + json(safe(session.scenario)) + "\","
            + "\"verdict\":\"" + json(verdict) + "\","
            + "\"detail\":\"" + json(detail) + "\","
            + "\"ticks\":" + session.ticks + ","
            + "\"barrier_axis\":\"" + json(session.region.axis()) + "\","
            + "\"barrier_coordinate\":" + decimal(session.region.barrier()) + ","
            + "\"max_vehicle_progress\":" + decimal(session.maxVehicleProgress) + ","
            + "\"max_player_progress\":" + decimal(session.maxPlayerProgress) + ","
            + "\"max_crossing_ticks\":" + session.maxPersistentCrossingTicks + ","
            + "\"max_solid_overlap_ticks\":" + session.maxSolidOverlapTicks
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

    @EventHandler
    public void onDamage(EntityDamageEvent event) {
        if (!(event.getEntity() instanceof Player player)) {
            return;
        }
        Session session = sessions.get(player.getUniqueId());
        if (session != null && session.running) {
            finish(session, "SAFETY_ABORT", "player_damage:" + event.getCause().name(), true);
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
        private String caseId = "NONE";
        private String scenario = "NONE";
        private int ticks;
        private Location playerStart;
        private Location vehicleStart;
        private Vector playerVelocity;
        private Vector vehicleVelocity;
        private Entity vehicle;
        private double direction;
        private double maxPlayerProgress = Double.NEGATIVE_INFINITY;
        private double maxVehicleProgress = Double.NEGATIVE_INFINITY;
        private int persistentCrossingTicks;
        private int maxPersistentCrossingTicks;
        private int solidOverlapTicks;
        private int maxSolidOverlapTicks;
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