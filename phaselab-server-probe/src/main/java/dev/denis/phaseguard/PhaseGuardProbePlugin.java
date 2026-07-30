package dev.denis.phaseguard;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.command.TabExecutor;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.event.Cancellable;
import org.bukkit.event.Event;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.event.vehicle.VehicleExitEvent;
import org.bukkit.plugin.RegisteredListener;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.BoundingBox;
import org.bukkit.util.Vector;

import java.io.BufferedWriter;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

public final class PhaseGuardProbePlugin extends JavaPlugin implements Listener, TabExecutor {
    private static final int DEFAULT_TICKS = 400;
    private static final int MIN_TICKS = 20;
    private static final int MAX_TICKS = 2400;
    private static final double POSITION_JUMP_THRESHOLD_SQUARED = 4.0D;

    private final Gson gson = new Gson();
    private final Map<UUID, ProbeSession> sessions = new ConcurrentHashMap<>();
    private long serverTick;
    private Path sessionsDirectory;

    @Override
    public void onEnable() {
        try {
            sessionsDirectory = getDataFolder().toPath().resolve("sessions");
            Files.createDirectories(sessionsDirectory);
        } catch (IOException exception) {
            throw new IllegalStateException("Could not create PhaseGuardProbe session directory", exception);
        }

        Bukkit.getPluginManager().registerEvents(this, this);
        registerPriorityStages(VehicleEnterEvent.class, "vehicle_enter");
        registerPriorityStages(VehicleExitEvent.class, "vehicle_exit");
        registerPriorityStages(PlayerInteractEntityEvent.class, "player_interact_entity");
        registerPriorityStages(PlayerTeleportEvent.class, "player_teleport");

        var command = getCommand("phaseprobe");
        if (command == null) throw new IllegalStateException("phaseprobe command missing from plugin.yml");
        command.setExecutor(this);
        command.setTabCompleter(this);

        Bukkit.getScheduler().runTaskTimer(this, this::sampleSessions, 1L, 1L);
        getLogger().info("PhaseGuardProbe enabled. Use /phaseprobe start <player> [ticks] [label].");
    }

    @Override
    public void onDisable() {
        for (ProbeSession session : new ArrayList<>(sessions.values())) {
            stopSession(session, "plugin_disable");
        }
        sessions.clear();
    }

    private <T extends Event> void registerPriorityStages(Class<T> eventClass, String eventName) {
        for (EventPriority priority : EventPriority.values()) {
            Bukkit.getPluginManager().registerEvent(
                eventClass,
                this,
                priority,
                (listener, event) -> onPriorityStage(eventName, priority, event),
                this,
                false
            );
        }
    }

    private void onPriorityStage(String eventName, EventPriority priority, Event event) {
        Player player = playerForEvent(event);
        if (player == null) return;
        ProbeSession session = sessions.get(player.getUniqueId());
        if (session == null) return;

        int eventIdentity = System.identityHashCode(event);
        boolean cancelled = event instanceof Cancellable cancellable && cancellable.isCancelled();
        String eventKey = event.getClass().getName() + ':' + eventIdentity;
        Boolean previous = session.eventCancellationState.put(eventKey, cancelled);

        Map<String, Object> row = baseRow(session, "event_priority_stage");
        row.put("event", eventName);
        row.put("event_class", event.getClass().getName());
        row.put("event_identity", eventIdentity);
        row.put("priority", priority.name());
        row.put("cancelled", cancelled);
        row.put("previous_cancelled", previous);
        row.put("cancel_transition", previous != null && !previous && cancelled);
        row.put("candidate_plugins_at_priority", candidatePlugins(event, priority));
        addEventDetails(row, event);
        write(session, row);

        if (priority == EventPriority.MONITOR) {
            session.eventCancellationState.remove(eventKey);
        }
    }

    private Player playerForEvent(Event event) {
        if (event instanceof VehicleEnterEvent enter && enter.getEntered() instanceof Player player) return player;
        if (event instanceof VehicleExitEvent exit && exit.getExited() instanceof Player player) return player;
        if (event instanceof PlayerInteractEntityEvent interact) return interact.getPlayer();
        if (event instanceof PlayerTeleportEvent teleport) return teleport.getPlayer();
        return null;
    }

