package dev.denis.phaselab.profiler;

import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabCompleter;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerKickEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.player.PlayerVelocityEvent;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.event.vehicle.VehicleExitEvent;
import org.bukkit.permissions.PermissionAttachment;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.Vector;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.EnumMap;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Passive, admin-only profiler for owned test servers. It does not send,
 * suppress, rewrite, or delay movement packets.
 */
public final class PhaseLabSetbackProfiler extends JavaPlugin implements Listener, CommandExecutor, TabCompleter {
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter
            .ofPattern("yyyyMMdd-HHmmss")
            .withLocale(Locale.ROOT)
            .withZone(ZoneOffset.UTC);

    private static final List<String> GRIM_NODES = List.of(
            "grim.disabled",
            "grim.nosetback",
            "grim.nomodifypacket",
            "grim.exempt"
    );
    private static final long TRIAL_WINDOW_TICKS = 30L;

    private final Map<UUID, Session> sessions = new HashMap<>();
    private final Map<UUID, PermissionAttachment> modeAttachments = new HashMap<>();
    private long profilerTick;

    @Override
    public void onEnable() {
        Objects.requireNonNull(getCommand("phaseprofile"), "phaseprofile command")
                .setExecutor(this);
        Objects.requireNonNull(getCommand("phaseprofile"), "phaseprofile command")
                .setTabCompleter(this);
        getServer().getPluginManager().registerEvents(this, this);
        getServer().getScheduler().runTaskTimer(this, this::sampleArmedPlayers, 1L, 1L);
        getLogger().info("Passive setback profiler enabled. No movement packets are modified.");
    }

    @Override
    public void onDisable() {
        for (Session session : new ArrayList<>(sessions.values())) {
            closeSession(session, "plugin_disable");
        }
        sessions.clear();
        for (PermissionAttachment attachment : modeAttachments.values()) {
            attachment.remove();
        }
        modeAttachments.clear();
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!sender.hasPermission("phaselab.profiler.admin")) {
            sender.sendMessage("You do not have permission to use the profiler.");
            return true;
        }
        if (args.length < 2) {
            sendUsage(sender);
            return true;
        }

        String action = args[0].toLowerCase(Locale.ROOT);
        Player target = Bukkit.getPlayerExact(args[1]);
        if (target == null) {
            sender.sendMessage("Player must be online: " + args[1]);
            return true;
        }

