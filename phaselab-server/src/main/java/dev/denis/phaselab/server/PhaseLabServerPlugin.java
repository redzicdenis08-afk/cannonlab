package dev.denis.phaselab.server;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.configuration.file.FileConfiguration;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.plugin.messaging.PluginMessageListener;
import org.bukkit.util.BoundingBox;
import org.jetbrains.annotations.NotNull;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
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
    private String serverId;
    private PrivateKey privateKey;
    private PublicKey publicKey;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        try {
            loadOrCreateIdentity();
            exportClientLock();
        } catch (Exception exception) {
            getLogger().severe("Cannot initialize signing identity: " + exception);
            getServer().getPluginManager().disablePlugin(this);
            return;
        }

        getServer().getMessenger().registerOutgoingPluginChannel(this, CHANNEL);
        getServer().getMessenger().registerIncomingPluginChannel(this, CHANNEL, this);
        getServer().getPluginManager().registerEvents(this, this);
        if (getCommand("phaselab") != null) {
            getCommand("phaselab").setExecutor(this);
        }
        getServer().getScheduler().runTaskTimer(this, this::tickSessions, 1L, 1L);
        getLogger().info("PhaseLab Server v5 active. server-id=" + serverId + "; active mode is fail-closed until the lab region is configured.");
    }

    @Override
    public void onDisable() {
        for (Session session : new ArrayList<>(sessions.values())) {
            rollback(session);
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
        if (args.length == 0 || "status".equalsIgnoreCase(args[0])) {
            sendStatus(sender);
            return true;
        }

        String sub = args[0].toLowerCase(Locale.ROOT);
        switch (sub) {
            case "setcorner1" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                Location location = player.getLocation();
                FileConfiguration config = getConfig();
                config.set("lab.world", location.getWorld().getName());
                config.set("lab.min-x", location.getBlockX());
                config.set("lab.min-y", location.getBlockY());
                config.set("lab.min-z", location.getBlockZ());
                config.set("lab.max-x", location.getBlockX());
                config.set("lab.max-y", location.getBlockY());
                config.set("lab.max-z", location.getBlockZ());
                config.set("lab.configured", false);
                saveConfig();
                sender.sendMessage("[PhaseLab] Corner 1 saved at " + format(location) + ". Now use /phaselab setcorner2.");
            }
            case "setcorner2" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                Location location = player.getLocation();
                FileConfiguration config = getConfig();
                String world = config.getString("lab.world", "");
                if (!world.equals(location.getWorld().getName())) {
                    sender.sendMessage("[PhaseLab] Both corners must be in the same world.");
                    return true;
                }
                int x1 = config.getInt("lab.min-x");
                int y1 = config.getInt("lab.min-y");
                int z1 = config.getInt("lab.min-z");
                config.set("lab.min-x", Math.min(x1, location.getBlockX()));
                config.set("lab.min-y", Math.min(y1, location.getBlockY()));
                config.set("lab.min-z", Math.min(z1, location.getBlockZ()));
                config.set("lab.max-x", Math.max(x1, location.getBlockX()));
                config.set("lab.max-y", Math.max(y1, location.getBlockY()));
                config.set("lab.max-z", Math.max(z1, location.getBlockZ()));
                saveConfig();
                sender.sendMessage("[PhaseLab] Corner 2 saved at " + format(location) + ". Stand on the wall plane and use /phaselab setbarrier X or Z.");
            }
            case "setbarrier" -> {
                Player player = requirePlayer(sender);
                if (player == null) {
                    return true;
                }
                if (args.length < 2 || !("X".equalsIgnoreCase(args[1]) || "Z".equalsIgnoreCase(args[1]))) {
                    sender.sendMessage("[PhaseLab] Usage: /phaselab setbarrier <X|Z> [coordinate]");
                    return true;
                }
                String axis = args[1].toUpperCase(Locale.ROOT);
                double coordinate;
                try {
                    coordinate = args.length >= 3
                        ? Double.parseDouble(args[2])
                        : ("X".equals(axis) ? player.getLocation().getX() : player.getLocation().getZ());
                } catch (NumberFormatException exception) {
                    sender.sendMessage("[PhaseLab] Invalid coordinate.");
                    return true;
                }
                getConfig().set("lab.barrier-axis", axis);
                getConfig().set("lab.barrier-coordinate", coordinate);
                getConfig().set("lab.configured", true);
                saveConfig();
                sender.sendMessage("[PhaseLab] Barrier set to " + axis + "=" + coordinate + ". Harness is configured.");
            }
            case "authorize" -> {
                Player target = resolveTarget(sender, args.length >= 2 ? args[1] : null);
                if (target != null) {
                    authorize(target, sender);
                }
            }
            case "abort" -> {
                Player target = resolveTarget(sender, args.length >= 2 ? args[1] : null);
                if (target != null) {
                    Session session = sessions.get(target.getUniqueId());
                    if (session == null) {
                        sender.sendMessage("[PhaseLab] No session for " + target.getName() + ".");
                    } else {
                        finish(session, "ABORTED", "operator_abort", true);
                        sender.sendMessage("[PhaseLab] Session aborted and rolled back.");
                    }
                }
            }
            case "exportlock" -> {
                try {
                    exportClientLock();
                    sender.sendMessage("[PhaseLab] Client lock exported to plugins/PhaseLabServer/client-lock/.");
                } catch (IOException exception) {
                    sender.sendMessage("[PhaseLab] Export failed: " + exception.getMessage());
                }
            }
            default -> sender.sendMessage("[PhaseLab] Usage: /phaselab <status|setcorner1|setcorner2|setbarrier|authorize|abort|exportlock>");
        }
        return true;
    }

    private void sendStatus(CommandSender sender) {
        Region region = region();
        sender.sendMessage("[PhaseLab] server-id=" + serverId);
        sender.sendMessage("[PhaseLab] configured=" + region.configured + " region=" + region.worldName + " ["
            + region.minX + "," + region.minY + "," + region.minZ + "] -> ["
            + region.maxX + "," + region.maxY + "," + region.maxZ + "]");
        sender.sendMessage("[PhaseLab] barrier=" + region.axis + "=" + region.barrier + " sessions=" + sessions.size());
    }

    private void authorize(Player player, CommandSender operator) {
        Region region = region();
        if (!region.configured) {
            operator.sendMessage("[PhaseLab] Configure the region and barrier first.");
            return;
        }
        if (!region.contains(player.getLocation())) {
            operator.sendMessage("[PhaseLab] Target must stand inside the configured lab region.");
            return;
        }

        long expires = System.currentTimeMillis() + getConfig().getLong("authorization-seconds", 120L) * 1000L;
        String nonce = UUID.randomUUID().toString();
        Session session = new Session(player, nonce, expires, region);
        sessions.put(player.getUniqueId(), session);

        String canonical = String.join("|",
            "AUTH",
            "1",
            serverId,
            player.getUniqueId().toString(),
            Long.toString(expires),
            Integer.toString(region.minX),
            Integer.toString(region.minY),
            Integer.toString(region.minZ),
            Integer.toString(region.maxX),
            Integer.toString(region.maxY),
            Integer.toString(region.maxZ),
            nonce
        );
        try {
            send(player, canonical + "|" + sign(canonical));
            operator.sendMessage("[PhaseLab] Signed authorization sent to " + player.getName() + " for "
                + getConfig().getLong("authorization-seconds", 120L) + " seconds.");
        } catch (Exception exception) {
            sessions.remove(player.getUniqueId());
            operator.sendMessage("[PhaseLab] Authorization signing failed: " + exception.getMessage());
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
        if (parts.length < 4) {
            send(player, "ERROR|malformed_command");
            return;
        }

        Session session = sessions.get(player.getUniqueId());
        if (!validSession(session, player, parts[1], parts[2])) {
            send(player, "LOCKED|no_valid_signed_session");
            return;
        }

        switch (parts[0]) {
            case "READY" -> session.clientReady = true;
            case "START" -> start(session, parts[3]);
            case "FINISH" -> {
                if (session.running) {
                    finish(session, classify(session), detail(session, "client_finish"), true);
                }
            }
            case "ABORT" -> finish(session, "ABORTED", clean(parts[3]), true);
            default -> send(player, "ERROR|unknown_command");
        }
    }

    private boolean validSession(Session session, Player player, String suppliedServerId, String suppliedNonce) {
        return session != null
            && session.playerId.equals(player.getUniqueId())
            && serverId.equals(suppliedServerId)
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
        if (!session.region.contains(player.getLocation())) {
            send(player, "LOCKED|outside_lab_region");
            return;
        }
        Entity vehicle = player.getVehicle();
        if (vehicle == null) {
            send(player, "ERROR|mount_required");
            return;
        }

        session.scenario = scenario;
        session.running = true;
        session.ticks = 0;
        session.playerStart = player.getLocation().clone();
        session.vehicle = vehicle;
        session.vehicleStart = vehicle.getLocation().clone();
        session.startedMounted = true;
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
                finish(session, "EXPIRED", "authorization_expired", true);
                continue;
            }
            if (!session.running) {
                continue;
            }

            session.ticks++;
            if (!session.region.contains(player.getLocation())) {
                finish(session, "SAFETY_ABORT", "left_lab_region", true);
                continue;
            }
            if (session.playerStart == null || player.getWorld() != session.playerStart.getWorld()) {
                finish(session, "SAFETY_ABORT", "world_changed", true);
                continue;
            }
            double maxDistance = getConfig().getDouble("max-displacement-blocks", 16.0D);
            if (player.getLocation().distance(session.playerStart) > maxDistance) {
                finish(session, "SAFETY_ABORT", "distance_cap", true);
                continue;
            }

            double playerProgress = session.direction * (session.region.coordinate(player.getLocation()) - session.region.barrier);
            session.maxPlayerProgress = Math.max(session.maxPlayerProgress, playerProgress);
            Entity vehicle = session.vehicle;
            double vehicleProgress = Double.NEGATIVE_INFINITY;
            if (vehicle != null && vehicle.isValid()) {
                vehicleProgress = session.direction * (session.region.coordinate(vehicle.getLocation()) - session.region.barrier);
                session.maxVehicleProgress = Math.max(session.maxVehicleProgress, vehicleProgress);
            }

            if (session.startedMounted && player.getVehicle() == null && session.dismountedTick < 0) {
                session.dismountedTick = session.ticks;
            }

            double threshold = getConfig().getDouble("penetration-threshold-blocks", 0.35D);
            boolean playerCrossing = playerProgress > threshold && intersectsSolid(player);
            boolean vehicleCrossing = vehicleProgress > threshold && vehicle != null && intersectsSolid(vehicle);
            if (playerCrossing || vehicleCrossing) {
                session.persistentCrossingTicks++;
            } else {
                session.persistentCrossingTicks = 0;
            }

            int requiredTicks = getConfig().getInt("required-persistent-crossing-ticks", 5);
            if (session.persistentCrossingTicks >= requiredTicks) {
                finish(session, "REPRODUCED", detail(session, "persistent_solid_crossing"), true);
                continue;
            }

            int maxTicks = getConfig().getInt("max-runtime-ticks", 240);
            if (session.ticks >= maxTicks) {
                finish(session, classify(session), detail(session, "runtime_cap"), true);
            }
        }
    }

    private String classify(Session session) {
        double threshold = getConfig().getDouble("penetration-threshold-blocks", 0.35D);
        if (session.persistentCrossingTicks >= getConfig().getInt("required-persistent-crossing-ticks", 5)) {
            return "REPRODUCED";
        }
        if (session.dismountedTick >= 0 && !"DISMOUNT_EDGE".equals(session.scenario)) {
            return "FORCED_DISMOUNT";
        }
        if (session.maxPlayerProgress > threshold || session.maxVehicleProgress > threshold) {
            return "TRANSIENT_CROSSING";
        }
        return "BLOCKED";
    }

    private String detail(Session session, String reason) {
        return String.format(Locale.ROOT,
            "scenario=%s;reason=%s;ticks=%d;player_progress=%.3f;vehicle_progress=%.3f;dismount_tick=%d",
            clean(session.scenario),
            clean(reason),
            session.ticks,
            finite(session.maxPlayerProgress),
            finite(session.maxVehicleProgress),
            session.dismountedTick
        );
    }

    private void finish(Session session, String verdict, String detail, boolean remove) {
        session.running = false;
        Player player = Bukkit.getPlayer(session.playerId);
        rollback(session);
        writeReport(session, verdict, detail);
        if (player != null && player.isOnline()) {
            send(player, "RESULT|" + session.nonce + "|" + clean(verdict) + "|" + clean(detail));
        }
        if (remove) {
            sessions.remove(session.playerId);
        }
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
        if (session.startedMounted && vehicle != null && vehicle.isValid()) {
            getServer().getScheduler().runTask(this, () -> {
                if (player.isOnline() && vehicle.isValid()) {
                    vehicle.addPassenger(player);
                }
            });
        }
    }

    private boolean intersectsSolid(Entity entity) {
        BoundingBox box = entity.getBoundingBox();
        World world = entity.getWorld();
        int minX = floor(box.getMinX() + 0.01D);
        int minY = floor(box.getMinY() + 0.01D);
        int minZ = floor(box.getMinZ() + 0.01D);
        int maxX = floor(box.getMaxX() - 0.01D);
        int maxY = floor(box.getMaxY() - 0.01D);
        int maxZ = floor(box.getMaxZ() - 0.01D);
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    if (world.getBlockAt(x, y, z).getType().isSolid()) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private static int floor(double value) {
        return (int) Math.floor(value);
    }

    private void loadOrCreateIdentity() throws Exception {
        Files.createDirectories(getDataFolder().toPath());
        Path path = getDataFolder().toPath().resolve("identity.properties");
        Properties properties = new Properties();
        KeyFactory factory = KeyFactory.getInstance("Ed25519");
        if (Files.isRegularFile(path)) {
            try (var reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
                properties.load(reader);
            }
            serverId = properties.getProperty("server-id");
            privateKey = factory.generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(properties.getProperty("private-key"))));
            publicKey = factory.generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(properties.getProperty("public-key"))));
            return;
        }

        KeyPair pair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair();
        serverId = UUID.randomUUID().toString();
        privateKey = pair.getPrivate();
        publicKey = pair.getPublic();
        properties.setProperty("server-id", serverId);
        properties.setProperty("private-key", Base64.getEncoder().encodeToString(privateKey.getEncoded()));
        properties.setProperty("public-key", Base64.getEncoder().encodeToString(publicKey.getEncoded()));
        try (var writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW)) {
            properties.store(writer, "PhaseLab server signing identity. Keep the private key on the test server only.");
        }
    }

    private void exportClientLock() throws IOException {
        Path dir = getDataFolder().toPath().resolve("client-lock");
        Files.createDirectories(dir);
        Files.writeString(dir.resolve("server-id.txt"), serverId + System.lineSeparator(), StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        Files.writeString(dir.resolve("server-public-key.txt"), Base64.getEncoder().encodeToString(publicKey.getEncoded()) + System.lineSeparator(),
            StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
    }

    private String sign(String canonical) throws Exception {
        Signature signature = Signature.getInstance("Ed25519");
        signature.initSign(privateKey);
        signature.update(canonical.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(signature.sign());
    }

    private Region region() {
        FileConfiguration config = getConfig();
        return new Region(
            config.getBoolean("lab.configured", false),
            config.getString("lab.world", "world"),
            config.getInt("lab.min-x"),
            config.getInt("lab.min-y"),
            config.getInt("lab.min-z"),
            config.getInt("lab.max-x"),
            config.getInt("lab.max-y"),
            config.getInt("lab.max-z"),
            config.getString("lab.barrier-axis", "X").toUpperCase(Locale.ROOT),
            config.getDouble("lab.barrier-coordinate")
        );
    }

    private void writeReport(Session session, String verdict, String detail) {
        try {
            Path dir = getDataFolder().toPath().resolve("reports");
            Files.createDirectories(dir);
            Path report = dir.resolve(LocalDate.now() + ".jsonl");
            String line = "{"
                + "\"timestamp\":\"" + json(Instant.now().toString()) + "\","
                + "\"server_id\":\"" + json(serverId) + "\","
                + "\"player_uuid\":\"" + json(session.playerId.toString()) + "\","
                + "\"nonce\":\"" + json(session.nonce) + "\","
                + "\"scenario\":\"" + json(session.scenario) + "\","
                + "\"verdict\":\"" + json(verdict) + "\","
                + "\"detail\":\"" + json(detail) + "\","
                + "\"ticks\":" + session.ticks + ","
                + "\"max_player_progress\":" + finite(session.maxPlayerProgress) + ","
                + "\"max_vehicle_progress\":" + finite(session.maxVehicleProgress)
                + "}" + System.lineSeparator();
            Files.writeString(report, line, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND, StandardOpenOption.WRITE);
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

    private Player requirePlayer(CommandSender sender) {
        if (sender instanceof Player player) {
            return player;
        }
        sender.sendMessage("[PhaseLab] This command requires a player.");
        return null;
    }

    private Player resolveTarget(CommandSender sender, String name) {
        if (name == null) {
            return requirePlayer(sender);
        }
        Player player = Bukkit.getPlayerExact(name);
        if (player == null) {
            sender.sendMessage("[PhaseLab] Player not found: " + name);
        }
        return player;
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        Session session = sessions.remove(event.getPlayer().getUniqueId());
        if (session != null) {
            rollback(session);
        }
    }

    private static String format(Location location) {
        return location.getWorld().getName() + " " + location.getBlockX() + " " + location.getBlockY() + " " + location.getBlockZ();
    }

    private static String clean(String value) {
        return value == null ? "" : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static String json(String value) {
        return clean(value).replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static double finite(double value) {
        return Double.isFinite(value) ? value : 0.0D;
    }

    private static final class Session {
        private final UUID playerId;
        private final String nonce;
        private final long expiresEpochMs;
        private final Region region;
        private boolean clientReady;
        private boolean running;
        private String scenario = "NONE";
        private int ticks;
        private int persistentCrossingTicks;
        private int dismountedTick = -1;
        private boolean startedMounted;
        private double direction;
        private double maxPlayerProgress;
        private double maxVehicleProgress;
        private Location playerStart;
        private Entity vehicle;
        private Location vehicleStart;
        private Instant startedAt;

        private Session(Player player, String nonce, long expiresEpochMs, Region region) {
            this.playerId = player.getUniqueId();
            this.nonce = nonce;
            this.expiresEpochMs = expiresEpochMs;
            this.region = region;
        }
    }

    private record Region(
        boolean configured,
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
        private boolean contains(Location location) {
            return configured
                && location.getWorld() != null
                && worldName.equals(location.getWorld().getName())
                && location.getBlockX() >= minX && location.getBlockX() <= maxX
                && location.getBlockY() >= minY && location.getBlockY() <= maxY
                && location.getBlockZ() >= minZ && location.getBlockZ() <= maxZ;
        }

        private double coordinate(Location location) {
            return "Z".equals(axis) ? location.getZ() : location.getX();
        }
    }
}