    private void addEventDetails(Map<String, Object> row, Event event) {
        if (event instanceof VehicleEnterEvent enter) {
            row.put("vehicle", entitySummary(enter.getVehicle()));
            row.put("entered_uuid", enter.getEntered().getUniqueId().toString());
            row.put("entered_type", enter.getEntered().getType().name());
        } else if (event instanceof VehicleExitEvent exit) {
            row.put("vehicle", entitySummary(exit.getVehicle()));
            row.put("exited_uuid", exit.getExited().getUniqueId().toString());
            row.put("exited_type", exit.getExited().getType().name());
        } else if (event instanceof PlayerInteractEntityEvent interact) {
            row.put("target", entitySummary(interact.getRightClicked()));
            row.put("hand", interact.getHand().name());
            row.put("distance_squared", interact.getPlayer().getLocation().distanceSquared(interact.getRightClicked().getLocation()));
        } else if (event instanceof PlayerTeleportEvent teleport) {
            row.put("cause", teleport.getCause().name());
            row.put("from", locationSummary(teleport.getFrom()));
            row.put("to", locationSummary(teleport.getTo()));
        }
    }

    private List<String> candidatePlugins(Event event, EventPriority priority) {
        Set<String> plugins = new LinkedHashSet<>();
        for (RegisteredListener listener : event.getHandlers().getRegisteredListeners()) {
            if (listener.getPriority() != priority) continue;
            if (listener.getPlugin() == this) continue;
            plugins.add(listener.getPlugin().getName());
        }
        return plugins.stream().sorted().toList();
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (args.length == 0) {
            sender.sendMessage("/phaseprobe <start|stop|snapshot|listeners|status> ...");
            return true;
        }

        return switch (args[0].toLowerCase(Locale.ROOT)) {
            case "start" -> startCommand(sender, args);
            case "stop" -> stopCommand(sender, args);
            case "snapshot" -> snapshotCommand(sender, args);
            case "listeners" -> listenersCommand(sender);
            case "status" -> statusCommand(sender);
            default -> false;
        };
    }

    private boolean startCommand(CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /phaseprobe start <player> [ticks] [label]");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }

        int maxTicks = DEFAULT_TICKS;
        if (args.length >= 3) {
            try {
                maxTicks = Math.max(MIN_TICKS, Math.min(MAX_TICKS, Integer.parseInt(args[2])));
            } catch (NumberFormatException exception) {
                sender.sendMessage("Ticks must be an integer between " + MIN_TICKS + " and " + MAX_TICKS + '.');
                return true;
            }
        }
        String label = args.length >= 4 ? sanitizeLabel(String.join("-", Arrays.copyOfRange(args, 3, args.length))) : "manual";

        ProbeSession previous = sessions.remove(player.getUniqueId());
        if (previous != null) stopSession(previous, "replaced");

        String timestamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").withZone(java.time.ZoneOffset.UTC).format(Instant.now());
        Path output = sessionsDirectory.resolve(timestamp + '-' + sanitizeLabel(player.getName()) + '-' + label + ".jsonl");
        ProbeSession session = new ProbeSession(player, maxTicks, label, output, serverTick);
        sessions.put(player.getUniqueId(), session);

        Map<String, Object> row = baseRow(session, "session_start");
        row.put("max_ticks", maxTicks);
        row.put("output", output.toString());
        row.put("listener_map", listenerMap());
        row.put("initial_state", captureState(player));
        write(session, row);
        sender.sendMessage("PhaseGuard probe started for " + player.getName() + " for " + maxTicks + " ticks.");
        sender.sendMessage("Evidence: " + output);
        return true;
    }

    private boolean stopCommand(CommandSender sender, String[] args) {
        Player player = resolvePlayerArgument(sender, args, 1);
        if (player == null) return true;
        ProbeSession session = sessions.remove(player.getUniqueId());
        if (session == null) {
            sender.sendMessage("No active probe for " + player.getName());
            return true;
        }
        stopSession(session, "manual_stop");
        sender.sendMessage("Stopped probe for " + player.getName() + ". Evidence: " + session.output);
        return true;
    }

