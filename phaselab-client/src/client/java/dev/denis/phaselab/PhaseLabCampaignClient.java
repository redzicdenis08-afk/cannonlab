package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.lwjgl.glfw.GLFW;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.UUID;

/**
 * Bounded ordinary-input campaign runner for the ExtremeCraft Test Lab.
 *
 * This class does not construct movement packets and does not directly modify
 * position, velocity, collision, bounding boxes, or server state.
 */
public final class PhaseLabCampaignClient implements ClientModInitializer {
    private static final String VERSION = "6.3.0";
    private static final String ALLOWED_HOST = "extremecraft.net";
    private static final int ALLOWED_PORT = 25565;
    private static final int MAX_TICKS = 360;
    private static final double MAX_TRAVEL = 24.0D;
    private static final double CROSSING_MARGIN = 0.15D;
    private static final double CORRIDOR_MARGIN = 0.10D;
    private static final int PERSIST_TICKS = 8;
    private static final double CORRECTION_STEP = 0.35D;
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");

    private static final String[] PROFILES = {
        "FULL_PRESSURE_MATRIX",
        "PULSE_STRESS",
        "STEERING_STRESS",
        "BRAKE_REVERSAL",
        "FORWARD_BACK_STRESS",
        "IDLE_CONTROL"
    };

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "campaign")
    );

    private static KeyMapping profileKey;
    private static KeyMapping runKey;
    private static int profileIndex;
    private static boolean running;
    private static int tick;
    private static Object lastConnection;

    private static Barrier barrier;
    private static Entity vehicle;
    private static int vehicleId = -1;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static double previousProgress;
    private static double maxProgress;
    private static double maxCorridorProgress;
    private static double maxPlayerTravel;
    private static double maxVehicleTravel;
    private static double maxLateralOffset;
    private static int corridorCrossingTicks;
    private static int maxCorridorCrossingTicks;
    private static int anyCrossingTicks;
    private static int maxAnyCrossingTicks;
    private static int correctionCandidates;
    private static double maxBackwardStep;
    private static int dismountTick = -1;
    private static boolean sawCollision;
    private static boolean sawWater;
    private static boolean sawLava;
    private static String runId;
    private static String runServer;
    private static BufferedWriter archiveWriter;
    private static BufferedWriter latestWriter;
    private static Path summaryPath;

    private static final String HEADER =
        "utc_timestamp,run_id,version,profile,tick,event,detail,server_address," +
        "target_x,target_y,target_z,barrier_axis,barrier_threshold,barrier_direction," +
        "progress,max_progress,lateral_offset,within_corridor,corridor_crossing_ticks,max_corridor_crossing_ticks," +
        "any_crossing_ticks,max_any_crossing_ticks,correction_candidates,max_backward_step," +
        "player_x,player_y,player_z,player_dx,player_dy,player_dz,mounted,horizontal_collision,in_water,in_lava," +
        "vehicle_id,vehicle_type,vehicle_x,vehicle_y,vehicle_z,vehicle_dx,vehicle_dy,vehicle_dz,vehicle_box_clear," +
        "key_forward,key_back,key_left,key_right,key_shift";

    @Override
    public void onInitializeClient() {
        profileKey = register("key.phaselab.campaign_profile", GLFW.GLFW_KEY_F5);
        runKey = register("key.phaselab.campaign_run", GLFW.GLFW_KEY_F11);
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabCampaignClient::clientTick);
    }

    private static KeyMapping register(String id, int key) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(id, InputConstants.Type.KEYSYM, key, CATEGORY));
    }

    private static void clientTick(Minecraft client) {
        Object connection = client.getConnection();
        if (connection != lastConnection) {
            if (running) {
                finish(client, client.player, "CONNECTION_CHANGED", "connection_changed", false);
            } else {
                stopKeys(client);
                closeOutputs();
            }
            lastConnection = connection;
            barrier = null;
        }

        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            if (running) {
                finish(client, player, "WORLD_LEFT", "player_or_level_unavailable", false);
            }
            return;
        }

        while (profileKey.consumeClick()) {
            if (running) {
                message(player, "F11 aborts before changing profile.", false);
            } else if (!isAllowedServer(client)) {
                message(player, "LOCKED: join " + ALLOWED_HOST + ":" + ALLOWED_PORT + ".", false);
            } else {
                profileIndex = (profileIndex + 1) % PROFILES.length;
                message(player, "Campaign profile " + (profileIndex + 1) + "/" + PROFILES.length + ": " + profile(), true);
            }
        }

        while (runKey.consumeClick()) {
            if (running) {
                finish(client, player, "ABORTED", "manual_abort", true);
            } else {
                start(client, player);
            }
        }

        if (running) {
            runTick(client, player);
        }
    }

    private static void start(Minecraft client, LocalPlayer player) {
        if (!isAllowedServer(client)) {
            message(player, "LOCKED: campaign only runs on " + ALLOWED_HOST + ":" + ALLOWED_PORT + ".", false);
            return;
        }
        Entity currentVehicle = player.getVehicle();
        if (currentVehicle == null || !player.isPassenger()) {
            message(player, "Mount the test vehicle first.", false);
            return;
        }

        Barrier detected = detectBarrier(client);
        if (detected == null) {
            message(player, "Aim at a vertical solid wall face, then press F11.", false);
            return;
        }
        if (!isTargetCollidable(client, detected)) {
            message(player, "INVALID TARGET: selected block has no collision.", false);
            return;
        }
        if (!targetOverlapsVehicleHeight(client, currentVehicle, detected)) {
            message(player, "INVALID HEIGHT: aim at the lowest blocking row.", false);
            return;
        }
        if (!detected.withinCorridor(currentVehicle.position(), 0.50D)) {
            message(player, "INVALID ALIGNMENT: center the vehicle on the selected block.", false);
            return;
        }
        double initialProgress = detected.progress(currentVehicle.position());
        if (initialProgress >= -0.05D) {
            message(player, "Vehicle must start on the front side of the wall.", false);
            return;
        }

        barrier = detected;
        vehicle = currentVehicle;
        vehicleId = currentVehicle.getId();
        playerStart = player.position();
        vehicleStart = currentVehicle.position();
        previousProgress = initialProgress;
        maxProgress = initialProgress;
        maxCorridorProgress = initialProgress;
        maxPlayerTravel = 0.0D;
        maxVehicleTravel = 0.0D;
        maxLateralOffset = barrier.lateralOffset(currentVehicle.position());
        corridorCrossingTicks = 0;
        maxCorridorCrossingTicks = 0;
        anyCrossingTicks = 0;
        maxAnyCrossingTicks = 0;
        correctionCandidates = 0;
        maxBackwardStep = 0.0D;
        dismountTick = -1;
        sawCollision = false;
        sawWater = false;
        sawLava = false;
        tick = 0;
        runId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        runServer = currentServerAddress(client);

        if (!openOutputs(player)) {
            return;
        }
        running = true;
        writeRow("START", "geometry_validated;initial_progress=" + number(initialProgress), player);
        message(player, "CAMPAIGN RUNNING " + profile() + " | F11 aborts.", false);
    }

    private static void runTick(Minecraft client, LocalPlayer player) {
        tick++;
        applyProfile(client);
        updateMetrics(player);
        writeRow("TICK", "active", player);

        if (!isAllowedServer(client)) {
            finish(client, player, "LOCK_ABORT", "server_lock_lost", true);
            return;
        }
        if (maxPlayerTravel > MAX_TRAVEL || maxVehicleTravel > MAX_TRAVEL) {
            finish(client, player, "SAFETY_ABORT", "travel_cap_exceeded", true);
            return;
        }
        if (tick >= profileDuration()) {
            finish(client, player, classify(), "profile_complete", true);
        }
    }

    private static void applyProfile(Minecraft client) {
        setKeys(client, false, false, false, false, false);
        switch (profile()) {
            case "FULL_PRESSURE_MATRIX" -> {
                if (tick <= 50) {
                    client.options.keyUp.setDown(true);
                } else if (tick >= 61 && tick <= 105) {
                    client.options.keyUp.setDown(tick % 4 < 3);
                } else if (tick >= 116 && tick <= 160) {
                    client.options.keyUp.setDown(tick % 8 < 6);
                } else if (tick >= 171 && tick <= 215) {
                    client.options.keyUp.setDown(true);
                    client.options.keyLeft.setDown((tick / 5) % 2 == 0);
                    client.options.keyRight.setDown((tick / 5) % 2 != 0);
                } else if (tick >= 226 && tick <= 270) {
                    boolean forward = (tick / 6) % 2 == 0;
                    client.options.keyUp.setDown(forward);
                    client.options.keyDown.setDown(!forward);
                } else if (tick >= 281 && tick <= 315) {
                    client.options.keyUp.setDown(true);
                }
            }
            case "PULSE_STRESS" -> client.options.keyUp.setDown(tick <= 300 && pulseState(tick));
            case "STEERING_STRESS" -> {
                client.options.keyUp.setDown(tick <= 300);
                int window = tick < 100 ? 3 : (tick < 200 ? 6 : 12);
                client.options.keyLeft.setDown(tick <= 300 && (tick / window) % 2 == 0);
                client.options.keyRight.setDown(tick <= 300 && (tick / window) % 2 != 0);
            }
            case "BRAKE_REVERSAL" -> {
                int phase = tick % 80;
                client.options.keyUp.setDown(tick <= 300 && phase < 50);
                client.options.keyDown.setDown(tick <= 300 && phase >= 50 && phase < 68);
            }
            case "FORWARD_BACK_STRESS" -> {
                int window = tick < 120 ? 4 : (tick < 240 ? 8 : 16);
                boolean forward = (tick / window) % 2 == 0;
                client.options.keyUp.setDown(tick <= 320 && forward);
                client.options.keyDown.setDown(tick <= 320 && !forward);
            }
            case "IDLE_CONTROL" -> {
            }
            default -> {
            }
        }
    }

    private static boolean pulseState(int currentTick) {
        if (currentTick < 100) {
            return currentTick % 3 != 0;
        }
        if (currentTick < 200) {
            return currentTick % 7 < 5;
        }
        return currentTick % 15 < 11;
    }

    private static int profileDuration() {
        return "IDLE_CONTROL".equals(profile()) ? 140 : 340;
    }

    private static void updateMetrics(LocalPlayer player) {
        Entity current = player.getVehicle();
        Entity observed = current != null ? current : vehicle;
        if (!player.isPassenger() && dismountTick < 0) {
            dismountTick = tick;
            writeRow("DISMOUNT", "tick=" + tick, player);
        }
        if (current != null && current.getId() != vehicleId) {
            writeRow("VEHICLE_CHANGED", "from=" + vehicleId + ";to=" + current.getId(), player);
            vehicle = current;
            vehicleId = current.getId();
            observed = current;
        }

        maxPlayerTravel = Math.max(maxPlayerTravel, player.position().distanceTo(playerStart));
        sawCollision |= player.horizontalCollision;
        sawWater |= player.isInWater();
        sawLava |= player.isInLava();
        if (observed == null) {
            return;
        }

        Vec3 pos = observed.position();
        maxVehicleTravel = Math.max(maxVehicleTravel, pos.distanceTo(vehicleStart));
        double progress = barrier.progress(pos);
        double lateral = barrier.lateralOffset(pos);
        boolean inCorridor = barrier.withinCorridor(pos, CORRIDOR_MARGIN);
        maxProgress = Math.max(maxProgress, progress);
        maxLateralOffset = Math.max(maxLateralOffset, lateral);
        if (inCorridor) {
            maxCorridorProgress = Math.max(maxCorridorProgress, progress);
        }

        double step = progress - previousProgress;
        if (step < -CORRECTION_STEP) {
            correctionCandidates++;
            maxBackwardStep = Math.max(maxBackwardStep, -step);
            writeRow("CORRECTION_CANDIDATE", "backward_step=" + number(-step), player);
        }
        previousProgress = progress;

        boolean boxClear = observed.level().noCollision(observed, observed.getBoundingBox().deflate(0.001D));
        sawCollision |= !boxClear;
        sawWater |= observed.isInWater();
        sawLava |= observed.isInLava();

        if (progress > CROSSING_MARGIN) {
            anyCrossingTicks++;
            maxAnyCrossingTicks = Math.max(maxAnyCrossingTicks, anyCrossingTicks);
            if (inCorridor) {
                corridorCrossingTicks++;
                maxCorridorCrossingTicks = Math.max(maxCorridorCrossingTicks, corridorCrossingTicks);
            } else {
                corridorCrossingTicks = 0;
            }
        } else {
            anyCrossingTicks = 0;
            corridorCrossingTicks = 0;
        }
    }

    private static String classify() {
        if (maxCorridorCrossingTicks >= PERSIST_TICKS) {
            return "CAMPAIGN_CANDIDATE";
        }
        if (maxAnyCrossingTicks >= PERSIST_TICKS) {
            return "LATERAL_ESCAPE";
        }
        if (maxCorridorProgress > CROSSING_MARGIN) {
            return "CORRIDOR_TRANSIENT";
        }
        if (correctionCandidates > 0) {
            return "CORRECTED_OR_SETBACK";
        }
        if (dismountTick >= 0) {
            return "UNEXPECTED_DISMOUNT";
        }
        if (maxVehicleTravel < 0.25D) {
            return "NO_MOVEMENT";
        }
        return "BLOCKED_OR_REJECTED";
    }

    private static void finish(Minecraft client, LocalPlayer player, String verdict, String reason, boolean show) {
        stopKeys(client);
        if (running) {
            writeRow(
                "FINISH",
                "verdict=" + verdict
                    + ";reason=" + reason
                    + ";max_progress=" + number(maxProgress)
                    + ";max_corridor_progress=" + number(maxCorridorProgress)
                    + ";max_corridor_crossing_ticks=" + maxCorridorCrossingTicks
                    + ";max_any_crossing_ticks=" + maxAnyCrossingTicks
                    + ";corrections=" + correctionCandidates
                    + ";dismount_tick=" + dismountTick,
                player
            );
            writeSummary(verdict, reason);
        }
        closeOutputs();
        running = false;
        tick = 0;
        if (show && player != null) {
            message(player, "CAMPAIGN RESULT: " + verdict + " | " + reason, false);
            profileIndex = (profileIndex + 1) % PROFILES.length;
            message(player, "Next campaign: " + profile(), true);
        }
    }

    private static Barrier detectBarrier(Minecraft client) {
        if (!(client.hitResult instanceof BlockHitResult hit)) {
            return null;
        }
        Direction face = hit.getDirection();
        BlockPos pos = hit.getBlockPos();
        return switch (face) {
            case WEST -> new Barrier(pos, 'X', pos.getX() + 1.0D, 1.0D);
            case EAST -> new Barrier(pos, 'X', pos.getX(), -1.0D);
            case NORTH -> new Barrier(pos, 'Z', pos.getZ() + 1.0D, 1.0D);
            case SOUTH -> new Barrier(pos, 'Z', pos.getZ(), -1.0D);
            default -> null;
        };
    }

    private static boolean isTargetCollidable(Minecraft client, Barrier selected) {
        var state = client.level.getBlockState(selected.pos());
        VoxelShape shape = state.getCollisionShape(client.level, selected.pos());
        return !shape.isEmpty();
    }

    private static boolean targetOverlapsVehicleHeight(Minecraft client, Entity currentVehicle, Barrier selected) {
        var state = client.level.getBlockState(selected.pos());
        VoxelShape shape = state.getCollisionShape(client.level, selected.pos());
        if (shape.isEmpty()) {
            return false;
        }
        AABB vehicleBox = currentVehicle.getBoundingBox();
        for (AABB local : shape.toAabbs()) {
            AABB world = local.move(selected.pos());
            if (vehicleBox.maxY > world.minY + 0.01D && vehicleBox.minY < world.maxY - 0.01D) {
                return true;
            }
        }
        return false;
    }

    private static boolean isAllowedServer(Minecraft client) {
        String address = currentServerAddress(client).trim().toLowerCase(Locale.ROOT);
        if (address.startsWith("minecraft://")) {
            address = address.substring("minecraft://".length());
        }
        int slash = address.indexOf('/');
        if (slash >= 0) {
            address = address.substring(0, slash);
        }
        String host = address;
        int port = ALLOWED_PORT;
        int first = address.indexOf(':');
        int last = address.lastIndexOf(':');
        if (first > 0 && first == last) {
            host = address.substring(0, first);
            try {
                port = Integer.parseInt(address.substring(first + 1));
            } catch (NumberFormatException exception) {
                return false;
            }
        }
        while (host.endsWith(".")) {
            host = host.substring(0, host.length() - 1);
        }
        return ALLOWED_HOST.equals(host) && port == ALLOWED_PORT;
    }

    private static String currentServerAddress(Minecraft client) {
        var server = client.getCurrentServer();
        return server == null || server.ip == null ? "" : server.ip;
    }

    private static void setKeys(Minecraft client, boolean forward, boolean back, boolean left, boolean right, boolean shift) {
        client.options.keyUp.setDown(forward);
        client.options.keyDown.setDown(back);
        client.options.keyLeft.setDown(left);
        client.options.keyRight.setDown(right);
        client.options.keyShift.setDown(shift);
    }

    private static void stopKeys(Minecraft client) {
        setKeys(client, false, false, false, false, false);
    }

    private static boolean openOutputs(LocalPlayer player) {
        closeOutputs();
        Path gameDir = Minecraft.getInstance().gameDirectory.toPath();
        Path configDir = gameDir.resolve("config").resolve("phaselab");
        summaryPath = gameDir.resolve("PHASELAB_CAMPAIGN_SUMMARY.txt");
        try {
            Files.createDirectories(configDir);
            archiveWriter = Files.newBufferedWriter(
                configDir.resolve("campaign-v6.3-" + runId + ".csv"),
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            latestWriter = Files.newBufferedWriter(
                gameDir.resolve("PHASELAB_CAMPAIGN_LATEST.csv"),
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
            archiveWriter.write(HEADER);
            archiveWriter.newLine();
            latestWriter.write(HEADER);
            latestWriter.newLine();
            archiveWriter.flush();
            latestWriter.flush();
            return true;
        } catch (IOException exception) {
            closeOutputs();
            message(player, "Could not open campaign CSV: " + clean(exception.getMessage()), false);
            return false;
        }
    }

    private static void writeRow(String event, String detail, LocalPlayer player) {
        if (archiveWriter == null && latestWriter == null) {
            return;
        }
        Entity observed = player == null ? vehicle : (player.getVehicle() != null ? player.getVehicle() : vehicle);
        Vec3 playerPos = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePos = observed == null ? null : observed.position();
        Vec3 vehicleDelta = observed == null ? null : observed.getDeltaMovement();
        double progress = vehiclePos == null || barrier == null ? Double.NaN : barrier.progress(vehiclePos);
        double lateral = vehiclePos == null || barrier == null ? Double.NaN : barrier.lateralOffset(vehiclePos);
        boolean within = vehiclePos != null && barrier != null && barrier.withinCorridor(vehiclePos, CORRIDOR_MARGIN);
        boolean boxClear = observed != null && observed.level().noCollision(observed, observed.getBoundingBox().deflate(0.001D));
        Minecraft client = Minecraft.getInstance();

        String row = String.join(",",
            csv(Instant.now().toString()), csv(runId), csv(VERSION), csv(profile()), Integer.toString(tick),
            csv(event), csv(detail), csv(runServer),
            barrier == null ? "" : Integer.toString(barrier.pos().getX()),
            barrier == null ? "" : Integer.toString(barrier.pos().getY()),
            barrier == null ? "" : Integer.toString(barrier.pos().getZ()),
            barrier == null ? "" : csv(Character.toString(barrier.axis())),
            barrier == null ? "" : number(barrier.threshold()),
            barrier == null ? "" : number(barrier.direction()),
            number(progress), number(maxProgress), number(lateral), Boolean.toString(within),
            Integer.toString(corridorCrossingTicks), Integer.toString(maxCorridorCrossingTicks),
            Integer.toString(anyCrossingTicks), Integer.toString(maxAnyCrossingTicks),
            Integer.toString(correctionCandidates), number(maxBackwardStep),
            vector(playerPos, 0), vector(playerPos, 1), vector(playerPos, 2),
            vector(playerDelta, 0), vector(playerDelta, 1), vector(playerDelta, 2),
            Boolean.toString(player != null && player.isPassenger()),
            Boolean.toString(player != null && player.horizontalCollision),
            Boolean.toString(player != null && player.isInWater()),
            Boolean.toString(player != null && player.isInLava()),
            observed == null ? "" : Integer.toString(observed.getId()),
            observed == null ? "" : csv(observed.getType().toString()),
            vector(vehiclePos, 0), vector(vehiclePos, 1), vector(vehiclePos, 2),
            vector(vehicleDelta, 0), vector(vehicleDelta, 1), vector(vehicleDelta, 2),
            Boolean.toString(boxClear),
            Boolean.toString(client.options.keyUp.isDown()),
            Boolean.toString(client.options.keyDown.isDown()),
            Boolean.toString(client.options.keyLeft.isDown()),
            Boolean.toString(client.options.keyRight.isDown()),
            Boolean.toString(client.options.keyShift.isDown())
        );
        writeLine(archiveWriter, row);
        writeLine(latestWriter, row);
    }

    private static void writeLine(BufferedWriter writer, String line) {
        if (writer == null) {
            return;
        }
        try {
            writer.write(line);
            writer.newLine();
            writer.flush();
        } catch (IOException ignored) {
        }
    }

    private static void writeSummary(String verdict, String reason) {
        if (summaryPath == null) {
            return;
        }
        String text = "PhaseLab Campaign v" + VERSION + System.lineSeparator()
            + "allowed_server=" + ALLOWED_HOST + ":" + ALLOWED_PORT + System.lineSeparator()
            + "connected_server=" + clean(runServer) + System.lineSeparator()
            + "run=" + runId + System.lineSeparator()
            + "profile=" + profile() + System.lineSeparator()
            + "verdict=" + verdict + System.lineSeparator()
            + "reason=" + clean(reason) + System.lineSeparator()
            + "target=" + (barrier == null ? "none" : barrier.pos().toShortString()) + System.lineSeparator()
            + "max_player_travel=" + number(maxPlayerTravel) + System.lineSeparator()
            + "max_vehicle_travel=" + number(maxVehicleTravel) + System.lineSeparator()
            + "max_progress=" + number(maxProgress) + System.lineSeparator()
            + "max_corridor_progress=" + number(maxCorridorProgress) + System.lineSeparator()
            + "max_corridor_crossing_ticks=" + maxCorridorCrossingTicks + System.lineSeparator()
            + "max_any_crossing_ticks=" + maxAnyCrossingTicks + System.lineSeparator()
            + "max_lateral_offset=" + number(maxLateralOffset) + System.lineSeparator()
            + "correction_candidates=" + correctionCandidates + System.lineSeparator()
            + "max_backward_step=" + number(maxBackwardStep) + System.lineSeparator()
            + "dismount_tick=" + dismountTick + System.lineSeparator()
            + "collision=" + sawCollision + System.lineSeparator()
            + "water=" + sawWater + System.lineSeparator()
            + "lava=" + sawLava + System.lineSeparator()
            + "note=CAMPAIGN_CANDIDATE is client-observed evidence and still requires persistence verification."
            + System.lineSeparator();
        try {
            Files.writeString(
                summaryPath,
                text,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
        } catch (IOException ignored) {
        }
    }

    private static void closeOutputs() {
        archiveWriter = closeWriter(archiveWriter);
        latestWriter = closeWriter(latestWriter);
    }

    private static BufferedWriter closeWriter(BufferedWriter writer) {
        if (writer != null) {
            try {
                writer.flush();
                writer.close();
            } catch (IOException ignored) {
            }
        }
        return null;
    }

    private static String profile() {
        return PROFILES[profileIndex];
    }

    private static String vector(Vec3 value, int index) {
        if (value == null) {
            return "";
        }
        return number(index == 0 ? value.x : (index == 1 ? value.y : value.z));
    }

    private static String number(double value) {
        return Double.isFinite(value) ? String.format(Locale.ROOT, "%.6f", value) : "";
    }

    private static String clean(String value) {
        return value == null ? "" : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static String csv(String value) {
        String safe = value == null ? "" : value.replace("\"", "\"\"");
        return "\"" + safe + "\"";
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }

    private record Barrier(BlockPos pos, char axis, double threshold, double direction) {
        double progress(Vec3 position) {
            double coordinate = axis == 'X' ? position.x : position.z;
            return direction * (coordinate - threshold);
        }

        double lateralOffset(Vec3 position) {
            double center = axis == 'X' ? pos.getZ() + 0.5D : pos.getX() + 0.5D;
            double coordinate = axis == 'X' ? position.z : position.x;
            return Math.abs(coordinate - center);
        }

        boolean withinCorridor(Vec3 position, double margin) {
            return lateralOffset(position) <= 0.5D + margin;
        }
    }
}
