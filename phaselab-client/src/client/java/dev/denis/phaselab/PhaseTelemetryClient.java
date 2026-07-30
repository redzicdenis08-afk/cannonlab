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

/**
 * Passive, player-side PhaseLab telemetry for authorized server testing.
 *
 * This class never changes player/vehicle position, collision, velocity, or
 * outbound movement packets. It records local state and inbound server evidence
 * into an obvious root CSV plus an archived per-session CSV.
 */
public final class PhaseTelemetryClient implements ClientModInitializer {
    private static final String VERSION = "4.2.0";
    private static final double LARGE_MOVE_THRESHOLD = 0.75D;
    private static final long CORRELATION_WINDOW_NANOS = 2_000_000_000L;
    private static final int IDLE_SAMPLE_TICKS = 20;
    private static final int DETAIL_SAMPLE_TICKS = 1;
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");
    private static final String[] TEST_LABELS = {
        "GENERAL",
        "MOUNT",
        "WALL_CONTACT",
        "WATER",
        "CLAIM_BORDER",
        "DISMOUNT",
        "CONTAINER"
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

    private static KeyMapping captureToggleKey;
    private static KeyMapping labelKey;
    private static KeyMapping segmentKey;
    private static KeyMapping statusKey;

    private static boolean connected;
    private static boolean recording = true;
    private static boolean segmentActive;
    private static long tickCounter;
    private static long lastStatusWriteTick;
    private static int segmentNumber;
    private static int testLabelIndex;
    private static String sessionId;

    private static Path sessionPath;
    private static Path configLatestPath;
    private static Path rootLatestPath;
    private static Path statusPath;
    private static Path summaryPath;
    private static BufferedWriter sessionWriter;
    private static BufferedWriter configLatestWriter;
    private static BufferedWriter rootLatestWriter;
    private static boolean ioWarningShown;
    private static String lastIoError = "none";
    private static String lastEvent = "none";

    private static long rowsWritten;
    private static long playerCorrectionPackets;
    private static long vehicleCorrectionPackets;
    private static long mountEvents;
    private static long stateChanges;
    private static long testSegments;

    private static Vec3 lastTickPosition;
    private static Vec3 lastVehiclePosition;
    private static Vec3 lastLargeMoveFrom;
    private static Vec3 lastLargeMoveTo;
    private static long lastLargeMoveNanos;

    private static boolean playerCorrectionPending;
    private static Vec3 playerCorrectionBefore;
    private static long playerCorrectionHeadNanos;

    private static boolean vehicleCorrectionPending;
    private static Vec3 vehicleCorrectionBefore;
    private static long vehicleCorrectionHeadNanos;

    private static int lastVehicleId = Integer.MIN_VALUE;
    private static boolean lastInWater;
    private static boolean lastInLava;
    private static boolean lastHorizontalCollision;
    private static boolean lastNoPhysics;
    private static boolean lastSwimming;
    private static boolean lastFallFlying;
    private static String lastDimension = "unknown";

    @Override
    public void onInitializeClient() {
        captureToggleKey = register("key.phaselab.capture_toggle", GLFW.GLFW_KEY_F8);
        labelKey = register("key.phaselab.test_label", GLFW.GLFW_KEY_F7);
        segmentKey = register("key.phaselab.test_segment", GLFW.GLFW_KEY_F9);
        statusKey = register("key.phaselab.telemetry_status", GLFW.GLFW_KEY_F10);
        ClientTickEvents.END_CLIENT_TICK.register(PhaseTelemetryClient::onClientTick);
    }

    private static KeyMapping register(String translationKey, int defaultKey) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(
            translationKey,
            InputConstants.Type.KEYSYM,
            defaultKey,
            CATEGORY
        ));
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            if (connected) {
                append("DISCONNECT", "client player/level became unavailable", -1.0D, -1.0D, null, null);
                writeSummaryFile("disconnect");
            }
            resetDisconnectedState();
            return;
        }

        if (!connected) {
            connected = true;
            tickCounter = 0L;
            lastStatusWriteTick = 0L;
            recording = true;
            segmentActive = false;
            segmentNumber = 0;
            testLabelIndex = 0;
            resetCounters();
            openSession(player);
            initializeState(player);
            append("SESSION_START", "PhaseLab passive telemetry v" + VERSION, -1.0D, -1.0D, null, player);
            message(player, "Telemetry v" + VERSION + " active. F7 type, F8 pause, F9 test start/end, F10 status.", false);
            if (rootLatestPath != null) {
                message(player, "Easy CSV: " + rootLatestPath.toAbsolutePath(), false);
            }
        }

        tickCounter++;
        handleKeys(player);

        Vec3 current = player.position();
        Entity vehicle = player.getVehicle();
        Vec3 vehiclePosition = vehicle == null ? null : vehicle.position();
        long now = System.nanoTime();

        if (recording && lastTickPosition != null) {
            double moved = current.distanceTo(lastTickPosition);
            if (moved >= LARGE_MOVE_THRESHOLD) {
                lastLargeMoveFrom = lastTickPosition;
                lastLargeMoveTo = current;
                lastLargeMoveNanos = now;
                append(
                    "LOCAL_LARGE_MOVE",
                    String.format(Locale.ROOT, "tick_distance=%.3f", moved),
                    0.0D,
                    0.0D,
                    lastTickPosition,
                    player
                );
            }
        }

        expireLargeMove(now);

        if (recording) {
            detectMountTransition(player, vehicle);
            detectStateTransition(player);

            boolean detailMode = segmentActive
                || player.isPassenger()
                || player.horizontalCollision
                || player.isInWater()
                || player.isInLava();
            int sampleTicks = detailMode ? DETAIL_SAMPLE_TICKS : IDLE_SAMPLE_TICKS;
            if (tickCounter % sampleTicks == 0L) {
                append(
                    "SAMPLE",
                    detailMode ? "detail_20hz" : "idle_1hz",
                    ageOfLargeMoveMs(now),
                    -1.0D,
                    lastLargeMoveTo,
                    player
                );
            }
        }

        lastTickPosition = current;
        lastVehiclePosition = vehiclePosition;
    }

    private static void handleKeys(LocalPlayer player) {
        while (labelKey.consumeClick()) {
            if (segmentActive) {
                message(player, "End the current test with F9 before changing its type.", false);
            } else {
                testLabelIndex = (testLabelIndex + 1) % TEST_LABELS.length;
                append("TEST_LABEL", "selected=" + currentTestLabel(), ageOfLargeMoveMs(System.nanoTime()), -1.0D, null, player);
                message(player, "Test type: " + currentTestLabel(), true);
            }
        }

        while (captureToggleKey.consumeClick()) {
            if (recording) {
                append("CAPTURE_PAUSED", "manual", ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
                recording = false;
                message(player, "Telemetry paused. F8 resumes it.", false);
            } else {
                recording = true;
                append("CAPTURE_RESUMED", "manual", ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
                message(player, "Telemetry resumed.", false);
            }
        }

        while (segmentKey.consumeClick()) {
            if (!segmentActive) {
                segmentNumber++;
                segmentActive = true;
                append("TEST_START", "label=" + currentTestLabel(), ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
                message(player, "TEST " + segmentNumber + " START: " + currentTestLabel(), false);
            } else {
                append("TEST_END", "label=" + currentTestLabel(), ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
                segmentActive = false;
                message(player, "TEST " + segmentNumber + " END: " + currentTestLabel(), false);
            }
        }

        while (statusKey.consumeClick()) {
            append("STATUS", recording ? "recording" : "paused", ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
            writeSummaryFile("live_status");
            message(
                player,
                "recording=" + recording
                    + " | test=" + (segmentActive ? segmentNumber + ":" + currentTestLabel() : "none")
                    + " | rows=" + rowsWritten
                    + " | playerPackets=" + playerCorrectionPackets
                    + " | vehiclePackets=" + vehicleCorrectionPackets,
                false
            );
            if (rootLatestPath != null) {
                message(player, "Open this exact file: " + rootLatestPath.toAbsolutePath(), false);
            }
        }
    }

    private static String currentTestLabel() {
        return TEST_LABELS[testLabelIndex];
    }

    private static void initializeState(LocalPlayer player) {
        Entity vehicle = player.getVehicle();
        lastTickPosition = player.position();
        lastVehiclePosition = vehicle == null ? null : vehicle.position();
        lastVehicleId = vehicle == null ? -1 : vehicle.getId();
        lastInWater = player.isInWater();
        lastInLava = player.isInLava();
        lastHorizontalCollision = player.horizontalCollision;
        lastNoPhysics = player.noPhysics;
        lastSwimming = player.isSwimming();
        lastFallFlying = player.isFallFlying();
        lastDimension = dimension(player);
    }

    private static void detectMountTransition(LocalPlayer player, Entity vehicle) {
        int vehicleId = vehicle == null ? -1 : vehicle.getId();
        if (vehicleId == lastVehicleId) {
            return;
        }

        String event;
        String detail;
        if (lastVehicleId == -1 && vehicleId != -1) {
            event = "MOUNTED";
            detail = "vehicle_id=" + vehicleId + ";vehicle_type=" + vehicleType(vehicle);
        } else if (lastVehicleId != -1 && vehicleId == -1) {
            event = "DISMOUNTED";
            detail = "previous_vehicle_id=" + lastVehicleId;
        } else {
            event = "VEHICLE_CHANGED";
            detail = "previous_vehicle_id=" + lastVehicleId
                + ";vehicle_id=" + vehicleId
                + ";vehicle_type=" + vehicleType(vehicle);
        }
        append(
            event,
            detail,
            ageOfLargeMoveMs(System.nanoTime()),
            -1.0D,
            vehicle == null ? lastVehiclePosition : vehicle.position(),
            player
        );
        lastVehicleId = vehicleId;
    }

    private static void detectStateTransition(LocalPlayer player) {
        List<String> changes = new ArrayList<>();
        if (player.isInWater() != lastInWater) {
            changes.add("water=" + player.isInWater());
            lastInWater = player.isInWater();
        }
        if (player.isInLava() != lastInLava) {
            changes.add("lava=" + player.isInLava());
            lastInLava = player.isInLava();
        }
        if (player.horizontalCollision != lastHorizontalCollision) {
            changes.add("horizontal_collision=" + player.horizontalCollision);
            lastHorizontalCollision = player.horizontalCollision;
        }
        if (player.noPhysics != lastNoPhysics) {
            changes.add("no_physics=" + player.noPhysics);
            lastNoPhysics = player.noPhysics;
        }
        if (player.isSwimming() != lastSwimming) {
            changes.add("swimming=" + player.isSwimming());
            lastSwimming = player.isSwimming();
        }
        if (player.isFallFlying() != lastFallFlying) {
            changes.add("fall_flying=" + player.isFallFlying());
            lastFallFlying = player.isFallFlying();
        }
        String currentDimension = dimension(player);
        if (!currentDimension.equals(lastDimension)) {
            changes.add("dimension=" + currentDimension);
            lastDimension = currentDimension;
        }

        if (!changes.isEmpty()) {
            append("STATE_CHANGE", String.join(";", changes), ageOfLargeMoveMs(System.nanoTime()), -1.0D, null, player);
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
        double sinceMoveMs = ageOfLargeMoveMs(now);
        double handlerMs = (now - playerCorrectionHeadNanos) / 1_000_000.0D;
        boolean correlated = lastLargeMoveNanos != 0L && now - lastLargeMoveNanos <= CORRELATION_WINDOW_NANOS;
        Vec3 corrected = player.position();
        double correctionDistance = playerCorrectionBefore == null ? -1.0D : corrected.distanceTo(playerCorrectionBefore);

        append(
            correlated ? "SERVER_SETBACK_CORRELATED" : "SERVER_POSITION_PACKET",
            String.format(Locale.ROOT, "correction_distance=%.3f", correctionDistance),
            sinceMoveMs,
            handlerMs,
            playerCorrectionBefore,
            player
        );

        if (correlated) {
            String speed = sinceMoveMs < 250.0D ? "FAST" : sinceMoveMs < 1_000.0D ? "NORMAL" : "DELAYED";
            message(player, String.format(Locale.ROOT,
                "SERVER SETBACK %s after %.1f ms (%.3f blocks)",
                speed,
                sinceMoveMs,
                correctionDistance
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
        double correctionDistance = vehicleCorrectionBefore == null || after == null
            ? -1.0D
            : after.distanceTo(vehicleCorrectionBefore);
        long now = System.nanoTime();

        append(
            "SERVER_VEHICLE_CORRECTION",
            String.format(Locale.ROOT, "correction_distance=%.3f", correctionDistance),
            ageOfLargeMoveMs(now),
            (now - vehicleCorrectionHeadNanos) / 1_000_000.0D,
            vehicleCorrectionBefore,
            player
        );
        vehicleCorrectionBefore = null;
    }

    public static void onServerOpenScreen() {
        LocalPlayer player = Minecraft.getInstance().player;
        append("SERVER_OPEN_SCREEN", "server opened a menu", ageOfLargeMoveMs(System.nanoTime()), -1.0D, null, player);
    }

    private static void expireLargeMove(long now) {
        if (lastLargeMoveNanos != 0L && now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            clearLargeMove();
        }
    }

    private static void clearLargeMove() {
        lastLargeMoveNanos = 0L;
        lastLargeMoveFrom = null;
        lastLargeMoveTo = null;
    }

    private static double ageOfLargeMoveMs(long now) {
        if (lastLargeMoveNanos == 0L || now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            return -1.0D;
        }
        return (now - lastLargeMoveNanos) / 1_000_000.0D;
    }

    private static synchronized void openSession(LocalPlayer player) {
        closeWritersQuietly();
        sessionId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        ioWarningShown = false;
        lastIoError = "none";

        Path configDirectory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
        Path gameDirectory = Minecraft.getInstance().gameDirectory.toPath();
        sessionPath = configDirectory.resolve("telemetry-v4.2-" + sessionId + ".csv");
        configLatestPath = configDirectory.resolve("PHASELAB_LATEST.csv");
        rootLatestPath = gameDirectory.resolve("PHASELAB_LATEST.csv");
        statusPath = gameDirectory.resolve("PHASELAB_STATUS.txt");
        summaryPath = gameDirectory.resolve("PHASELAB_SUMMARY.txt");

        try {
            Files.createDirectories(configDirectory);
        } catch (IOException exception) {
            noteIoFailure("config directory", exception, player);
        }

        try {
            sessionWriter = Files.newBufferedWriter(
                sessionPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            writeHeader(sessionWriter);
        } catch (IOException exception) {
            sessionWriter = null;
            noteIoFailure("session CSV", exception, player);
        }

        try {
            configLatestWriter = Files.newBufferedWriter(
                configLatestPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
            writeHeader(configLatestWriter);
        } catch (IOException exception) {
            configLatestWriter = null;
            noteIoFailure("config latest CSV", exception, player);
        }

        try {
            rootLatestWriter = Files.newBufferedWriter(
                rootLatestPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
            writeHeader(rootLatestWriter);
        } catch (IOException exception) {
            rootLatestWriter = null;
            noteIoFailure("root latest CSV", exception, player);
        }

        if (!hasAnyWriter()) {
            message(player, "ERROR: PhaseLab could not open any CSV output. Check PHASELAB_STATUS.txt after fixing folder permissions.", false);
        }
        writeStatusFile(player, "SESSION_OPEN");
    }

    private static void writeHeader(BufferedWriter writer) throws IOException {
        writer.write(HEADER);
        writer.newLine();
        writer.flush();
    }

    private static synchronized void append(
        String event,
        String detail,
        double sinceMoveMs,
        double handlerMs,
        Vec3 reference,
        LocalPlayer player
    ) {
        boolean controlEvent = event.startsWith("CAPTURE_")
            || event.startsWith("TEST_")
            || "STATUS".equals(event)
            || "DISCONNECT".equals(event)
            || event.startsWith("SERVER_");
        if (!recording && !controlEvent) {
            return;
        }
        if (!hasAnyWriter()) {
            return;
        }

        Entity vehicle = player == null ? null : player.getVehicle();
        Vec3 playerPosition = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePosition = vehicle == null ? null : vehicle.position();
        Vec3 vehicleDelta = vehicle == null ? null : vehicle.getDeltaMovement();
        boolean playerBoxClear = player != null && player.level().noCollision(player, player.getBoundingBox().deflate(0.001D));
        boolean vehicleBoxClear = vehicle != null && vehicle.level().noCollision(vehicle, vehicle.getBoundingBox().deflate(0.001D));
        double playerVehicleDistance = playerPosition == null || vehiclePosition == null
            ? -1.0D
            : playerPosition.distanceTo(vehiclePosition);
        var blockPosition = player == null ? null : player.blockPosition();

        List<String> fields = new ArrayList<>();
        fields.add(csv(Instant.now().toString()));
        fields.add(csv(ZonedDateTime.now().toString()));
        fields.add(csv(sessionId));
        fields.add(Long.toString(tickCounter));
        fields.add(Integer.toString(segmentActive ? segmentNumber : 0));
        fields.add(csv(segmentActive ? currentTestLabel() : "NONE"));
        fields.add(csv(event));
        fields.add(csv(detail));
        fields.add(number(sinceMoveMs));
        fields.add(number(handlerMs));
        addVector(fields, reference);
        addVector(fields, playerPosition);
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
        fields.add(blockPosition == null ? "" : Integer.toString(blockPosition.getX()));
        fields.add(blockPosition == null ? "" : Integer.toString(blockPosition.getY()));
        fields.add(blockPosition == null ? "" : Integer.toString(blockPosition.getZ()));
        fields.add(blockPosition == null ? "" : Integer.toString(blockPosition.getX() >> 4));
        fields.add(blockPosition == null ? "" : Integer.toString(blockPosition.getZ() >> 4));
        fields.add(csv(player == null ? "" : dimension(player)));
        fields.add(vehicle == null ? "-1" : Integer.toString(vehicle.getId()));
        fields.add(csv(vehicleType(vehicle)));
        addVector(fields, vehiclePosition);
        addVector(fields, vehicleDelta);
        fields.add(bool(vehicle != null && vehicle.onGround()));
        fields.add(bool(vehicle != null && vehicle.noPhysics));
        fields.add(bool(vehicleBoxClear));
        fields.add(vehicle == null ? "0" : Integer.toString(vehicle.getPassengers().size()));
        fields.add(number(playerVehicleDistance));

        String line = String.join(",", fields);
        boolean wrote = writeLineToOutputs(line, player);
        if (!wrote) {
            return;
        }

        rowsWritten++;
        lastEvent = event;
        updateCounters(event);
        if (!"SAMPLE".equals(event) || tickCounter - lastStatusWriteTick >= IDLE_SAMPLE_TICKS) {
            writeStatusFile(player, event);
            lastStatusWriteTick = tickCounter;
        }
    }

    private static boolean writeLineToOutputs(String line, LocalPlayer player) {
        boolean wrote = false;

        if (sessionWriter != null) {
            try {
                sessionWriter.write(line);
                sessionWriter.newLine();
                sessionWriter.flush();
                wrote = true;
            } catch (IOException exception) {
                safeClose(sessionWriter);
                sessionWriter = null;
                noteIoFailure("session CSV write", exception, player);
            }
        }

        if (configLatestWriter != null) {
            try {
                configLatestWriter.write(line);
                configLatestWriter.newLine();
                configLatestWriter.flush();
                wrote = true;
            } catch (IOException exception) {
                safeClose(configLatestWriter);
                configLatestWriter = null;
                noteIoFailure("config latest write", exception, player);
            }
        }

        if (rootLatestWriter != null) {
            try {
                rootLatestWriter.write(line);
                rootLatestWriter.newLine();
                rootLatestWriter.flush();
                wrote = true;
            } catch (IOException exception) {
                safeClose(rootLatestWriter);
                rootLatestWriter = null;
                noteIoFailure("root latest write", exception, player);
            }
        }

        return wrote;
    }

    private static void updateCounters(String event) {
        if ("SERVER_SETBACK_CORRELATED".equals(event) || "SERVER_POSITION_PACKET".equals(event)) {
            playerCorrectionPackets++;
        }
        if ("SERVER_VEHICLE_CORRECTION".equals(event)) {
            vehicleCorrectionPackets++;
        }
        if ("MOUNTED".equals(event) || "DISMOUNTED".equals(event) || "VEHICLE_CHANGED".equals(event)) {
            mountEvents++;
        }
        if ("STATE_CHANGE".equals(event)) {
            stateChanges++;
        }
        if ("TEST_START".equals(event)) {
            testSegments++;
        }
    }

    private static void writeStatusFile(LocalPlayer player, String reason) {
        if (statusPath == null) {
            return;
        }
        String text = "PhaseLab Admin Telemetry v" + VERSION + "\n"
            + "updated_local=" + ZonedDateTime.now() + "\n"
            + "reason=" + reason + "\n"
            + "session_id=" + safe(sessionId) + "\n"
            + "recording=" + recording + "\n"
            + "test_active=" + segmentActive + "\n"
            + "test_id=" + (segmentActive ? segmentNumber : 0) + "\n"
            + "test_label=" + (segmentActive ? currentTestLabel() : "NONE") + "\n"
            + "rows_written=" + rowsWritten + "\n"
            + "player_correction_packets=" + playerCorrectionPackets + "\n"
            + "vehicle_correction_packets=" + vehicleCorrectionPackets + "\n"
            + "mount_events=" + mountEvents + "\n"
            + "state_changes=" + stateChanges + "\n"
            + "test_segments=" + testSegments + "\n"
            + "last_event=" + lastEvent + "\n"
            + "session_csv=" + pathText(sessionPath) + "\n"
            + "easy_csv=" + pathText(rootLatestPath) + "\n"
            + "config_latest_csv=" + pathText(configLatestPath) + "\n"
            + "last_io_error=" + lastIoError + "\n";
        try {
            Files.writeString(
                statusPath,
                text,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
        } catch (IOException exception) {
            lastIoError = "status file: " + exception.getClass().getSimpleName() + ": " + safe(exception.getMessage());
            if (!ioWarningShown && player != null) {
                ioWarningShown = true;
                message(player, "Telemetry status-file warning: " + lastIoError, false);
            }
        }
    }

    private static void writeSummaryFile(String reason) {
        if (summaryPath == null) {
            return;
        }
        String text = "PhaseLab v" + VERSION + " session summary\n"
            + "reason=" + reason + "\n"
            + "generated_local=" + ZonedDateTime.now() + "\n"
            + "session_id=" + safe(sessionId) + "\n"
            + "rows_written=" + rowsWritten + "\n"
            + "player_correction_packets=" + playerCorrectionPackets + "\n"
            + "vehicle_correction_packets=" + vehicleCorrectionPackets + "\n"
            + "mount_events=" + mountEvents + "\n"
            + "state_changes=" + stateChanges + "\n"
            + "test_segments=" + testSegments + "\n"
            + "session_csv=" + pathText(sessionPath) + "\n"
            + "easy_csv=" + pathText(rootLatestPath) + "\n"
            + "last_io_error=" + lastIoError + "\n";
        try {
            Files.writeString(
                summaryPath,
                text,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
        } catch (IOException exception) {
            lastIoError = "summary file: " + exception.getClass().getSimpleName() + ": " + safe(exception.getMessage());
        }
    }

    private static void noteIoFailure(String target, Exception exception, LocalPlayer player) {
        lastIoError = target + ": " + exception.getClass().getSimpleName() + ": " + safe(exception.getMessage());
        if (!ioWarningShown && player != null) {
            ioWarningShown = true;
            message(player, "Telemetry I/O warning: " + lastIoError, false);
        }
    }

    private static boolean hasAnyWriter() {
        return sessionWriter != null || configLatestWriter != null || rootLatestWriter != null;
    }

    private static String dimension(LocalPlayer player) {
        try {
            return player.level().dimension().location().toString();
        } catch (RuntimeException exception) {
            return "unknown";
        }
    }

    private static String vehicleType(Entity vehicle) {
        return vehicle == null ? "NONE" : vehicle.getType().toString();
    }

    private static void addVector(List<String> fields, Vec3 vector) {
        if (vector == null) {
            fields.add("");
            fields.add("");
            fields.add("");
            return;
        }
        fields.add(number(vector.x));
        fields.add(number(vector.y));
        fields.add(number(vector.z));
    }

    private static String number(double value) {
        return Double.isFinite(value) ? String.format(Locale.ROOT, "%.6f", value) : "";
    }

    private static String bool(boolean value) {
        return value ? "true" : "false";
    }

    private static String csv(String value) {
        if (value == null) {
            return "";
        }
        return "\"" + value.replace("\"", "\"\"") + "\"";
    }

    private static String pathText(Path path) {
        return path == null ? "not-open" : path.toAbsolutePath().toString();
    }

    private static String safe(String value) {
        return value == null ? "" : value.replace('\n', ' ').replace('\r', ' ');
    }

    private static void resetCounters() {
        rowsWritten = 0L;
        playerCorrectionPackets = 0L;
        vehicleCorrectionPackets = 0L;
        mountEvents = 0L;
        stateChanges = 0L;
        testSegments = 0L;
        lastEvent = "none";
    }

    private static synchronized void closeWritersQuietly() {
        safeClose(sessionWriter);
        safeClose(configLatestWriter);
        safeClose(rootLatestWriter);
        sessionWriter = null;
        configLatestWriter = null;
        rootLatestWriter = null;
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

    private static void resetDisconnectedState() {
        closeWritersQuietly();
        connected = false;
        recording = true;
        segmentActive = false;
        tickCounter = 0L;
        lastStatusWriteTick = 0L;
        lastTickPosition = null;
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