    private boolean snapshotCommand(CommandSender sender, String[] args) {
        Player player = resolvePlayerArgument(sender, args, 1);
        if (player == null) return true;
        ProbeSession session = sessions.get(player.getUniqueId());
        if (session == null) {
            sender.sendMessage("No active probe for " + player.getName());
            return true;
        }
        Map<String, Object> row = baseRow(session, "manual_snapshot");
        row.put("state", captureState(player));
        write(session, row);
        sender.sendMessage("Snapshot written for " + player.getName());
        return true;
    }

    private boolean listenersCommand(CommandSender sender) {
        Map<String, List<Map<String, Object>>> listenerMap = listenerMap();
        sender.sendMessage("Vehicle/mount listener map written to console and active probe files.");
        getLogger().info(gson.toJson(listenerMap));
        for (ProbeSession session : sessions.values()) {
            Map<String, Object> row = baseRow(session, "listener_map");
            row.put("listeners", listenerMap);
            write(session, row);
        }
        return true;
    }

    private boolean statusCommand(CommandSender sender) {
        if (sessions.isEmpty()) {
            sender.sendMessage("No active PhaseGuard probes.");
            return true;
        }
        for (ProbeSession session : sessions.values()) {
            sender.sendMessage(session.playerName + ": " + session.ageTicks + '/' + session.maxTicks + " ticks → " + session.output.getFileName());
        }
        return true;
    }

    private Player resolvePlayerArgument(CommandSender sender, String[] args, int index) {
        if (args.length > index) {
            Player player = Bukkit.getPlayerExact(args[index]);
            if (player == null) sender.sendMessage("Player not online: " + args[index]);
            return player;
        }
        if (sender instanceof Player player) return player;
        sender.sendMessage("Specify a player name.");
        return null;
    }

    private void sampleSessions() {
        serverTick++;
        for (ProbeSession session : new ArrayList<>(sessions.values())) {
            Player player = Bukkit.getPlayer(session.playerId);
            if (player == null || !player.isOnline()) {
                sessions.remove(session.playerId);
                stopSession(session, "player_offline");
                continue;
            }

            session.ageTicks++;
            Map<String, Object> current = captureState(player);
            Map<String, Object> row = baseRow(session, "probe_tick");
            row.put("state", current);
            write(session, row);

            Map<String, Object> transition = transition(session.lastState, current);
            if (!transition.isEmpty()) {
                Map<String, Object> transitionRow = baseRow(session, "probe_transition");
                transitionRow.putAll(transition);
                transitionRow.put("state", current);
                write(session, transitionRow);
            }
            session.lastState = current;

            if (session.ageTicks >= session.maxTicks) {
                sessions.remove(session.playerId);
                stopSession(session, "tick_limit");
            }
        }
    }

    private Map<String, Object> transition(Map<String, Object> previous, Map<String, Object> current) {
        if (previous == null) return Map.of("kind", "first_sample");
        Map<String, Object> transition = new LinkedHashMap<>();

        boolean previousMounted = Boolean.TRUE.equals(previous.get("mounted"));
        boolean currentMounted = Boolean.TRUE.equals(current.get("mounted"));
        if (previousMounted != currentMounted) {
            transition.put("mounted_changed", previousMounted + "->" + currentMounted);
        }

        Object previousVehicle = previous.get("vehicle_uuid");
        Object currentVehicle = current.get("vehicle_uuid");
        if (!Objects.equals(previousVehicle, currentVehicle)) {
            transition.put("vehicle_changed", String.valueOf(previousVehicle) + "->" + currentVehicle);
        }

        String previousClaim = String.valueOf(previous.get("player_claim"));
        String currentClaim = String.valueOf(current.get("player_claim"));
        if (!Objects.equals(previousClaim, currentClaim)) transition.put("player_claim_changed", previousClaim + "->" + currentClaim);

        Number px = number(previous.get("player_x"));
        Number py = number(previous.get("player_y"));
        Number pz = number(previous.get("player_z"));
        Number cx = number(current.get("player_x"));
        Number cy = number(current.get("player_y"));
        Number cz = number(current.get("player_z"));
        if (px != null && py != null && pz != null && cx != null && cy != null && cz != null) {
            double dx = cx.doubleValue() - px.doubleValue();
            double dy = cy.doubleValue() - py.doubleValue();
            double dz = cz.doubleValue() - pz.doubleValue();
            double distanceSquared = dx * dx + dy * dy + dz * dz;
            if (distanceSquared >= POSITION_JUMP_THRESHOLD_SQUARED) {
                transition.put("player_position_jump", Math.sqrt(distanceSquared));
                transition.put("player_delta", List.of(dx, dy, dz));
            }
        }

        if (!Objects.equals(previous.get("player_collision_signature"), current.get("player_collision_signature"))) {
            transition.put("player_collision_changed", previous.get("player_collision_signature") + "->" + current.get("player_collision_signature"));
        }
        if (!Objects.equals(previous.get("vehicle_collision_signature"), current.get("vehicle_collision_signature"))) {
            transition.put("vehicle_collision_changed", previous.get("vehicle_collision_signature") + "->" + current.get("vehicle_collision_signature"));
        }
        return transition;
    }

