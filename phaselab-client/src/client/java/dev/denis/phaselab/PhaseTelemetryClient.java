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
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * Passive, player-side PhaseLab telemetry for authorized server testing.
 *
 * This class never changes player/vehicle position, collision, velocity, or
 * outbound movement packets. It only records client state and inbound server
 * correction events so moderators can distinguish normal teleports, local
 * visual movement, dismounts, and real server setbacks.
 */
public final class PhaseTelemetryClient implements ClientModInitializer {
    private static final String VERSION = "4.1.0";
    private static final double LARGE_MOVE_THRESHOLD = 0.75D;
    private static final long CORRELATION_WINDOW_NANOS = 2_000_000_000L;
    private static final int PERIODIC_SAMPLE_TICKS = 20;

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "telemetry")
    );

    private static KeyMapping captureToggleKey;
    private static KeyMapping markerKey;
    private static KeyMapping statusKey;

    private static boolean connected;
    private static boolean recording = true;
    private static long tickCounter;
    private static String sessionId;
    private static Path logPath;
    private static BufferedWriter logWriter;
    private static boolean ioFailed;

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

    @Override
    public void onInitializeClient() {
        captureToggleKey = register("key.phaselab.capture_toggle", GLFW.GLFW_KEY_F8);
        markerKey = register("key.phaselab.marker", GLFW.GLFW_KEY_F9);
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
            }
            resetDisconnectedState();
            return;
        }

        if (!connected) {
            connected = true;
            tickCounter = 0L;
            recording = true;
            openSession();
            initializeState(player);
            append("SESSION_START", "PhaseLab passive telemetry v" + VERSION, -1.0D, -1.0D, null, player);
            message(player, "Telemetry active. F8 pause/resume, F9 mark, F10 status.", false);
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
                append("LOCAL_LARGE_MOVE", String.format(Locale.ROOT, "tick_distance=%.3f", moved), 0.0D, 0.0D, lastTickPosition, player);
            }
        }

        if (lastLargeMoveNanos != 0L && now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            lastLargeMoveNanos = 0L;
            lastLargeMoveFrom = null;
            lastLargeMoveTo = null;
        }

        if (recording) {
            detectMountTransition(player, vehicle);
            detectStateTransition(player);
            if (tickCounter % PERIODIC_SAMPLE_TICKS == 0L) {
                append("SAMPLE", "periodic_1s", ageOfLargeMoveMs(now), -1.0D, lastLargeMoveTo, player);
            }
        }

        lastTickPosition = current;
        lastVehiclePosition = vehiclePosition;
    }

    private static void handleKeys(LocalPlayer player) {
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

        while (markerKey.consumeClick()) {
            append("MANUAL_MARK", "F9 marker", ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
            message(player, "Marker saved at tick " + tickCounter + ".", true);
        }

        while (statusKey.consumeClick()) {
            append("STATUS", recording ? "recording" : "paused", ageOfLargeMoveMs(System.nanoTime()), -1.0D, lastLargeMoveTo, player);
            String pathText = logPath == null ? "not-open" : logPath.toAbsolutePath().toString();
            message(player,
                "recording=" + recording
                    + " | mounted=" + player.isPassenger()
                    + " | water=" + player.isInWater()
                    + " | lava=" + player.isInLava()
                    + " | log=" + pathText,
                false
            );
        }
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
            detail = "previous_vehicle_id=" + lastVehicleId + ";vehicle_id=" + vehicleId + ";vehicle_type=" + vehicleType(vehicle);
        }
        append(event, detail, ageOfLargeMoveMs(System.nanoTime()), -1.0D, vehicle == null ? lastVehiclePosition : vehicle.position(), player);
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

        lastLargeMoveNanos = 0L;
        lastLargeMoveFrom = null;
        lastLargeMoveTo = null;
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
    }

    public static void onServerOpenScreen() {
        LocalPlayer player = Minecraft.getInstance().player;
        append("SERVER_OPEN_SCREEN", "server opened a menu", ageOfLargeMoveMs(System.nanoTime()), -1.0D, null, player);
    }

    private static double ageOfLargeMoveMs(long now) {
        if (lastLargeMoveNanos == 0L || now - lastLargeMoveNanos > CORRELATION_WINDOW_NANOS) {
            return -1.0D;
        }
        return (now - lastLargeMoveNanos) / 1_000_000.0D;
    }

    private static synchronized void openSession() {
        closeLogQuietly();
        sessionId = Instant.now().toString().replace(':', '-') + "-" + UUID.randomUUID().toString().substring(0, 8);
        ioFailed = false;
        try {
            Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Files.createDirectories(directory);
            logPath = directory.resolve("telemetry-v4.1-" + sessionId + ".csv");
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write("timestamp,session_id,tick,event,detail,since_local_move_ms,handler_ms,reference_x,reference_y,reference_z,player_x,player_y,player_z,player_dx,player_dy,player_dz,yaw,pitch,health,air,on_ground,horizontal_collision,no_physics,in_water,in_lava,swimming,sneaking,sprinting,fall_flying,passenger,player_box_clear,vehicle_id,vehicle_type,vehicle_x,vehicle_y,vehicle_z,vehicle_dx,vehicle_dy,vehicle_dz,vehicle_on_ground,vehicle_no_physics,player_vehicle_distance\n");
            logWriter.flush();
        } catch (IOException exception) {
            ioFailed = true;
            logWriter = null;
            logPath = null;
        }
    }

    private static synchronized void append(
        String event,
        String detail,
        double sinceMoveMs,
        double handlerMs,
        Vec3 reference,
        LocalPlayer player
    ) {
        if (logWriter == null || ioFailed || (!recording && !event.startsWith("CAPTURE_") && !"DISCONNECT".equals(event))) {
            return;
        }

        Entity vehicle = player == null ? null : player.getVehicle();
        Vec3 playerPosition = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePosition = vehicle == null ? null : vehicle.position();
        Vec3 vehicleDelta = vehicle == null ? null : vehicle.getDeltaMovement();
        boolean playerBoxClear = player != null && player.level().noCollision(player, player.getBoundingBox().deflate(0.001D));
        double playerVehicleDistance = playerPosition == null || vehiclePosition == null
            ? -1.0D
            : playerPosition.distanceTo(vehiclePosition);

        List<String> fields = new ArrayList<>();
        fields.add(csv(Instant.now().toString()));
        fields.add(csv(sessionId));
        fields.add(Long.toString(tickCounter));
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
        fields.add(vehicle == null ? "-1" : Integer.toString(vehicle.getId()));
        fields.add(csv(vehicleType(vehicle)));
        addVector(fields, vehiclePosition);
        addVector(fields, vehicleDelta);
        fields.add(bool(vehicle != null && vehicle.onGround()));
        fields.add(bool(vehicle != null && vehicle.noPhysics));
        fields.add(number(playerVehicleDistance));

        try {
            logWriter.write(String.join(",", fields));
            logWriter.newLine();
            logWriter.flush();
        } catch (IOException exception) {
            ioFailed = true;
            closeLogQuietly();
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

    private static synchronized void closeLogQuietly() {
        if (logWriter != null) {
            try {
                logWriter.close();
            } catch (IOException ignored) {
            }
        }
        logWriter = null;
    }

    private static void resetDisconnectedState() {
        closeLogQuietly();
        connected = false;
        tickCounter = 0L;
        lastTickPosition = null;
        lastVehiclePosition = null;
        lastLargeMoveFrom = null;
        lastLargeMoveTo = null;
        lastLargeMoveNanos = 0L;
        playerCorrectionPending = false;
        vehicleCorrectionPending = false;
        lastVehicleId = Integer.MIN_VALUE;
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }
}
