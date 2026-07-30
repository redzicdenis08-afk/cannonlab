package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
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
 * Player-only black-box phase research harness for the ExtremeCraft Test Lab.
 *
 * Active scenarios are hard-locked to extremecraft.net:25565 and only change
 * ordinary client key states. Geometry validation rejects targets above/below
 * the vehicle and distinguishes crossing through the selected block corridor
 * from simply driving around an edge.
 */
public final class PhaseLabActiveClient implements ClientModInitializer {
    private static final String VERSION = "6.2.0";
    private static final String ALLOWED_HOST = "extremecraft.net";
    private static final int ALLOWED_PORT = 25565;

    private static final String[] SCENARIOS = {
        "PRESS_FORWARD_SHORT",
        "PRESS_FORWARD_LONG",
        "AUTO_DEEP_SWEEP",
        "PULSE_FAST",
        "PULSE_MEDIUM",
        "PULSE_SLOW",
        "FORWARD_LEFT",
        "FORWARD_RIGHT",
        "STEER_OSCILLATE_FAST",
        "STEER_OSCILLATE_SLOW",
        "BRAKE_RELEASE_SHORT",
        "BRAKE_RELEASE_LONG",
        "FORWARD_BACK_FAST",
        "FORWARD_BACK_SLOW",
        "DISMOUNT_T20",
        "DISMOUNT_T35",
        "DISMOUNT_T50",
        "DISMOUNT_T65",
        "DISMOUNT_T80",
        "IDLE_CONTROL"
    };

    private static final int MAX_RUNTIME_TICKS = 300;
    private static final double MAX_TRAVEL_BLOCKS = 24.0D;
    private static final double CROSSING_MARGIN = 0.15D;
    private static final int PERSISTENT_CROSSING_TICKS = 8;
    private static final double CORRECTION_STEP = 0.35D;
    private static final double START_CORRIDOR_MARGIN = 0.50D;
    private static final double CROSSING_CORRIDOR_MARGIN = 0.10D;
    private static final double VERTICAL_EPSILON = 0.01D;
    private static final DateTimeFormatter FILE_TIME =
        DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");