    private Number number(Object value) {
        return value instanceof Number number ? number : null;
    }

    private Map<String, Object> captureState(Player player) {
        Map<String, Object> state = new LinkedHashMap<>();
        Location playerLocation = player.getLocation();
        Vector playerVelocity = player.getVelocity();
        Entity vehicle = player.getVehicle();

        state.put("player_uuid", player.getUniqueId().toString());
        state.put("player_name", player.getName());
        state.put("player_x", playerLocation.getX());
        state.put("player_y", playerLocation.getY());
        state.put("player_z", playerLocation.getZ());
        state.put("player_yaw", playerLocation.getYaw());
        state.put("player_pitch", playerLocation.getPitch());
        state.put("player_velocity", vectorSummary(playerVelocity));
        state.put("player_on_ground", player.isOnGround());
        state.put("player_game_mode", player.getGameMode().name());
        state.put("player_fire_ticks", player.getFireTicks());
        state.put("player_freeze_ticks", player.getFreezeTicks());
        state.put("player_fall_distance", player.getFallDistance());
        state.put("player_health", player.getHealth());
        state.put("player_claim", claimTagAt(playerLocation));
        Map<String, Object> playerCollision = collisionSummary(player, playerLocation);
        state.put("player_collision", playerCollision);
        state.put("player_collision_signature", collisionSignature(playerCollision));

        state.put("mounted", vehicle != null);
        state.put("vehicle_uuid", vehicle == null ? null : vehicle.getUniqueId().toString());
        state.put("vehicle_type", vehicle == null ? null : vehicle.getType().name());
        if (vehicle != null) {
            Location vehicleLocation = vehicle.getLocation();
            state.put("vehicle_x", vehicleLocation.getX());
            state.put("vehicle_y", vehicleLocation.getY());
            state.put("vehicle_z", vehicleLocation.getZ());
            state.put("vehicle_velocity", vectorSummary(vehicle.getVelocity()));
            state.put("vehicle_on_ground", vehicle.isOnGround());
            state.put("vehicle_valid", vehicle.isValid());
            state.put("vehicle_dead", vehicle.isDead());
            state.put("vehicle_fire_ticks", vehicle.getFireTicks());
            state.put("vehicle_passengers", vehicle.getPassengers().stream().map(Entity::getUniqueId).map(UUID::toString).toList());
            state.put("vehicle_claim", claimTagAt(vehicleLocation));
            state.put("player_vehicle_distance_squared", playerLocation.distanceSquared(vehicleLocation));
            Map<String, Object> vehicleCollision = collisionSummary(vehicle, vehicleLocation);
            state.put("vehicle_collision", vehicleCollision);
            state.put("vehicle_collision_signature", collisionSignature(vehicleCollision));
        } else {
            state.put("vehicle_claim", null);
            state.put("vehicle_collision_signature", null);
        }
        return state;
    }

