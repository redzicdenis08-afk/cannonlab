package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** Passive telemetry only. It never mutates movement or sends custom packets. */
public final class PhaseTelemetryClient implements ClientModInitializer {
    private static final String VERSION = "4.2.0";
    private static final double LARGE_MOVE_THRESHOLD = 0.75D;
    private static final long CORRELATION_WINDOW_NANOS = 2_000_000_000L;
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");
    private static final String[] TEST_LABELS = {
        "GENERAL", "MOUNT", "WALL_CONTACT", "WATER", "CLAIM_BORDER", "DISMOUNT", "CONTAINER"
    };
    private static final String HEADER =
        "utc_timestamp,local_timestamp,session_id,tick,segment_id,segment_label,event,detail," +
        "since_local_move_ms,handler_ms,reference_x,reference_y,reference_z," +
        "player_x,player_y,player_z,player_dx,player_dy,player_dz,yaw,pitch,health,air," +
        "on_ground,horizontal_collision,no_physics,in_water,in_lava,swimming,sneaking,sprinting," +
        "fall_flying,passenger,player_box_clear,pose,block_x,block_y,block_z,chunk_x,chunk_z,dimension," +
        "vehicle_id,vehicle_type,vehicle_x,vehicle_y,vehicle_z,vehicle_dx,vehicle_dy,vehicle_dz," +
        "vehicle_on_ground,vehicle_no_physics,vehicle_box_clear,vehicle_passengers,player_vehicle_distance";

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "telemetry")
    );
    private static KeyMapping pauseKey;
    private static KeyMapping labelKey;
    private static KeyMapping segmentKey;
    private static KeyMapping statusKey;

    private static final BufferedWriter[] WRITERS = new BufferedWriter[3];
    private static final Path[] OUTPUT_PATHS = new Path[3];
    private static Path statusPath;
    private static Path summaryPath;

    private static boolean connected;
    private static boolean recording = true;
    private static boolean segmentActive;
    private static boolean ioWarningShown;
    private static long tick;
    private static long lastStatusTick;
    private static int segmentId;
    private static int labelIndex;
    private static String sessionId;
    private static String lastEvent = "none";
    private static String lastIoError = "none";

    private static long rows;
    private static long playerPackets;
    private static long vehiclePackets;
    private static long mountEvents;
    private static long stateEvents;
    private static long testSegments;

    private static Vec3 lastPlayerPosition;
    private static Vec3 lastVehiclePosition;
    private static Vec3 lastLargeMoveTo;
    private static long lastLargeMoveNanos;
    private static int lastVehicleId = Integer.MIN_VALUE;
    private static boolean lastWater;
    private static boolean lastLava;
    private static boolean lastCollision;
    private static boolean lastNoPhysics;
    private static boolean lastSwimming;
    private static boolean lastFallFlying;
    private static String lastDimension = "unknown";

    private static boolean playerCorrectionPending;
    private static Vec3 playerCorrectionBefore;
    private static long playerCorrectionHeadNanos;
    private static boolean vehicleCorrectionPending;
    private static Vec3 vehicleCorrectionBefore;
    private static long vehicleCorrectionHeadNanos;

    @Override
    public void onInitializeClient() {
        labelKey = register("key.phaselab.test_label", GLFW.GLFW_KEY_F7);
        pauseKey = register("key.phaselab.capture_toggle", GLFW.GLFW_KEY_F8);
        segmentKey = register("key.phaselab.test_segment", GLFW.GLFW_KEY_F9);
        statusKey = register("key.phaselab.telemetry_status", GLFW.GLFW_KEY_F10);
        ClientTickEvents.END_CLIENT_TICK.register(PhaseTelemetryClient::tickClient);
    }

    private static KeyMapping register(String key, int code) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(
            key, InputConstants.Type.KEYSYM, code, CATEGORY
        ));
    }

    private static void tickClient(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            if (connected) {
                append("DISCONNECT", "player_or_level_unavailable", -1.0D, -1.0D, null, null);
                writeSummary("disconnect");
            }
            resetDisconnected();
            return;
        }

        if (!connected) {
            beginSession(player);
        }

        tick++;
        handleKeys(player);

        Vec3 current = player.position();
        Entity vehicle = player.getVehicle();
        long now = System.nanoTime();

        if (recording && lastPlayerPosition != null) {
            double moved = current.distanceTo(lastPlayerPosition);
            if (moved >= LARGE_MOVE_THRESHOLD) {
                lastLargeMoveTo = current;
                lastLargeMoveNanos = now;
                append(
                    "LOCAL_LARGE_MOVE",
                    String.format(Locale.ROOT, "tick_distance=%.3f", moved),
                    0.0D,
                    0.0D,
                    lastPlayerPosition,
                    player
                );
            }
        }
        if (lastLargeMoveNanos != 0L && now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            clearLargeMove();
        }

        if (recording) {
            detectMount(player, vehicle);
            detectState(player);
            boolean detail = segmentActive
                || player.isPassenger()
                || player.horizontalCollision
                || player.isInWater()
                || player.isInLava();
            int interval = detail ? 1 : 20;
            if (tick % interval == 0L) {
                append(
                    "SAMPLE",
                    detail ? "detail_20hz" : "idle_1hz",
                    ageOfLargeMove(now),
                    -1.0D,
                    lastLargeMoveTo,
                    player
                );
            }
        }

        lastPlayerPosition = current;
        lastVehiclePosition = vehicle == null ? null : vehicle.position();
    }

    private static void beginSession(LocalPlayer player) {
        connected = true;
        recording = true;
        segmentActive = false;
        tick = 0L;
        lastStatusTick = 0L;
        segmentId = 0;
        labelIndex = 0;
        resetCounters();
        openOutputs(player);
        initializeState(player);
        append("SESSION_START", "PhaseLab_passive_v" + VERSION, -1.0D, -1.0D, null, player);
        message(player, "Telemetry v" + VERSION + " active. F7 type, F8 pause, F9 test start/end, F10 status.", false);
        if (OUTPUT_PATHS[2] != null) {
            message(player, "Easy CSV: " + OUTPUT_PATHS[2].toAbsolutePath(), false);
        }
    }

    private static void handleKeys(LocalPlayer player) {
        while (labelKey.consumeClick()) {
            if (segmentActive) {
                message(player, "End the current test with F9 before changing type.", false);
            } else {
                labelIndex = (labelIndex + 1) % TEST_LABELS.length;
                append("TEST_LABEL", "selected=" + label(), ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
                message(player, "Test type: " + label(), true);
            }
        }

        while (pauseKey.consumeClick()) {
            if (recording) {
                append("CAPTURE_PAUSED", "manual", ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
                recording = false;
                message(player, "Telemetry paused. F8 resumes it.", false);
            } else {
                recording = true;
                append("CAPTURE_RESUMED", "manual", ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
                message(player, "Telemetry resumed.", false);
            }
        }

        while (segmentKey.consumeClick()) {
            if (!segmentActive) {
                segmentId++;
                segmentActive = true;
                append("TEST_START", "label=" + label(), ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
                message(player, "TEST " + segmentId + " START: " + label(), false);
            } else {
                append("TEST_END", "label=" + label(), ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
                segmentActive = false;
                message(player, "TEST " + segmentId + " END: " + label(), false);
            }
        }

        while (statusKey.consumeClick()) {
            append("STATUS", recording ? "recording" : "paused", ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
            writeSummary("live_status");
            message(
                player,
                "recording=" + recording
                    + " | test=" + (segmentActive ? segmentId + ":" + label() : "none")
                    + " | rows=" + rows
                    + " | playerPackets=" + playerPackets
                    + " | vehiclePackets=" + vehiclePackets,
                false
            );
            if (OUTPUT_PATHS[2] != null) {
                message(player, "Open: " + OUTPUT_PATHS[2].toAbsolutePath(), false);
            }
        }
    }

    private static String label() {
        return TEST_LABELS[labelIndex];
    }

    private static void initializeState(LocalPlayer player) {
        Entity vehicle = player.getVehicle();
        lastPlayerPosition = player.position();
        lastVehiclePosition = vehicle == null ? null : vehicle.position();
        lastVehicleId = vehicle == null ? -1 : vehicle.getId();
        lastWater = player.isInWater();
        lastLava = player.isInLava();
        lastCollision = player.horizontalCollision;
        lastNoPhysics = player.noPhysics;
        lastSwimming = player.isSwimming();
        lastFallFlying = player.isFallFlying();
        lastDimension = dimension(player);
    }

    private static void detectMount(LocalPlayer player, Entity vehicle) {
        int currentId = vehicle == null ? -1 : vehicle.getId();
        if (currentId == lastVehicleId) {
            return;
        }

        String event;
        String detail;
        if (lastVehicleId == -1 && currentId != -1) {
            event = "MOUNTED";
            detail = "vehicle_id=" + currentId + ";vehicle_type=" + vehicleType(vehicle);
        } else if (lastVehicleId != -1 && currentId == -1) {
            event = "DISMOUNTED";
            detail = "previous_vehicle_id=" + lastVehicleId;
        } else {
            event = "VEHICLE_CHANGED";
            detail = "previous_vehicle_id=" + lastVehicleId
                + ";vehicle_id=" + currentId
                + ";vehicle_type=" + vehicleType(vehicle);
        }
        append(
            event,
            detail,
            ageOfLargeMove(System.nanoTime()),
            -1.0D,
            vehicle == null ? lastVehiclePosition : vehicle.position(),
            player
        );
        lastVehicleId = currentId;
    }

    private static void detectState(LocalPlayer player) {
        List<String> changes = new ArrayList<>();
        if (player.isInWater() != lastWater) {
            lastWater = player.isInWater();
            changes.add("water=" + lastWater);
        }
        if (player.isInLava() != lastLava) {
            lastLava = player.isInLava();
            changes.add("lava=" + lastLava);
        }
        if (player.horizontalCollision != lastCollision) {
            lastCollision = player.horizontalCollision;
            changes.add("horizontal_collision=" + lastCollision);
        }
        if (player.noPhysics != lastNoPhysics) {
            lastNoPhysics = player.noPhysics;
            changes.add("no_physics=" + lastNoPhysics);
        }
        if (player.isSwimming() != lastSwimming) {
            lastSwimming = player.isSwimming();
            changes.add("swimming=" + lastSwimming);
        }
        if (player.isFallFlying() != lastFallFlying) {
            lastFallFlying = player.isFallFlying();
            changes.add("fall_flying=" + lastFallFlying);
        }
        String dimension = dimension(player);
        if (!dimension.equals(lastDimension)) {
            lastDimension = dimension;
            changes.add("dimension=" + dimension);
        }
        if (!changes.isEmpty()) {
            append("STATE_CHANGE", String.join(";", changes), ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
        }
    }

    public static void onPlayerCorrectionHead() {
        LocalPlayer player = Minecraft.getInstance().player;
        playerCorrectionPending = true;
        playerCorrectionHeadNanos = System.nanoTime();
        playerCorrectionBefore = player == null ? null : player.position();
    }

    public static void onPlayerCorrectionTail() {
        if (!playerCorrectionPending) {
            return;
        }
        playerCorrectionPending = false;
        LocalPlayer player = Minecraft.getInstance().player;
        if (player == null) {
            playerCorrectionBefore = null;
            return;
        }

        long now = System.nanoTime();
        double sinceMove = ageOfLargeMove(now);
        double handlerMs = (now - playerCorrectionHeadNanos) / 1_000_000.0D;
        boolean correlated = lastLargeMoveNanos != 0L && now - lastLargeMoveNanos <= CORRELATION_WINDOW_NANOS;
        double distance = playerCorrectionBefore == null ? -1.0D : player.position().distanceTo(playerCorrectionBefore);
        append(
            correlated ? "SERVER_SETBACK_CORRELATED" : "SERVER_POSITION_PACKET",
            String.format(Locale.ROOT, "correction_distance=%.3f", distance),
            sinceMove,
            handlerMs,
            playerCorrectionBefore,
            player
        );
        if (correlated) {
            String speed = sinceMove < 250.0D ? "FAST" : sinceMove < 1_000.0D ? "NORMAL" : "DELAYED";
            message(player, String.format(Locale.ROOT,
                "SERVER SETBACK %s after %.1f ms (%.3f blocks)", speed, sinceMove, distance
            ), false);
        }
        playerCorrectionBefore = null;
        clearLargeMove();
    }

    public static void onVehicleCorrectionHead() {
        LocalPlayer player = Minecraft.getInstance().player;
        Entity vehicle = player == null ? null : player.getVehicle();
        vehicleCorrectionPending = true;
        vehicleCorrectionHeadNanos = System.nanoTime();
        vehicleCorrectionBefore = vehicle == null ? null : vehicle.position();
    }

    public static void onVehicleCorrectionTail() {
        if (!vehicleCorrectionPending) {
            return;
        }
        vehicleCorrectionPending = false;
        LocalPlayer player = Minecraft.getInstance().player;
        if (player == null) {
            vehicleCorrectionBefore = null;
            return;
        }
        Entity vehicle = player.getVehicle();
        Vec3 after = vehicle == null ? null : vehicle.position();
        double distance = vehicleCorrectionBefore == null || after == null
            ? -1.0D
            : after.distanceTo(vehicleCorrectionBefore);
        long now = System.nanoTime();
        append(
            "SERVER_VEHICLE_CORRECTION",
            String.format(Locale.ROOT, "correction_distance=%.3f", distance),
            ageOfLargeMove(now),
            (now - vehicleCorrectionHeadNanos) / 1_000_000.0D,
            vehicleCorrectionBefore,
            player
        );
        vehicleCorrectionBefore = null;
    }

    public static void onServerOpenScreen() {
        LocalPlayer player = Minecraft.getInstance().player;
        append("SERVER_OPEN_SCREEN", "server_opened_menu", ageOfLargeMove(System.nanoTime()), -1.0D, null, player);
    }

    private static synchronized void openOutputs(LocalPlayer player) {
        closeOutputs();
        sessionId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        ioWarningShown = false;
        lastIoError = "none";

        Path configDir = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
        Path gameDir = Minecraft.getInstance().gameDirectory.toPath();
        OUTPUT_PATHS[0] = configDir.resolve("telemetry-v4.2-" + sessionId + ".csv");
        OUTPUT_PATHS[1] = configDir.resolve("PHASELAB_LATEST.csv");
        OUTPUT_PATHS[2] = gameDir.resolve("PHASELAB_LATEST.csv");
        statusPath = gameDir.resolve("PHASELAB_STATUS.txt");
        summaryPath = gameDir.resolve("PHASELAB_SUMMARY.txt");

        try {
            Files.createDirectories(configDir);
        } catch (IOException exception) {
            noteIoFailure("config_directory", exception, player);
        }

        for (int i = 0; i < WRITERS.length; i++) {
            try {
                WRITERS[i] = i == 0
                    ? Files.newBufferedWriter(
                        OUTPUT_PATHS[i], StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE
                    )
                    : Files.newBufferedWriter(
                        OUTPUT_PATHS[i], StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
                    );
                WRITERS[i].write(HEADER);
                WRITERS[i].newLine();
                WRITERS[i].flush();
            } catch (IOException exception) {
                WRITERS[i] = null;
                noteIoFailure("open_output_" + i, exception, player);
            }
        }

        if (!hasWriter()) {
            message(player, "ERROR: no telemetry CSV could be opened.", false);
        }
        writeStatus("SESSION_OPEN", player);
    }

    private static synchronized void append(
        String event,
        String detail,
        double sinceMoveMs,
        double handlerMs,
        Vec3 reference,
        LocalPlayer player
    ) {
        boolean control = event.startsWith("CAPTURE_")
            || event.startsWith("TEST_")
            || event.startsWith("SERVER_")
            || "STATUS".equals(event)
            || "DISCONNECT".equals(event);
        if ((!recording && !control) || !hasWriter()) {
            return;
        }

        Entity vehicle = player == null ? null : player.getVehicle();
        Vec3 playerPos = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePos = vehicle == null ? null : vehicle.position();
        Vec3 vehicleDelta = vehicle == null ? null : vehicle.getDeltaMovement();
        boolean playerBoxClear = player != null && player.level().noCollision(player, player.getBoundingBox().deflate(0.001D));
        boolean vehicleBoxClear = vehicle != null && vehicle.level().noCollision(vehicle, vehicle.getBoundingBox().deflate(0.001D));
        double vehicleDistance = playerPos == null || vehiclePos == null ? -1.0D : playerPos.distanceTo(vehiclePos);
        var block = player == null ? null : player.blockPosition();

        List<String> fields = new ArrayList<>();
        fields.add(csv(Instant.now().toString()));
        fields.add(csv(ZonedDateTime.now().toString()));
        fields.add(csv(sessionId));
        fields.add(Long.toString(tick));
        fields.add(Integer.toString(segmentActive ? segmentId : 0));
        fields.add(csv(segmentActive ? label() : "NONE"));
        fields.add(csv(event));
        fields.add(csv(detail));
        fields.add(number(sinceMoveMs));
        fields.add(number(handlerMs));
        addVector(fields, reference);
        addVector(fields, playerPos);
        addVector(fields, playerDelta);
        fields.add(number(player == null ? Double.NaN : player.getYRot()));
        fields.add(number(player == null ? Double.NaN : player.getXRot()));
        fields.add(number(player == null ? Double.NaN : player.getHealth()));
        fields.add(player == null ? "" : Integer.toString(player.getAirSupply()));
        fields.add(bool(player != null && player.onGround()));
        fields.add(bool(player != null && player.horizontalCollision));
        fields.add(bool(player != null && player.noPhysics));
        fields.add(bool(player != null && player.isInWater()));
        fields.add(bool(player != null && player.isInLava()));
        fields.add(bool(player != null && player.isSwimming()));
        fields.add(bool(player != null && player.isShiftKeyDown()));
        fields.add(bool(player != null && player.isSprinting()));
        fields.add(bool(player != null && player.isFallFlying()));
        fields.add(bool(player != null && player.isPassenger()));
        fields.add(bool(playerBoxClear));
        fields.add(csv(player == null ? "" : player.getPose().toString()));
        fields.add(block == null ? "" : Integer.toString(block.getX()));
        fields.add(block == null ? "" : Integer.toString(block.getY()));
        fields.add(block == null ? "" : Integer.toString(block.getZ()));
        fields.add(block == null ? "" : Integer.toString(block.getX() >> 4));
        fields.add(block == null ? "" : Integer.toString(block.getZ() >> 4));
        fields.add(csv(player == null ? "" : dimension(player)));
        fields.add(vehicle == null ? "-1" : Integer.toString(vehicle.getId()));
        fields.add(csv(vehicleType(vehicle)));
        addVector(fields, vehiclePos);
        addVector(fields, vehicleDelta);
        fields.add(bool(vehicle != null && vehicle.onGround()));
        fields.add(bool(vehicle != null && vehicle.noPhysics));
        fields.add(bool(vehicleBoxClear));
        fields.add(vehicle == null ? "0" : Integer.toString(vehicle.getPassengers().size()));
        fields.add(number(vehicleDistance));

        if (!writeAll(String.join(",", fields), player)) {
            return;
        }
        rows++;
        lastEvent = event;
        count(event);
        if (!"SAMPLE".equals(event) || tick - lastStatusTick >= 20L) {
            writeStatus(event, player);
            lastStatusTick = tick;
        }
    }

    private static boolean writeAll(String line, LocalPlayer player) {
        boolean wrote = false;
        for (int i = 0; i < WRITERS.length; i++) {
            BufferedWriter writer = WRITERS[i];
            if (writer == null) {
                continue;
            }
            try {
                writer.write(line);
                writer.newLine();
                writer.flush();
                wrote = true;
            } catch (IOException exception) {
                safeClose(writer);
                WRITERS[i] = null;
                noteIoFailure("write_output_" + i, exception, player);
            }
        }
        return wrote;
    }

    private static void count(String event) {
        if ("SERVER_SETBACK_CORRELATED".equals(event) || "SERVER_POSITION_PACKET".equals(event)) {
            playerPackets++;
        } else if ("SERVER_VEHICLE_CORRECTION".equals(event)) {
            vehiclePackets++;
        } else if ("MOUNTED".equals(event) || "DISMOUNTED".equals(event) || "VEHICLE_CHANGED".equals(event)) {
            mountEvents++;
        } else if ("STATE_CHANGE".equals(event)) {
            stateEvents++;
        } else if ("TEST_START".equals(event)) {
            testSegments++;
        }
    }

    private static void writeStatus(String reason, LocalPlayer player) {
        if (statusPath == null) {
            return;
        }
        String text = "PhaseLab Admin Telemetry v" + VERSION + "\n"
            + "updated_local=" + ZonedDateTime.now() + "\n"
            + "reason=" + reason + "\n"
            + "session_id=" + safe(sessionId) + "\n"
            + "recording=" + recording + "\n"
            + "test_active=" + segmentActive + "\n"
            + "test_id=" + (segmentActive ? segmentId : 0) + "\n"
            + "test_label=" + (segmentActive ? label() : "NONE") + "\n"
            + "rows_written=" + rows + "\n"
            + "player_packets=" + playerPackets + "\n"
            + "vehicle_packets=" + vehiclePackets + "\n"
            + "mount_events=" + mountEvents + "\n"
            + "state_events=" + stateEvents + "\n"
            + "test_segments=" + testSegments + "\n"
            + "last_event=" + lastEvent + "\n"
            + "session_csv=" + path(OUTPUT_PATHS[0]) + "\n"
            + "config_latest_csv=" + path(OUTPUT_PATHS[1]) + "\n"
            + "easy_csv=" + path(OUTPUT_PATHS[2]) + "\n"
            + "last_io_error=" + lastIoError + "\n";
        try {
            Files.writeString(
                statusPath, text, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
            );
        } catch (IOException exception) {
            noteIoFailure("status_file", exception, player);
        }
    }

    private static void writeSummary(String reason) {
        if (summaryPath == null) {
            return;
        }
        String text = "PhaseLab v" + VERSION + " summary\n"
            + "reason=" + reason + "\n"
            + "generated_local=" + ZonedDateTime.now() + "\n"
            + "session_id=" + safe(sessionId) + "\n"
            + "rows_written=" + rows + "\n"
            + "player_packets=" + playerPackets + "\n"
            + "vehicle_packets=" + vehiclePackets + "\n"
            + "mount_events=" + mountEvents + "\n"
            + "state_events=" + stateEvents + "\n"
            + "test_segments=" + testSegments + "\n"
            + "session_csv=" + path(OUTPUT_PATHS[0]) + "\n"
            + "easy_csv=" + path(OUTPUT_PATHS[2]) + "\n"
            + "last_io_error=" + lastIoError + "\n";
        try {
            Files.writeString(
                summaryPath, text, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
            );
        } catch (IOException exception) {
            lastIoError = "summary_file:" + exception.getClass().getSimpleName() + ":" + safe(exception.getMessage());
        }
    }

    private static String dimension(LocalPlayer player) {
        return player.level().dimension().toString();
    }

    private static double ageOfLargeMove(long now) {
        if (lastLargeMoveNanos == 0L || now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            return -1.0D;
        }
        return (now - lastLargeMoveNanos) / 1_000_000.0D;
    }

    private static void clearLargeMove() {
        lastLargeMoveNanos = 0L;
        lastLargeMoveTo = null;
    }

    private static String vehicleType(Entity vehicle) {
        return vehicle == null ? "NONE" : vehicle.getType().toString();
    }

    private static void addVector(List<String> fields, Vec3 vector) {
        if (vector == null) {
            fields.add("");
            fields.add("");
            fields.add("");
        } else {
            fields.add(number(vector.x));
            fields.add(number(vector.y));
            fields.add(number(vector.z));
        }
    }

    private static String number(double value) {
        return Double.isFinite(value) ? String.format(Locale.ROOT, "%.6f", value) : "";
    }

    private static String bool(boolean value) {
        return value ? "true" : "false";
    }

    private static String csv(String value) {
        return value == null ? "" : "\"" + value.replace("\"", "\"\"") + "\"";
    }

    private static String path(Path value) {
        return value == null ? "not_open" : value.toAbsolutePath().toString();
    }

    private static String safe(String value) {
        return value == null ? "" : value.replace('\n', ' ').replace('\r', ' ');
    }

    private static void noteIoFailure(String target, Exception exception, LocalPlayer player) {
        lastIoError = target + ":" + exception.getClass().getSimpleName() + ":" + safe(exception.getMessage());
        if (!ioWarningShown && player != null) {
            ioWarningShown = true;
            message(player, "Telemetry I/O warning: " + lastIoError, false);
        }
    }

    private static boolean hasWriter() {
        for (BufferedWriter writer : WRITERS) {
            if (writer != null) {
                return true;
            }
        }
        return false;
    }

    private static void resetCounters() {
        rows = 0L;
        playerPackets = 0L;
        vehiclePackets = 0L;
        mountEvents = 0L;
        stateEvents = 0L;
        testSegments = 0L;
        lastEvent = "none";
    }

    private static synchronized void closeOutputs() {
        for (int i = 0; i < WRITERS.length; i++) {
            safeClose(WRITERS[i]);
            WRITERS[i] = null;
        }
    }

    private static void safeClose(BufferedWriter writer) {
        if (writer == null) {
            return;
        }
        try {
            writer.close();
        } catch (IOException ignored) {
        }
    }

    private static void resetDisconnected() {
        closeOutputs();
        connected = false;
        recording = true;
        segmentActive = false;
        tick = 0L;
        lastStatusTick = 0L;
        lastPlayerPosition = null;
        lastVehiclePosition = null;
        clearLargeMove();
        playerCorrectionPending = false;
        playerCorrectionBefore = null;
        vehicleCorrectionPending = false;
        vehicleCorrectionBefore = null;
        lastVehicleId = Integer.MIN_VALUE;
        lastDimension = "unknown";
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }
}