    private static final String HEADER =
        "utc_timestamp,run_id,version,server_address,lock_ok,scenario,tick,event,detail," +
        "target_x,target_y,target_z,target_collidable,target_vertical_overlap," +
        "barrier_axis,barrier_threshold,barrier_direction,progress,max_progress," +
        "lateral_offset,within_target_corridor,any_crossing_ticks,max_any_crossing_ticks," +
        "corridor_crossing_ticks,max_corridor_crossing_ticks,max_corridor_progress," +
        "correction_candidates,max_backward_step," +
        "player_x,player_y,player_z,player_dx,player_dy,player_dz,mounted,horizontal_collision,in_water,in_lava," +
        "vehicle_id,vehicle_type,vehicle_x,vehicle_y,vehicle_z,vehicle_dx,vehicle_dy,vehicle_dz,vehicle_box_clear," +
        "key_forward,key_back,key_left,key_right,key_shift";

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "active_tester")
    );

    private static KeyMapping scenarioKey;
    private static KeyMapping runKey;
    private static int scenarioIndex;
    private static boolean running;
    private static int scenarioTick;
    private static Object lastConnection;
    private static Boolean lastLockState;

    private static Barrier barrier;
    private static String runId;
    private static String runServerAddress;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static Entity trackedVehicle;
    private static int trackedVehicleId = -1;
    private static double maxPlayerTravel;
    private static double maxVehicleTravel;
    private static double maxProgress;
    private static double maxCorridorProgress;
    private static double previousProgress;
    private static int anyCrossingTicks;
    private static int maxAnyCrossingTicks;
    private static int corridorCrossingTicks;
    private static int maxCorridorCrossingTicks;
    private static int correctionCandidates;
    private static double maxBackwardStep;
    private static double maxLateralOffset;
    private static int dismountTick = -1;
    private static boolean sawCollision;
    private static boolean sawWater;
    private static boolean sawLava;
    private static boolean targetCollidable;
    private static boolean targetVerticalOverlap;

    private static final BufferedWriter[] WRITERS = new BufferedWriter[2];
    private static final Path[] OUTPUT_PATHS = new Path[2];
    private static Path summaryPath;

    @Override
    public void onInitializeClient() {
        scenarioKey = register("key.phaselab.active_scenario", GLFW.GLFW_KEY_F6);
        runKey = register("key.phaselab.active_run", GLFW.GLFW_KEY_F12);
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabActiveClient::tickClient);
    }

    private static KeyMapping register(String key, int code) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(
            key, InputConstants.Type.KEYSYM, code, CATEGORY
        ));
    }

    private static void tickClient(Minecraft client) {
        Object connection = client.getConnection();
        if (connection != lastConnection) {
            if (running) {
                finish(client, client.player, "CONNECTION_CHANGED", "connection_changed", false);
            } else {
                stopKeys(client);
                closeOutputs();
            }
            lastConnection = connection;
            lastLockState = null;
            barrier = null;
        }

        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            if (running) {
                finish(client, player, "WORLD_LEFT", "player_or_level_unavailable", false);
            } else {
                stopKeys(client);
            }
            return;
        }

        boolean lockOk = isAllowedServer(client);
        if (lastLockState == null || lastLockState != lockOk) {
            lastLockState = lockOk;
            message(
                player,
                lockOk
                    ? "ExtremeCraft lock verified. Geometry-aware runner armed."
                    : "LOCKED: active runner only works on " + ALLOWED_HOST + ":" + ALLOWED_PORT + ".",
                false
            );
        }

        if (running && !lockOk) {
            finish(client, player, "LOCK_ABORT", "server_lock_lost", true);
            return;
        }

        while (scenarioKey.consumeClick()) {
            if (!lockOk) {
                message(player, "LOCKED: join " + ALLOWED_HOST + ":" + ALLOWED_PORT + " first.", false);
            } else if (running) {
                message(player, "Press F12 to abort before changing scenario.", false);
            } else {
                scenarioIndex = (scenarioIndex + 1) % SCENARIOS.length;
                message(player, "Scenario " + (scenarioIndex + 1) + "/" + SCENARIOS.length + ": " + scenario(), true);
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
            tickRun(client, player);
        }
    }

    private static void start(Minecraft client, LocalPlayer player) {
        if (!isAllowedServer(client)) {
            message(player, "LOCKED: this build only runs on " + ALLOWED_HOST + ":" + ALLOWED_PORT + ".", false);
            stopKeys(client);
            return;
        }

        Entity vehicle = player.getVehicle();
        if (vehicle == null || !player.isPassenger()) {
            message(player, "Mount the test boat or vehicle first.", false);
            return;
        }

        barrier = detectBarrier(client);
        if (barrier == null) {
            message(player, "Look directly at a vertical wall face, then press F12.", false);
            return;
        }

        targetCollidable = isTargetCollidable(client, barrier);
        if (!targetCollidable) {
            message(player, "INVALID TARGET: selected block has no collision. Aim at a solid bottom wall block.", false);
            barrier = null;
            return;
        }

        targetVerticalOverlap = targetOverlapsVehicleHeight(client, vehicle, barrier);
        if (!targetVerticalOverlap) {
            AABB box = vehicle.getBoundingBox();
            message(
                player,
                "INVALID HEIGHT: target Y=" + barrier.blockPos().getY()
                    + " does not overlap vehicle box Y=" + number(box.minY) + ".." + number(box.maxY)
                    + ". Aim at the lowest blocking row.",
                false
            );
            barrier = null;
            return;
        }

        if (!barrier.withinCorridor(vehicle.position(), START_CORRIDOR_MARGIN)) {
            message(player, "INVALID ALIGNMENT: center the vehicle on the selected wall block.", false);
            barrier = null;
            return;
        }

        double initialProgress = barrier.progress(vehicle.position());
        if (initialProgress >= -0.05D) {
            message(player, "Vehicle must start on the front side of the selected wall.", false);
            barrier = null;
            return;
        }

        scenarioTick = 0;
        runId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        runServerAddress = currentServerAddress(client);
        playerStart = player.position();
        vehicleStart = vehicle.position();
        trackedVehicle = vehicle;
        trackedVehicleId = vehicle.getId();
        maxPlayerTravel = 0.0D;
        maxVehicleTravel = 0.0D;
        maxProgress = initialProgress;
        maxCorridorProgress = initialProgress;
        previousProgress = initialProgress;
        anyCrossingTicks = 0;
        maxAnyCrossingTicks = 0;
        corridorCrossingTicks = 0;
        maxCorridorCrossingTicks = 0;
        correctionCandidates = 0;
        maxBackwardStep = 0.0D;
        maxLateralOffset = barrier.lateralOffset(vehicle.position());
        dismountTick = -1;
        sawCollision = false;
        sawWater = false;
        sawLava = false;

        if (!openOutputs(player)) {
            return;
        }

        running = true;
        writeRow(
            "START",
            "geometry_validated;initial_progress=" + number(initialProgress)
                + ";target=" + barrier.blockPos().toShortString(),
            player
        );
        message(
            player,
            "RUNNING " + scenario() + " | target=" + barrier.blockPos().toShortString() + " | F12 aborts.",
            false
        );
    }

    private static void tickRun(Minecraft client, LocalPlayer player) {
        scenarioTick++;
        applyScenario(client);
        updateMetrics(player);
        writeRow("TICK", "active", player);

        if (!isAllowedServer(client)) {
            finish(client, player, "LOCK_ABORT", "server_lock_lost", true);
            return;
        }
        if (maxPlayerTravel > MAX_TRAVEL_BLOCKS || maxVehicleTravel > MAX_TRAVEL_BLOCKS) {
            finish(client, player, "SAFETY_ABORT", "travel_cap_exceeded", true);
            return;
        }
        if (scenarioTick >= MAX_RUNTIME_TICKS) {
            finish(client, player, "SAFETY_ABORT", "runtime_cap_exceeded", true);
            return;
        }
        if (scenarioTick >= scenarioDuration()) {
            finish(client, player, classify(), "scenario_complete", true);
        }
    }

    private static void applyScenario(Minecraft client) {
        setAllMovement(client, false, false, false, false, false);

        switch (scenario()) {
            case "PRESS_FORWARD_SHORT" -> client.options.keyUp.setDown(scenarioTick <= 80);
            case "PRESS_FORWARD_LONG" -> client.options.keyUp.setDown(scenarioTick <= 200);
            case "AUTO_DEEP_SWEEP" -> applyAutoDeep(client);
            case "PULSE_FAST" -> client.options.keyUp.setDown(scenarioTick <= 180 && scenarioTick % 4 < 3);
            case "PULSE_MEDIUM" -> client.options.keyUp.setDown(scenarioTick <= 180 && scenarioTick % 8 < 6);
            case "PULSE_SLOW" -> client.options.keyUp.setDown(scenarioTick <= 180 && scenarioTick % 16 < 12);
            case "FORWARD_LEFT" -> {
                client.options.keyUp.setDown(scenarioTick <= 160);
                client.options.keyLeft.setDown(scenarioTick <= 160);
            }
            case "FORWARD_RIGHT" -> {
                client.options.keyUp.setDown(scenarioTick <= 160);
                client.options.keyRight.setDown(scenarioTick <= 160);
            }
            case "STEER_OSCILLATE_FAST" -> {
                client.options.keyUp.setDown(scenarioTick <= 180);
                client.options.keyLeft.setDown(scenarioTick <= 180 && (scenarioTick / 4) % 2 == 0);
                client.options.keyRight.setDown(scenarioTick <= 180 && (scenarioTick / 4) % 2 != 0);
            }
            case "STEER_OSCILLATE_SLOW" -> {
                client.options.keyUp.setDown(scenarioTick <= 180);
                client.options.keyLeft.setDown(scenarioTick <= 180 && (scenarioTick / 12) % 2 == 0);
                client.options.keyRight.setDown(scenarioTick <= 180 && (scenarioTick / 12) % 2 != 0);
            }
            case "BRAKE_RELEASE_SHORT" -> {
                client.options.keyUp.setDown(scenarioTick <= 60);
                client.options.keyDown.setDown(scenarioTick >= 61 && scenarioTick <= 78);
            }
            case "BRAKE_RELEASE_LONG" -> {
                client.options.keyUp.setDown(scenarioTick <= 100);
                client.options.keyDown.setDown(scenarioTick >= 101 && scenarioTick <= 135);
            }
            case "FORWARD_BACK_FAST" -> {
                boolean forward = scenarioTick <= 180 && (scenarioTick / 5) % 2 == 0;
                client.options.keyUp.setDown(forward);
                client.options.keyDown.setDown(scenarioTick <= 180 && !forward);
            }
            case "FORWARD_BACK_SLOW" -> {
                boolean forward = scenarioTick <= 220 && (scenarioTick / 15) % 2 == 0;
                client.options.keyUp.setDown(forward);
                client.options.keyDown.setDown(scenarioTick <= 220 && !forward);
            }
            case "DISMOUNT_T20" -> applyDismount(client, 20);
            case "DISMOUNT_T35" -> applyDismount(client, 35);
            case "DISMOUNT_T50" -> applyDismount(client, 50);
            case "DISMOUNT_T65" -> applyDismount(client, 65);
            case "DISMOUNT_T80" -> applyDismount(client, 80);
            case "IDLE_CONTROL" -> {
            }
            default -> {
            }
        }
    }

    private static void applyAutoDeep(Minecraft client) {
        if (scenarioTick <= 40) {
            client.options.keyUp.setDown(true);
        } else if (scenarioTick >= 51 && scenarioTick <= 80) {
            client.options.keyUp.setDown(true);
            client.options.keyLeft.setDown(true);
        } else if (scenarioTick >= 91 && scenarioTick <= 120) {
            client.options.keyUp.setDown(true);
            client.options.keyRight.setDown(true);
        } else if (scenarioTick >= 131 && scenarioTick <= 175) {
            client.options.keyUp.setDown(scenarioTick % 8 < 6);
        } else if (scenarioTick >= 186 && scenarioTick <= 220) {
            boolean forward = (scenarioTick / 5) % 2 == 0;
            client.options.keyUp.setDown(forward);
            client.options.keyDown.setDown(!forward);
        } else if (scenarioTick >= 231 && scenarioTick <= 260) {
            client.options.keyUp.setDown(true);
            client.options.keyLeft.setDown((scenarioTick / 4) % 2 == 0);
            client.options.keyRight.setDown((scenarioTick / 4) % 2 != 0);
        }
    }

    private static void applyDismount(Minecraft client, int tick) {
        client.options.keyUp.setDown(scenarioTick <= 95);
        client.options.keyShift.setDown(scenarioTick == tick || scenarioTick == tick + 1);
    }

    private static int scenarioDuration() {
        return switch (scenario()) {
            case "PRESS_FORWARD_SHORT" -> 110;
            case "PRESS_FORWARD_LONG" -> 220;
            case "AUTO_DEEP_SWEEP" -> 270;
            case "PULSE_FAST", "PULSE_MEDIUM", "PULSE_SLOW",
                 "FORWARD_LEFT", "FORWARD_RIGHT",
                 "STEER_OSCILLATE_FAST", "STEER_OSCILLATE_SLOW",
                 "FORWARD_BACK_FAST" -> 200;
            case "BRAKE_RELEASE_SHORT" -> 120;
            case "BRAKE_RELEASE_LONG" -> 175;
            case "FORWARD_BACK_SLOW" -> 240;
            case "DISMOUNT_T20", "DISMOUNT_T35", "DISMOUNT_T50",
                 "DISMOUNT_T65", "DISMOUNT_T80", "IDLE_CONTROL" -> 120;
            default -> 120;
        };
    }

    private static void updateMetrics(LocalPlayer player) {
        Entity currentVehicle = player.getVehicle();
        Entity observedVehicle = currentVehicle != null ? currentVehicle : trackedVehicle;

        if (!player.isPassenger() && dismountTick < 0) {
            dismountTick = scenarioTick;
            writeRow("DISMOUNT", "tick=" + dismountTick, player);
        }
        if (currentVehicle != null && currentVehicle.getId() != trackedVehicleId) {
            writeRow("VEHICLE_CHANGED", "from=" + trackedVehicleId + ";to=" + currentVehicle.getId(), player);
            trackedVehicle = currentVehicle;
            trackedVehicleId = currentVehicle.getId();
            observedVehicle = currentVehicle;
        }

        maxPlayerTravel = Math.max(maxPlayerTravel, player.position().distanceTo(playerStart));
        sawCollision |= player.horizontalCollision;
        sawWater |= player.isInWater();
        sawLava |= player.isInLava();

        if (observedVehicle == null) {
            return;
        }

        Vec3 vehiclePosition = observedVehicle.position();
        maxVehicleTravel = Math.max(maxVehicleTravel, vehiclePosition.distanceTo(vehicleStart));
        double progress = barrier.progress(vehiclePosition);
        double lateralOffset = barrier.lateralOffset(vehiclePosition);
        boolean withinCorridor = barrier.withinCorridor(vehiclePosition, CROSSING_CORRIDOR_MARGIN);
        maxProgress = Math.max(maxProgress, progress);
        maxLateralOffset = Math.max(maxLateralOffset, lateralOffset);
        if (withinCorridor) {
            maxCorridorProgress = Math.max(maxCorridorProgress, progress);
        }

        if (Double.isFinite(previousProgress)) {
            double step = progress - previousProgress;
            if (step < -CORRECTION_STEP) {
                correctionCandidates++;
                maxBackwardStep = Math.max(maxBackwardStep, -step);
                writeRow(
                    "CORRECTION_CANDIDATE",
                    "backward_step=" + number(-step) + ";from=" + number(previousProgress) + ";to=" + number(progress),
                    player
                );
            }
        }
        previousProgress = progress;

        boolean vehicleBoxClear = observedVehicle.level().noCollision(
            observedVehicle,
            observedVehicle.getBoundingBox().deflate(0.001D)
        );
        sawCollision |= !vehicleBoxClear;
        sawWater |= observedVehicle.isInWater();
        sawLava |= observedVehicle.isInLava();

        if (progress > CROSSING_MARGIN) {
            anyCrossingTicks++;
            maxAnyCrossingTicks = Math.max(maxAnyCrossingTicks, anyCrossingTicks);
            if (withinCorridor) {
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
        if (maxCorridorCrossingTicks >= PERSISTENT_CROSSING_TICKS) {
            return "LOCAL_REPRODUCED";
        }
        if (maxAnyCrossingTicks >= PERSISTENT_CROSSING_TICKS) {
            return "LATERAL_ESCAPE";
        }
        if (maxCorridorProgress > CROSSING_MARGIN) {
            return "LOCAL_TRANSIENT";
        }
        if (correctionCandidates > 0) {
            return "CORRECTED_OR_SETBACK";
        }
        if (dismountTick >= 0 && !requestedDismount()) {
            return "UNEXPECTED_DISMOUNT";
        }
        if (requestedDismount() && dismountTick >= 0) {
            return "DISMOUNT_COMPLETED";
        }
        if (maxVehicleTravel < 0.25D) {
            return "NO_MOVEMENT";
        }
        return "BLOCKED_OR_REJECTED";
    }

    private static boolean requestedDismount() {
        return scenario().startsWith("DISMOUNT_");
    }

    private static void finish(
        Minecraft client,
        LocalPlayer player,
        String verdict,
        String reason,
        boolean showMessage
    ) {
        stopKeys(client);
        if (running) {
            writeRow(
                "FINISH",
                "verdict=" + verdict
                    + ";reason=" + clean(reason)
                    + ";max_player_travel=" + number(maxPlayerTravel)
                    + ";max_vehicle_travel=" + number(maxVehicleTravel)
                    + ";max_progress=" + number(maxProgress)
                    + ";max_corridor_progress=" + number(maxCorridorProgress)
                    + ";max_any_crossing_ticks=" + maxAnyCrossingTicks
                    + ";max_corridor_crossing_ticks=" + maxCorridorCrossingTicks
                    + ";max_lateral_offset=" + number(maxLateralOffset)
                    + ";correction_candidates=" + correctionCandidates
                    + ";max_backward_step=" + number(maxBackwardStep)
                    + ";dismount_tick=" + dismountTick
                    + ";collision=" + sawCollision
                    + ";water=" + sawWater
                    + ";lava=" + sawLava,
                player
            );
            writeSummary(verdict, reason);
        }
        closeOutputs();
        running = false;
        scenarioTick = 0;

        if (showMessage && player != null) {
            message(player, "RESULT: " + verdict + " | " + reason, false);
            message(player, "CSV: " + outputPath(), false);
            scenarioIndex = (scenarioIndex + 1) % SCENARIOS.length;
            message(player, "Next: " + scenario(), true);
        }
    }

    private static Barrier detectBarrier(Minecraft client) {
        if (!(client.hitResult instanceof BlockHitResult hit)) {
            return null;
        }
        Direction face = hit.getDirection();
        BlockPos pos = hit.getBlockPos();
        return switch (face) {
            case WEST -> new Barrier('X', pos.getX() + 1.0D, 1.0D, pos, "X+ beyond block " + pos.toShortString());
            case EAST -> new Barrier('X', pos.getX(), -1.0D, pos, "X- beyond block " + pos.toShortString());
            case NORTH -> new Barrier('Z', pos.getZ() + 1.0D, 1.0D, pos, "Z+ beyond block " + pos.toShortString());
            case SOUTH -> new Barrier('Z', pos.getZ(), -1.0D, pos, "Z- beyond block " + pos.toShortString());
            default -> null;
        };
    }

    private static boolean isTargetCollidable(Minecraft client, Barrier target) {
        if (client.level == null) {
            return false;
        }
        VoxelShape shape = client.level
            .getBlockState(target.blockPos())
            .getCollisionShape(client.level, target.blockPos());
        return !shape.isEmpty();
    }

    private static boolean targetOverlapsVehicleHeight(Minecraft client, Entity vehicle, Barrier target) {
        if (client.level == null) {
            return false;
        }
        VoxelShape shape = client.level
            .getBlockState(target.blockPos())
            .getCollisionShape(client.level, target.blockPos());
        if (shape.isEmpty()) {
            return false;
        }
        AABB local = shape.bounds();
        double targetMinY = target.blockPos().getY() + local.minY;
        double targetMaxY = target.blockPos().getY() + local.maxY;
        AABB vehicleBox = vehicle.getBoundingBox();
        return vehicleBox.maxY > targetMinY + VERTICAL_EPSILON
            && vehicleBox.minY < targetMaxY - VERTICAL_EPSILON;
    }

    private static boolean isAllowedServer(Minecraft client) {
        String address = currentServerAddress(client);
        if (address.isEmpty()) {
            return false;
        }
        String normalized = address.trim().toLowerCase(Locale.ROOT);
        if (normalized.startsWith("minecraft://")) {
            normalized = normalized.substring("minecraft://".length());
        }
        int slash = normalized.indexOf('/');
        if (slash >= 0) {
            normalized = normalized.substring(0, slash);
        }

        String host = normalized;
        int port = ALLOWED_PORT;
        int firstColon = normalized.indexOf(':');
        int lastColon = normalized.lastIndexOf(':');
        if (firstColon > 0 && firstColon == lastColon) {
            host = normalized.substring(0, firstColon);
            String portText = normalized.substring(firstColon + 1);
            try {
                port = Integer.parseInt(portText);
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

    private static void setAllMovement(
        Minecraft client,
        boolean forward,
        boolean back,
        boolean left,
        boolean right,
        boolean shift
    ) {
        client.options.keyUp.setDown(forward);
        client.options.keyDown.setDown(back);
        client.options.keyLeft.setDown(left);
        client.options.keyRight.setDown(right);
        client.options.keyShift.setDown(shift);
    }

    private static void stopKeys(Minecraft client) {
        setAllMovement(client, false, false, false, false, false);
    }

    private static boolean openOutputs(LocalPlayer player) {
        closeOutputs();
        Path configDir = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
        Path gameDir = Minecraft.getInstance().gameDirectory.toPath();
        OUTPUT_PATHS[0] = configDir.resolve("extremecraft-v6.2-" + runId + ".csv");
        OUTPUT_PATHS[1] = gameDir.resolve("PHASELAB_EXTREMECRAFT_LATEST.csv");
        summaryPath = gameDir.resolve("PHASELAB_EXTREMECRAFT_SUMMARY.txt");

        try {
            Files.createDirectories(configDir);
            WRITERS[0] = Files.newBufferedWriter(
                OUTPUT_PATHS[0],
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            WRITERS[1] = Files.newBufferedWriter(
                OUTPUT_PATHS[1],
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE
            );
            for (BufferedWriter writer : WRITERS) {
                writer.write(HEADER);
                writer.newLine();
                writer.flush();
            }
            return true;
        } catch (IOException exception) {
            closeOutputs();
            message(player, "Could not open CSV: " + clean(exception.getMessage()), false);
            return false;
        }
    }

    private static synchronized void writeRow(String event, String detail, LocalPlayer player) {
        if (!hasWriter()) {
            return;
        }

        Entity vehicle = player == null
            ? trackedVehicle
            : (player.getVehicle() != null ? player.getVehicle() : trackedVehicle);
        Vec3 playerPos = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePos = vehicle == null ? null : vehicle.position();
        Vec3 vehicleDelta = vehicle == null ? null : vehicle.getDeltaMovement();
        boolean vehicleBoxClear = vehicle != null && vehicle.level().noCollision(
            vehicle,
            vehicle.getBoundingBox().deflate(0.001D)
        );
        double progress = vehiclePos == null || barrier == null
            ? Double.NaN
            : barrier.progress(vehiclePos);
        double lateralOffset = vehiclePos == null || barrier == null
            ? Double.NaN
            : barrier.lateralOffset(vehiclePos);
        boolean withinCorridor = vehiclePos != null
            && barrier != null
            && barrier.withinCorridor(vehiclePos, CROSSING_CORRIDOR_MARGIN);
        Minecraft client = Minecraft.getInstance();
        BlockPos target = barrier == null ? null : barrier.blockPos();

        String row = String.join(",",
            csv(Instant.now().toString()),
            csv(runId),
            csv(VERSION),
            csv(runServerAddress),
            Boolean.toString(isAllowedServer(client)),
            csv(scenario()),
            Integer.toString(scenarioTick),
            csv(event),
            csv(detail),
            target == null ? "" : Integer.toString(target.getX()),
            target == null ? "" : Integer.toString(target.getY()),
            target == null ? "" : Integer.toString(target.getZ()),
            Boolean.toString(targetCollidable),
            Boolean.toString(targetVerticalOverlap),
            barrier == null ? "" : csv(Character.toString(barrier.axis())),
            barrier == null ? "" : number(barrier.threshold()),
            barrier == null ? "" : number(barrier.direction()),
            number(progress),
            number(maxProgress),
            number(lateralOffset),
            Boolean.toString(withinCorridor),
            Integer.toString(anyCrossingTicks),
            Integer.toString(maxAnyCrossingTicks),
            Integer.toString(corridorCrossingTicks),
            Integer.toString(maxCorridorCrossingTicks),
            number(maxCorridorProgress),
            Integer.toString(correctionCandidates),
            number(maxBackwardStep),
            vectorField(playerPos, 0),
            vectorField(playerPos, 1),
            vectorField(playerPos, 2),
            vectorField(playerDelta, 0),
            vectorField(playerDelta, 1),
            vectorField(playerDelta, 2),
            Boolean.toString(player != null && player.isPassenger()),
            Boolean.toString(player != null && player.horizontalCollision),
            Boolean.toString(player != null && player.isInWater()),
            Boolean.toString(player != null && player.isInLava()),
            vehicle == null ? "" : Integer.toString(vehicle.getId()),
            vehicle == null ? "" : csv(vehicle.getType().toString()),
            vectorField(vehiclePos, 0),
            vectorField(vehiclePos, 1),
            vectorField(vehiclePos, 2),
            vectorField(vehicleDelta, 0),
            vectorField(vehicleDelta, 1),
            vectorField(vehicleDelta, 2),
            Boolean.toString(vehicleBoxClear),
            Boolean.toString(client.options.keyUp.isDown()),
            Boolean.toString(client.options.keyDown.isDown()),
            Boolean.toString(client.options.keyLeft.isDown()),
            Boolean.toString(client.options.keyRight.isDown()),
            Boolean.toString(client.options.keyShift.isDown())
        );

        for (int i = 0; i < WRITERS.length; i++) {
            BufferedWriter writer = WRITERS[i];
            if (writer == null) {
                continue;
            }
            try {
                writer.write(row);
                writer.newLine();
                writer.flush();
            } catch (IOException exception) {
                try {
                    writer.close();
                } catch (IOException ignored) {
                }
                WRITERS[i] = null;
            }
        }
    }

    private static void writeSummary(String verdict, String reason) {
        if (summaryPath == null) {
            return;
        }
        String text = "PhaseLab ExtremeCraft Geometry v" + VERSION + System.lineSeparator()
            + "allowed_server=" + ALLOWED_HOST + ":" + ALLOWED_PORT + System.lineSeparator()
            + "connected_server=" + clean(runServerAddress) + System.lineSeparator()
            + "run=" + runId + System.lineSeparator()
            + "scenario=" + scenario() + System.lineSeparator()
            + "verdict=" + verdict + System.lineSeparator()
            + "reason=" + clean(reason) + System.lineSeparator()
            + "barrier=" + (barrier == null ? "none" : barrier.description()) + System.lineSeparator()
            + "target_block=" + (barrier == null ? "none" : barrier.blockPos().toShortString()) + System.lineSeparator()
            + "target_collidable=" + targetCollidable + System.lineSeparator()
            + "target_vertical_overlap=" + targetVerticalOverlap + System.lineSeparator()
            + "max_player_travel=" + number(maxPlayerTravel) + System.lineSeparator()
            + "max_vehicle_travel=" + number(maxVehicleTravel) + System.lineSeparator()
            + "max_progress=" + number(maxProgress) + System.lineSeparator()
            + "max_corridor_progress=" + number(maxCorridorProgress) + System.lineSeparator()
            + "max_any_crossing_ticks=" + maxAnyCrossingTicks + System.lineSeparator()
            + "max_corridor_crossing_ticks=" + maxCorridorCrossingTicks + System.lineSeparator()
            + "max_lateral_offset=" + number(maxLateralOffset) + System.lineSeparator()
            + "correction_candidates=" + correctionCandidates + System.lineSeparator()
            + "max_backward_step=" + number(maxBackwardStep) + System.lineSeparator()
            + "dismount_tick=" + dismountTick + System.lineSeparator()
            + "collision=" + sawCollision + System.lineSeparator()
            + "water=" + sawWater + System.lineSeparator()
            + "lava=" + sawLava + System.lineSeparator()
            + "note=LOCAL_REPRODUCED now requires persistent crossing inside the selected solid block corridor."
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

    private static boolean hasWriter() {
        return WRITERS[0] != null || WRITERS[1] != null;
    }

    private static synchronized void closeOutputs() {
        for (int i = 0; i < WRITERS.length; i++) {
            if (WRITERS[i] != null) {
                try {
                    WRITERS[i].flush();
                    WRITERS[i].close();
                } catch (IOException ignored) {
                }
                WRITERS[i] = null;
            }
        }
    }

    private static String outputPath() {
        return OUTPUT_PATHS[1] == null
            ? "PHASELAB_EXTREMECRAFT_LATEST.csv"
            : OUTPUT_PATHS[1].toAbsolutePath().toString();
    }

    private static String scenario() {
        return SCENARIOS[scenarioIndex];
    }

    private static String vectorField(Vec3 vector, int index) {
        if (vector == null) {
            return "";
        }
        return number(index == 0 ? vector.x : index == 1 ? vector.y : vector.z);
    }

    private static String number(double value) {
        return Double.isFinite(value)
            ? String.format(Locale.ROOT, "%.6f", value)
            : "";
    }

    private static String clean(String value) {
        return value == null
            ? ""
            : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static String csv(String value) {
        String safe = value == null ? "" : value.replace("\"", "\"\"");
        return "\"" + safe + "\"";
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }

    private record Barrier(
        char axis,
        double threshold,
        double direction,
        BlockPos blockPos,
        String description
    ) {
        double progress(Vec3 position) {
            double coordinate = axis == 'X' ? position.x : position.z;
            return direction * (coordinate - threshold);
        }

        double lateralCoordinate(Vec3 position) {
            return axis == 'X' ? position.z : position.x;
        }

        double lateralMin() {
            return axis == 'X' ? blockPos.getZ() : blockPos.getX();
        }

        double lateralMax() {
            return lateralMin() + 1.0D;
        }

        boolean withinCorridor(Vec3 position, double margin) {
            double lateral = lateralCoordinate(position);
            return lateral >= lateralMin() - margin && lateral <= lateralMax() + margin;
        }

        double lateralOffset(Vec3 position) {
            double center = lateralMin() + 0.5D;
            return Math.abs(lateralCoordinate(position) - center);
        }
    }
}