    private Map<String, Object> collisionSummary(Entity entity, Location location) {
        Map<String, Object> summary = new LinkedHashMap<>();
        BoundingBox box = entity.getBoundingBox();
        int minX = (int) Math.floor(box.getMinX() + 1.0E-7D);
        int maxX = (int) Math.floor(box.getMaxX() - 1.0E-7D);
        int minY = (int) Math.floor(box.getMinY() + 1.0E-7D);
        int maxY = (int) Math.floor(box.getMaxY() - 1.0E-7D);
        int minZ = (int) Math.floor(box.getMinZ() + 1.0E-7D);
        int maxZ = (int) Math.floor(box.getMaxZ() - 1.0E-7D);

        int solid = 0;
        int water = 0;
        int lava = 0;
        Set<String> materials = new LinkedHashSet<>();
        World world = location.getWorld();
        if (world != null) {
            for (int x = minX; x <= maxX; x++) {
                for (int y = minY; y <= maxY; y++) {
                    for (int z = minZ; z <= maxZ; z++) {
                        Material material = world.getBlockAt(x, y, z).getType();
                        materials.add(material.name());
                        if (material.isSolid()) solid++;
                        if (material == Material.WATER) water++;
                        if (material == Material.LAVA) lava++;
                    }
                }
            }
        }
        summary.put("solid_blocks", solid);
        summary.put("water_blocks", water);
        summary.put("lava_blocks", lava);
        summary.put("materials", materials.stream().sorted().toList());
        summary.put("feet", location.getBlock().getType().name());
        summary.put("below", location.clone().subtract(0.0D, 1.0D, 0.0D).getBlock().getType().name());
        summary.put("head", location.clone().add(0.0D, Math.max(1.0D, box.getHeight() * 0.75D), 0.0D).getBlock().getType().name());
        return summary;
    }

    private String collisionSignature(Map<String, Object> collision) {
        return collision.get("solid_blocks") + ":" + collision.get("water_blocks") + ":" + collision.get("lava_blocks") + ":" + collision.get("materials");
    }

    private String claimTagAt(Location location) {
        try {
            Class<?> locationClass = Class.forName("dev.kitteh.factions.FLocation");
            Constructor<?> constructor = locationClass.getConstructor(String.class, int.class, int.class);
            Object factionLocation = constructor.newInstance(location.getWorld().getName(), location.getChunk().getX(), location.getChunk().getZ());
            Class<?> boardClass = Class.forName("dev.kitteh.factions.Board");
            Object board = boardClass.getMethod("board").invoke(null);
            Object faction = boardClass.getMethod("factionAt", locationClass).invoke(board, factionLocation);
            return String.valueOf(faction.getClass().getMethod("tag").invoke(faction));
        } catch (ReflectiveOperationException | RuntimeException exception) {
            return "UNKNOWN:" + exception.getClass().getSimpleName();
        }
    }

    private Map<String, List<Map<String, Object>>> listenerMap() {
        Map<String, List<Map<String, Object>>> map = new LinkedHashMap<>();
        map.put("VehicleEnterEvent", registeredListeners(VehicleEnterEvent.getHandlerList().getRegisteredListeners()));
        map.put("VehicleExitEvent", registeredListeners(VehicleExitEvent.getHandlerList().getRegisteredListeners()));
        map.put("PlayerInteractEntityEvent", registeredListeners(PlayerInteractEntityEvent.getHandlerList().getRegisteredListeners()));
        map.put("PlayerTeleportEvent", registeredListeners(PlayerTeleportEvent.getHandlerList().getRegisteredListeners()));
        return map;
    }

    private List<Map<String, Object>> registeredListeners(RegisteredListener[] listeners) {
        return Arrays.stream(listeners)
            .filter(listener -> listener.getPlugin() != this)
            .sorted(Comparator.comparing((RegisteredListener listener) -> listener.getPriority().ordinal()).thenComparing(listener -> listener.getPlugin().getName()))
            .map(listener -> {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("plugin", listener.getPlugin().getName());
                row.put("priority", listener.getPriority().name());
                row.put("ignore_cancelled", listener.isIgnoringCancelled());
                row.put("listener_class", listener.getListener().getClass().getName());
                return row;
            })
            .toList();
    }