        return switch (action) {
            case "arm" -> arm(sender, target);
            case "stop" -> stop(sender, target);
            case "status" -> status(sender, target);
            case "mark" -> mark(sender, target, args);
            case "mode" -> mode(sender, target, args);
            default -> {
                sendUsage(sender);
                yield true;
            }
        };
    }

    private boolean arm(CommandSender sender, Player target) {
        Session previous = sessions.remove(target.getUniqueId());
        if (previous != null) {
            closeSession(previous, "rearmed");
        }

        try {
            Path folder = getDataFolder().toPath().resolve("sessions");
            Files.createDirectories(folder);
            String filename = FILE_TIME.format(Instant.now()) + "-" + safeFilename(target.getName()) + ".jsonl";
            Path path = folder.resolve(filename);
            BufferedWriter writer = Files.newBufferedWriter(
                    path,
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE_NEW,
                    StandardOpenOption.WRITE
            );
            Session session = new Session(target.getUniqueId(), target.getName(), path, writer);
            sessions.put(target.getUniqueId(), session);
            setMode(target, session, GrimMode.BASELINE);
            Frame frame = Frame.capture(target);
            session.lastFrame = frame;
            session.lastMountedFrame = frame.mounted() ? frame : null;
            session.trialBaseline = frame;
            session.write(profilerTick, "SESSION_START", jsonObject(Map.of(
                    "player", quote(target.getName()),
                    "uuid", quote(target.getUniqueId().toString()),
                    "server", quote(getServer().getName() + " " + getServer().getVersion()),
                    "plugins", quote(pluginSnapshot()),
                    "grimPresent", Boolean.toString(isPluginEnabled("GrimAC")),
                    "noCheatEnforcerPresent", Boolean.toString(isPluginEnabled("NoCheatEnforcer")),
                    "mode", quote(session.mode.id)
            )));
            session.writeFrame(profilerTick, "ARM_FRAME", frame);
            sender.sendMessage("Profiler armed for " + target.getName() + ": " + path.toAbsolutePath());
        } catch (IOException error) {
            getLogger().log(java.util.logging.Level.SEVERE, "Unable to arm profiler", error);
            sender.sendMessage("Could not create profiler log: " + error.getMessage());
        }
        return true;
    }

    private boolean stop(CommandSender sender, Player target) {
        Session session = sessions.remove(target.getUniqueId());
        if (session == null) {
            sender.sendMessage("Profiler is not armed for " + target.getName() + ".");
            clearMode(target);
            return true;
        }
        closeSession(session, "admin_stop");
        clearMode(target);
        sender.sendMessage("Profiler stopped for " + target.getName() + ". Log: " + session.path.toAbsolutePath());
        return true;
    }

    private boolean status(CommandSender sender, Player target) {
        Session session = sessions.get(target.getUniqueId());
        if (session == null) {
            sender.sendMessage("Profiler is not armed for " + target.getName() + ".");
            return true;
        }
        sender.sendMessage("Profiler: armed | mode=" + session.mode.id + " | file=" + session.path.toAbsolutePath());
        sender.sendMessage("Grim permissions: " + grimPermissionSnapshot(target));
        return true;
    }

    private boolean mark(CommandSender sender, Player target, String[] args) {
        Session session = sessions.get(target.getUniqueId());
        if (session == null) {
            sender.sendMessage("Arm the profiler first.");
            return true;
        }
        String marker = args.length >= 3
                ? String.join(" ", Arrays.copyOfRange(args, 2, args.length))
                : "manual";
        Frame frame = Frame.capture(target);
        session.resetTrial(frame, profilerTick);
        session.write(profilerTick, "MARK", jsonObject(Map.of(
                "label", quote(marker),
                "mode", quote(session.mode.id),
                "grimPermissions", quote(grimPermissionSnapshot(target))
        )));
        session.writeFrame(profilerTick, "MARK_FRAME", frame);
        sender.sendMessage("Marked " + target.getName() + " trial: " + marker);
        return true;
    }

    private boolean mode(CommandSender sender, Player target, String[] args) {
        if (args.length < 3) {
            sender.sendMessage("Modes: baseline, nosetback, nomodifypacket, disabled, exempt");
            return true;
        }
        GrimMode requested = GrimMode.parse(args[2]);
        if (requested == null) {
            sender.sendMessage("Unknown mode. Use baseline, nosetback, nomodifypacket, disabled, or exempt.");
            return true;
        }
        Session session = sessions.get(target.getUniqueId());
        if (session == null) {
            sender.sendMessage("Arm the profiler first.");
            return true;
        }
        setMode(target, session, requested);
        session.write(profilerTick, "MODE", jsonObject(Map.of(
                "mode", quote(requested.id),
                "grimPermissions", quote(grimPermissionSnapshot(target))
        )));
        sender.sendMessage("Profiler mode for " + target.getName() + " is now " + requested.id + ".");
        if (requested == GrimMode.EXEMPT || session.previousMode == GrimMode.EXEMPT) {
            sender.sendMessage("Grim's full exempt registration state may require the player to rejoin. Prefer disabled for live A/B testing.");
        }
        return true;
    }

    private void setMode(Player target, Session session, GrimMode mode) {
        session.previousMode = session.mode;
        clearMode(target);
        PermissionAttachment attachment = target.addAttachment(this);
        for (String node : GRIM_NODES) {
            attachment.setPermission(node, false);
        }
        if (mode.permissionNode != null) {
            attachment.setPermission(mode.permissionNode, true);
        }
        target.recalculatePermissions();
        modeAttachments.put(target.getUniqueId(), attachment);
        session.mode = mode;
    }

    private void clearMode(Player target) {
        PermissionAttachment existing = modeAttachments.remove(target.getUniqueId());
        if (existing != null) {
            existing.remove();
            target.recalculatePermissions();
        }
    }

    private void sampleArmedPlayers() {
        profilerTick++;
        for (Session session : sessions.values()) {
            Player player = Bukkit.getPlayer(session.playerId);
            if (player == null || !player.isOnline()) {
                continue;
            }
            Frame frame = Frame.capture(player);
            session.lastFrame = frame;
            if (frame.mounted()) {
                session.lastMountedFrame = frame;
            }
            session.writeFrame(profilerTick, "SAMPLE", frame);
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleEnter(VehicleEnterEvent event) {
        if (event.getEntered() instanceof Player player) {
            writeEvent(player, "VEHICLE_ENTER", Map.of(
                    "cancelled", Boolean.toString(event.isCancelled()),
                    "vehicle", quote(entityIdentity(event.getVehicle()))
            ));
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleExit(VehicleExitEvent event) {
        if (!(event.getExited() instanceof Player player)) {
            return;
        }
        Session session = sessions.get(player.getUniqueId());
        if (session == null) {
            return;
        }
        boolean trialWindowOpen = session.isTrialWindowOpen(profilerTick);
        session.write(profilerTick,
                trialWindowOpen ? "VEHICLE_EXIT" : "VEHICLE_EXIT_OUTSIDE_TRIAL_WINDOW",
                jsonObject(Map.of(
                        "cancelled", Boolean.toString(event.isCancelled()),
                        "vehicle", quote(entityIdentity(event.getVehicle())),
                        "mode", quote(session.mode.id),
                        "trialWindowOpen", Boolean.toString(trialWindowOpen),
                        "ticksSinceMark", Long.toString(session.ticksSinceMark(profilerTick))
                )));
        if (!trialWindowOpen) {
            return;
        }
        session.vehicleExitObserved = true;
        scheduleClassification(player, session);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onTeleport(PlayerTeleportEvent event) {
        Session session = sessions.get(event.getPlayer().getUniqueId());
        if (session == null) {
            return;
        }
        boolean trialWindowOpen = session.isTrialWindowOpen(profilerTick);
        if (trialWindowOpen) {
            session.teleportObserved = true;
        }
        session.write(profilerTick, "PLAYER_TELEPORT", jsonObject(Map.of(
                "cancelled", Boolean.toString(event.isCancelled()),
                "cause", quote(event.getCause().name()),
                "from", quote(location(event.getFrom())),
                "to", quote(event.getTo() == null ? "null" : location(event.getTo())),
                "trialWindowOpen", Boolean.toString(trialWindowOpen),
                "ticksSinceMark", Long.toString(session.ticksSinceMark(profilerTick))
        )));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVelocity(PlayerVelocityEvent event) {
        writeEvent(event.getPlayer(), "PLAYER_VELOCITY", Map.of(
                "cancelled", Boolean.toString(event.isCancelled()),
                "velocity", quote(vector(event.getVelocity()))
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onInteractEntity(PlayerInteractEntityEvent event) {
        writeEvent(event.getPlayer(), "INTERACT_ENTITY", Map.of(
                "cancelled", Boolean.toString(event.isCancelled()),
                "target", quote(entityIdentity(event.getRightClicked())),
                "hand", quote(event.getHand().name())
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent event) {
        writeEvent(event.getPlayer(), "PLAYER_JOIN", Map.of());
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent event) {
        writeEvent(event.getPlayer(), "PLAYER_QUIT", Map.of(
                "reason", quote(String.valueOf(event.getReason()))
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onKick(PlayerKickEvent event) {
        writeEvent(event.getPlayer(), "PLAYER_KICK", Map.of(
                "cancelled", Boolean.toString(event.isCancelled()),
                "cause", quote(event.getCause().name()),
                "reason", quote(event.reason().toString())
        ));
    }

    private void scheduleClassification(Player player, Session session) {
        if (session.classificationPending) {
            return;
        }
        session.classificationPending = true;
        Frame before = session.trialBaseline != null && session.trialBaseline.mounted()
                ? session.trialBaseline
                : session.lastMountedFrame;
        getServer().getScheduler().runTaskLater(this, () -> {
            try {
                Player current = Bukkit.getPlayer(player.getUniqueId());
                if (current == null || before == null) {
                    session.write(profilerTick, "CLASSIFICATION", jsonObject(Map.of(
                            "classification", quote(SetbackClassifier.Classification.INSUFFICIENT_EVIDENCE.name()),
                            "explanation", quote("Player or mounted baseline was unavailable.")
                    )));
                    return;
                }
                Frame after = Frame.capture(current);
                double playerDistance = distance(before.playerLocation, after.playerLocation);
                double vehicleDistance = vehicleDistance(before);
                SetbackClassifier.Result result = SetbackClassifier.classify(new SetbackClassifier.Input(
                        before.mounted(),
                        after.mounted(),
                        session.vehicleExitObserved,
                        session.vehicleExitObserved,
                        session.teleportObserved,
                        playerDistance,
                        vehicleDistance
                ));
                session.classificationCounts.merge(result.classification(), 1, Integer::sum);
                session.write(profilerTick, "CLASSIFICATION", jsonObject(Map.of(
                        "classification", quote(result.classification().name()),
                        "explanation", quote(result.explanation()),
                        "mode", quote(session.mode.id),
                        "grimPermissions", quote(grimPermissionSnapshot(current))
                )));
                session.writeFrame(profilerTick, "POST_CLASSIFICATION_FRAME", after);
            } finally {
                session.classificationPending = false;
                session.vehicleExitObserved = false;
                session.teleportObserved = false;
                session.trialArmedTick = -1L;
                Player latest = Bukkit.getPlayer(session.playerId);
                session.trialBaseline = latest != null && latest.isOnline() ? Frame.capture(latest) : null;
            }
        }, 3L);
    }

    private double vehicleDistance(Frame before) {
        if (before.vehicleId == null || before.vehicleLocation == null) {
            return 0.0D;
        }
        Entity currentVehicle = Bukkit.getEntity(before.vehicleId);
        if (currentVehicle == null) {
            return 0.0D;
        }
        return distance(before.vehicleLocation, currentVehicle.getLocation());
    }

    private void writeEvent(Player player, String type, Map<String, String> fields) {
        Session session = sessions.get(player.getUniqueId());
        if (session != null) {
            session.write(profilerTick, type, jsonObject(fields));
        }
    }

    private void closeSession(Session session, String reason) {
        try {
            session.write(profilerTick, "SESSION_END", jsonObject(Map.of(
                    "reason", quote(reason),
                    "classifications", quote(session.classificationCounts.toString())
            )));
            session.writer.close();
        } catch (IOException error) {
            getLogger().log(java.util.logging.Level.WARNING, "Unable to close profiler log " + session.path, error);
        }
    }

    private boolean isPluginEnabled(String name) {
        Plugin plugin = getServer().getPluginManager().getPlugin(name);
        return plugin != null && plugin.isEnabled();
    }

    private String pluginSnapshot() {
        return Arrays.stream(getServer().getPluginManager().getPlugins())
                .map(plugin -> plugin.getName() + "@" + plugin.getPluginMeta().getVersion())
                .sorted()
                .collect(Collectors.joining(","));
    }

    private static String grimPermissionSnapshot(Player player) {
        return GRIM_NODES.stream()
                .map(node -> node + "=" + player.hasPermission(node))
                .collect(Collectors.joining(","));
    }

    private static String entityIdentity(Entity entity) {
        return entity.getType().name() + ":" + entity.getUniqueId();
    }

    private static String location(Location location) {
        return String.format(
                Locale.ROOT,
                "%s:%.6f,%.6f,%.6f,%.3f,%.3f",
                location.getWorld() == null ? "null" : location.getWorld().getName(),
                location.getX(), location.getY(), location.getZ(), location.getYaw(), location.getPitch()
        );
    }

    private static String vector(Vector vector) {
        return String.format(Locale.ROOT, "%.6f,%.6f,%.6f", vector.getX(), vector.getY(), vector.getZ());
    }

    private static double distance(Location first, Location second) {
        if (first == null || second == null || first.getWorld() != second.getWorld()) {
            return 0.0D;
        }
        return first.distance(second);
    }

    private static String jsonObject(Map<String, String> fields) {
        return fields.entrySet().stream()
                .sorted(Map.Entry.comparingByKey())
                .map(entry -> quote(entry.getKey()) + ":" + entry.getValue())
                .collect(Collectors.joining(",", "{", "}"));
    }

    private static String quote(String value) {
        if (value == null) {
            return "null";
        }
        StringBuilder out = new StringBuilder(value.length() + 16).append('"');
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (character < 0x20) {
                        out.append(String.format(Locale.ROOT, "\\u%04x", (int) character));
                    } else {
                        out.append(character);
                    }
                }
            }
        }
        return out.append('"').toString();
    }

    private static String safeFilename(String value) {
        return value.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    private static void sendUsage(CommandSender sender) {
        sender.sendMessage("/phaseprofile arm <player>");
        sender.sendMessage("/phaseprofile mode <player> <baseline|nosetback|nomodifypacket|disabled|exempt>");
        sender.sendMessage("/phaseprofile mark <player> [label]");
        sender.sendMessage("/phaseprofile status <player>");
        sender.sendMessage("/phaseprofile stop <player>");
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        if (args.length == 1) {
            return startsWith(args[0], List.of("arm", "mode", "mark", "status", "stop"));
        }
        if (args.length == 2) {
            return startsWith(args[1], Bukkit.getOnlinePlayers().stream().map(Player::getName).sorted().toList());
        }
        if (args.length == 3 && args[0].equalsIgnoreCase("mode")) {
            return startsWith(args[2], Arrays.stream(GrimMode.values()).map(mode -> mode.id).toList());
        }
        return Collections.emptyList();
    }

    private static List<String> startsWith(String prefix, List<String> values) {
        String lower = prefix.toLowerCase(Locale.ROOT);
        return values.stream().filter(value -> value.toLowerCase(Locale.ROOT).startsWith(lower)).toList();
    }

    private enum GrimMode {
        BASELINE("baseline", null),
        NO_SETBACK("nosetback", "grim.nosetback"),
        NO_MODIFY_PACKET("nomodifypacket", "grim.nomodifypacket"),
        DISABLED("disabled", "grim.disabled"),
        EXEMPT("exempt", "grim.exempt");

        private final String id;
        private final String permissionNode;

        GrimMode(String id, String permissionNode) {
            this.id = id;
            this.permissionNode = permissionNode;
        }

        private static GrimMode parse(String value) {
            return Arrays.stream(values())
                    .filter(mode -> mode.id.equalsIgnoreCase(value))
                    .findFirst()
                    .orElse(null);
        }
    }

    private static final class Session {
        private final UUID playerId;
        private final String playerName;
        private final Path path;
        private final BufferedWriter writer;
        private final EnumMap<SetbackClassifier.Classification, Integer> classificationCounts =
                new EnumMap<>(SetbackClassifier.Classification.class);
        private GrimMode mode = GrimMode.BASELINE;
        private GrimMode previousMode = GrimMode.BASELINE;
        private Frame lastFrame;
        private Frame lastMountedFrame;
        private Frame trialBaseline;
        private long trialArmedTick = -1L;
        private boolean vehicleExitObserved;
        private boolean teleportObserved;
        private boolean classificationPending;

        private Session(UUID playerId, String playerName, Path path, BufferedWriter writer) {
            this.playerId = playerId;
            this.playerName = playerName;
            this.path = path;
            this.writer = writer;
        }

        private void resetTrial(Frame frame, long tick) {
            trialBaseline = frame;
            trialArmedTick = tick;
            vehicleExitObserved = false;
            teleportObserved = false;
            classificationPending = false;
        }

        private boolean isTrialWindowOpen(long tick) {
            long age = ticksSinceMark(tick);
            return age >= 0L && age <= TRIAL_WINDOW_TICKS;
        }

        private long ticksSinceMark(long tick) {
            return trialArmedTick < 0L ? -1L : tick - trialArmedTick;
        }

        private void writeFrame(long tick, String type, Frame frame) {
            write(tick, type, frame.toJson());
        }

        private synchronized void write(long tick, String type, String fieldsObject) {
            try {
                String fields = fieldsObject.length() <= 2
                        ? ""
                        : "," + fieldsObject.substring(1, fieldsObject.length() - 1);
                writer.write("{\"tick\":" + tick
                        + ",\"time\":" + System.currentTimeMillis()
                        + ",\"type\":" + quote(type)
                        + fields
                        + "}\n");
                writer.flush();
            } catch (IOException error) {
                throw new IllegalStateException("Unable to write profiler session for " + playerName, error);
            }
        }
    }

    private record Frame(
            Location playerLocation,
            Vector playerVelocity,
            boolean onGround,
            boolean mounted,
            UUID vehicleId,
            String vehicleType,
            Location vehicleLocation,
            Vector vehicleVelocity,
            int passengerCount
    ) {
        private static Frame capture(Player player) {
            Entity vehicle = player.getVehicle();
            return new Frame(
                    player.getLocation().clone(),
                    player.getVelocity().clone(),
                    player.isOnGround(),
                    vehicle != null,
                    vehicle == null ? null : vehicle.getUniqueId(),
                    vehicle == null ? null : vehicle.getType().name(),
                    vehicle == null ? null : vehicle.getLocation().clone(),
                    vehicle == null ? null : vehicle.getVelocity().clone(),
                    vehicle == null ? 0 : vehicle.getPassengers().size()
            );
        }

        private String toJson() {
            Map<String, String> fields = new HashMap<>();
            fields.put("playerLocation", quote(location(playerLocation)));
            fields.put("playerVelocity", quote(vector(playerVelocity)));
            fields.put("onGround", Boolean.toString(onGround));
            fields.put("mounted", Boolean.toString(mounted));
            fields.put("vehicleId", vehicleId == null ? "null" : quote(vehicleId.toString()));
            fields.put("vehicleType", vehicleType == null ? "null" : quote(vehicleType));
            fields.put("vehicleLocation", vehicleLocation == null ? "null" : quote(location(vehicleLocation)));
            fields.put("vehicleVelocity", vehicleVelocity == null ? "null" : quote(vector(vehicleVelocity)));
            fields.put("passengerCount", Integer.toString(passengerCount));
            return jsonObject(fields);
        }
    }
}