    private Map<String, Object> entitySummary(Entity entity) {
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("uuid", entity.getUniqueId().toString());
        summary.put("type", entity.getType().name());
        summary.put("location", locationSummary(entity.getLocation()));
        summary.put("velocity", vectorSummary(entity.getVelocity()));
        summary.put("valid", entity.isValid());
        summary.put("dead", entity.isDead());
        summary.put("passengers", entity.getPassengers().stream().map(Entity::getUniqueId).map(UUID::toString).toList());
        return summary;
    }

    private Map<String, Object> locationSummary(Location location) {
        if (location == null) return Map.of("null", true);
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("world", location.getWorld() == null ? null : location.getWorld().getName());
        summary.put("x", location.getX());
        summary.put("y", location.getY());
        summary.put("z", location.getZ());
        summary.put("yaw", location.getYaw());
        summary.put("pitch", location.getPitch());
        summary.put("chunk_x", location.getChunk().getX());
        summary.put("chunk_z", location.getChunk().getZ());
        summary.put("claim", location.getWorld() == null ? null : claimTagAt(location));
        return summary;
    }

    private Map<String, Object> vectorSummary(Vector vector) {
        return Map.of("x", vector.getX(), "y", vector.getY(), "z", vector.getZ(), "length", vector.length());
    }

    private Map<String, Object> baseRow(ProbeSession session, String type) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("ts", Instant.now().toString());
        row.put("type", type);
        row.put("session_id", session.sessionId);
        row.put("label", session.label);
        row.put("server_tick", serverTick);
        row.put("age_ticks", session.ageTicks);
        row.put("player_uuid", session.playerId.toString());
        row.put("player_name", session.playerName);
        return row;
    }

    private synchronized void write(ProbeSession session, Map<String, ?> fields) {
        JsonObject object = new JsonObject();
        fields.forEach((key, value) -> object.add(key, gson.toJsonTree(value)));
        try (BufferedWriter writer = Files.newBufferedWriter(session.output, StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            writer.write(gson.toJson(object));
            writer.newLine();
        } catch (IOException exception) {
            getLogger().warning("Could not write probe evidence: " + exception.getMessage());
        }
    }

    private void stopSession(ProbeSession session, String reason) {
        Map<String, Object> row = baseRow(session, "session_stop");
        row.put("reason", reason);
        Player player = Bukkit.getPlayer(session.playerId);
        row.put("final_state", player == null ? Map.of("online", false) : captureState(player));
        write(session, row);
    }

    private String sanitizeLabel(String value) {
        String sanitized = value.replaceAll("[^A-Za-z0-9._-]", "_");
        return sanitized.isBlank() ? "probe" : sanitized.substring(0, Math.min(80, sanitized.length()));
    }

    @Override
    public List<String> onTabComplete(CommandSender sender, Command command, String alias, String[] args) {
        if (args.length == 1) return prefixMatches(args[0], List.of("start", "stop", "snapshot", "listeners", "status"));
        if (args.length == 2 && Set.of("start", "stop", "snapshot").contains(args[0].toLowerCase(Locale.ROOT))) {
            return prefixMatches(args[1], Bukkit.getOnlinePlayers().stream().map(Player::getName).sorted().toList());
        }
        return Collections.emptyList();
    }

    private List<String> prefixMatches(String prefix, List<String> values) {
        String lower = prefix.toLowerCase(Locale.ROOT);
        return values.stream().filter(value -> value.toLowerCase(Locale.ROOT).startsWith(lower)).toList();
    }

    private static final class ProbeSession {
        private final String sessionId = UUID.randomUUID().toString();
        private final UUID playerId;
        private final String playerName;
        private final int maxTicks;
        private final String label;
        private final Path output;
        private final long startedServerTick;
        private final Map<String, Boolean> eventCancellationState = new ConcurrentHashMap<>();
        private int ageTicks;
        private Map<String, Object> lastState;

        private ProbeSession(Player player, int maxTicks, String label, Path output, long startedServerTick) {
            this.playerId = player.getUniqueId();
            this.playerName = player.getName();
            this.maxTicks = maxTicks;
            this.label = label;
            this.output = output;
            this.startedServerTick = startedServerTick;
        }
    }
}
