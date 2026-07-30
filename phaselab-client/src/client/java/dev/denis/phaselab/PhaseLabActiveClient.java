package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.Direction;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.BlockHitResult;
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
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.UUID;

/**
 * Standalone player-side active tester.
 *
 * It only automates ordinary key states for short, bounded scenarios. It does
 * not change player or vehicle coordinates and does not create movement packets.
 */
public final class PhaseLabActiveClient implements ClientModInitializer {
    private static final String VERSION = "5.2.0";
    private static final String[] SCENARIOS = {
        "PRESS_FORWARD",
        "PULSE_FORWARD",
        "FORWARD_LEFT",
        "FORWARD_RIGHT",
        "BRAKE_RELEASE",
        "FORWARD_BACK_PULSE",
        "DISMOUNT_EDGE",
        "IDLE_CONTROL"
    };
    private static final int MAX_RUNTIME_TICKS = 260;
    private static final double MAX_TRAVEL_BLOCKS = 24.0D;
    private static final double CROSSING_MARGIN = 0.15D;
    private static final int PERSISTENT_CROSSING_TICKS = 5;
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");
    private static final String HEADER =
        "utc_timestamp,run_id,scenario,tick,event,detail,barrier_axis,barrier_threshold,barrier_direction," +
        "progress,max_progress,persistent_crossing_ticks,max_persistent_crossing_ticks," +
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

    private static Barrier barrier;
    private static String runId;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static Entity trackedVehicle;
    private static int trackedVehicleId = -1;
    private static double maxPlayerTravel;
    private static double maxVehicleTravel;
    private static double maxProgress;
    private static int persistentCrossingTicks;
    private static int maxPersistentCrossingTicks;
    private static int dismountTick = -1;
    private static boolean sawCollision;
    private static boolean sawWater;
    private static boolean sawLava;

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

        while (scenarioKey.consumeClick()) {
            if (running) {
                message(player, "Press F12 to abort before changing scenario.", false);
            } else {
                scenarioIndex = (scenarioIndex + 1) % SCENARIOS.length;
                message(player, "Active scenario: " + scenario(), true);
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
        Entity vehicle = player.getVehicle();
        if (vehicle == null || !player.isPassenger()) {
            message(player, "Mount the test boat or vehicle first.", false);
            return;
        }

        Barrier detected = detectBarrier(client);
        if (detected != null) {
            barrier = detected;
        }
        if (barrier == null) {
            message(player, "Look directly at the SIDE of the wall, then press F12.", false);
            return;
        }

        double initialProgress = barrier.progress(vehicle.position());
        if (initialProgress >= -0.05D) {
            message(player, "The vehicle must start on the front side of the selected wall.", false);
            return;
        }

        scenarioTick = 0;
        runId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        playerStart = player.position();
        vehicleStart = vehicle.position();
        trackedVehicle = vehicle;
        trackedVehicleId = vehicle.getId();
        maxPlayerTravel = 0.0D;
        maxVehicleTravel = 0.0D;
        maxProgress = initialProgress;
        persistentCrossingTicks = 0;
        maxPersistentCrossingTicks = 0;
        dismountTick = -1;
        sawCollision = false;
        sawWater = false;
        sawLava = false;

        if (!openOutputs(player)) {
            return;
        }

        running = true;
        writeRow("START", "local_active_test;initial_progress=" + number(initialProgress), player);
        message(player, "RUNNING " + scenario() + " against " + barrier.description() + ". F12 aborts.", false);
    }

    private static void tickRun(Minecraft client, LocalPlayer player) {
        scenarioTick++;
        applyScenario(client);
        updateMetrics(player);
        writeRow("TICK", "active", player);

        if (maxPlayerTravel > MAX_TRAVEL_BLOCKS || maxVehicleTravel > MAX_TRAVEL_BLOCKS) {
            finish(client, player, "SAFETY_ABORT", "travel_cap_exceeded", true);
            return;
        }
        if (scenarioTick >= MAX_RUNTIME_TICKS) {
            finish(client, player, "SAFETY_ABORT", "runtime_cap_exceeded", true);
            return;
        }
        if (scenarioComplete()) {
            finish(client, player, classify(), "scenario_complete", true);
        }
    }

    private static void applyScenario(Minecraft client) {
        setAllMovement(client, false, false, false, false, false);

        switch (scenario()) {
            case "PRESS_FORWARD" -> client.options.keyUp.setDown(scenarioTick <= 160);
            case "PULSE_FORWARD" -> client.options.keyUp.setDown(scenarioTick <= 180 && scenarioTick % 12 < 9);
            case "FORWARD_LEFT" -> {
                client.options.keyUp.setDown(scenarioTick <= 160);
                client.options.keyLeft.setDown(scenarioTick <= 160);
            }
            case "FORWARD_RIGHT" -> {
                client.options.keyUp.setDown(scenarioTick <= 160);
                client.options.keyRight.setDown(scenarioTick <= 160);
            }
            case "BRAKE_RELEASE" -> {
                client.options.keyUp.setDown(scenarioTick <= 70);
                client.options.keyDown.setDown(scenarioTick >= 71 && scenarioTick <= 95);
            }
            case "FORWARD_BACK_PULSE" -> {
                boolean forward = scenarioTick <= 180 && (scenarioTick / 10) % 2 == 0;
                client.options.keyUp.setDown(forward);
                client.options.keyDown.setDown(scenarioTick <= 180 && !forward);
            }
            case "DISMOUNT_EDGE" -> {
                client.options.keyUp.setDown(scenarioTick <= 90);
                client.options.keyShift.setDown(scenarioTick == 55 || scenarioTick == 56);
            }
            case "IDLE_CONTROL" -> {
            }
            default -> {
            }
        }
    }

    private static boolean scenarioComplete() {
        return switch (scenario()) {
            case "PRESS_FORWARD", "FORWARD_LEFT", "FORWARD_RIGHT" -> scenarioTick >= 180;
            case "PULSE_FORWARD", "FORWARD_BACK_PULSE" -> scenarioTick >= 200;
            case "BRAKE_RELEASE" -> scenarioTick >= 130;
            case "DISMOUNT_EDGE", "IDLE_CONTROL" -> scenarioTick >= 120;
            default -> true;
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

        if (observedVehicle != null) {
            Vec3 vehiclePosition = observedVehicle.position();
            maxVehicleTravel = Math.max(maxVehicleTravel, vehiclePosition.distanceTo(vehicleStart));
            double progress = barrier.progress(vehiclePosition);
            maxProgress = Math.max(maxProgress, progress);
            boolean vehicleBoxClear = observedVehicle.level().noCollision(
                observedVehicle,
                observedVehicle.getBoundingBox().deflate(0.001D)
            );
            sawCollision |= !vehicleBoxClear;
            sawWater |= observedVehicle.isInWater();
            sawLava |= observedVehicle.isInLava();

            if (progress > CROSSING_MARGIN) {
                persistentCrossingTicks++;
                maxPersistentCrossingTicks = Math.max(maxPersistentCrossingTicks, persistentCrossingTicks);
            } else {
                persistentCrossingTicks = 0;
            }
        }
    }

    private static String classify() {
        if (maxPersistentCrossingTicks >= PERSISTENT_CROSSING_TICKS) {
            return "LOCAL_REPRODUCED";
        }
        if (maxProgress > CROSSING_MARGIN) {
            return "LOCAL_TRANSIENT";
        }
        if (dismountTick >= 0 && !"DISMOUNT_EDGE".equals(scenario())) {
            return "UNEXPECTED_DISMOUNT";
        }
        if ("DISMOUNT_EDGE".equals(scenario()) && dismountTick >= 0) {
            return "DISMOUNT_COMPLETED";
        }
        if (maxVehicleTravel < 0.25D) {
            return "NO_MOVEMENT";
        }
        return "BLOCKED_OR_REJECTED";
    }

    private static void finish(Minecraft client, LocalPlayer player, String verdict, String reason, boolean showMessage) {
        stopKeys(client);
        if (running) {
            writeRow(
                "FINISH",
                "verdict=" + verdict
                    + ";reason=" + clean(reason)
                    + ";max_player_travel=" + number(maxPlayerTravel)
                    + ";max_vehicle_travel=" + number(maxVehicleTravel)
                    + ";max_progress=" + number(maxProgress)
                    + ";max_persistent_crossing_ticks=" + maxPersistentCrossingTicks
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
            message(player, "Active CSV: " + outputPath(), false);
            scenarioIndex = (scenarioIndex + 1) % SCENARIOS.length;
            message(player, "Next scenario: " + scenario(), true);
        }
    }

    private static Barrier detectBarrier(Minecraft client) {
        if (!(client.hitResult instanceof BlockHitResult hit)) {
            return null;
        }
        Direction face = hit.getDirection();
        var pos = hit.getBlockPos();
        return switch (face) {
            case WEST -> new Barrier('X', pos.getX() + 1.0D, 1.0D, "X+ beyond block " + pos.toShortString());
            case EAST -> new Barrier('X', pos.getX(), -1.0D, "X- beyond block " + pos.toShortString());
            case NORTH -> new Barrier('Z', pos.getZ() + 1.0D, 1.0D, "Z+ beyond block " + pos.toShortString());
            case SOUTH -> new Barrier('Z', pos.getZ(), -1.0D, "Z- beyond block " + pos.toShortString());
            default -> null;
        };
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
        OUTPUT_PATHS[0] = configDir.resolve("active-v5.2-" + runId + ".csv");
        OUTPUT_PATHS[1] = gameDir.resolve("PHASELAB_ACTIVE_LATEST.csv");
        summaryPath = gameDir.resolve("PHASELAB_ACTIVE_SUMMARY.txt");

        try {
            Files.createDirectories(configDir);
            WRITERS[0] = Files.newBufferedWriter(
                OUTPUT_PATHS[0], StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE
            );
            WRITERS[1] = Files.newBufferedWriter(
                OUTPUT_PATHS[1], StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
            );
            for (BufferedWriter writer : WRITERS) {
                writer.write(HEADER);
                writer.newLine();
                writer.flush();
            }
            return true;
        } catch (IOException exception) {
            closeOutputs();
            message(player, "Could not open active CSV: " + clean(exception.getMessage()), false);
            return false;
        }
    }

    private static synchronized void writeRow(String event, String detail, LocalPlayer player) {
        if (!hasWriter()) {
            return;
        }
        Entity vehicle = player == null ? trackedVehicle : (player.getVehicle() != null ? player.getVehicle() : trackedVehicle);
        Vec3 playerPos = player == null ? null : player.position();
        Vec3 playerDelta = player == null ? null : player.getDeltaMovement();
        Vec3 vehiclePos = vehicle == null ? null : vehicle.position();
        Vec3 vehicleDelta = vehicle == null ? null : vehicle.getDeltaMovement();
        boolean vehicleBoxClear = vehicle != null && vehicle.level().noCollision(
            vehicle,
            vehicle.getBoundingBox().deflate(0.001D)
        );
        double progress = vehiclePos == null || barrier == null ? Double.NaN : barrier.progress(vehiclePos);
        Minecraft client = Minecraft.getInstance();

        String row = String.join(",",
            csv(Instant.now().toString()),
            csv(runId),
            csv(scenario()),
            Integer.toString(scenarioTick),
            csv(event),
            csv(detail),
            barrier == null ? "" : csv(Character.toString(barrier.axis())),
            barrier == null ? "" : number(barrier.threshold()),
            barrier == null ? "" : number(barrier.direction()),
            number(progress),
            number(maxProgress),
            Integer.toString(persistentCrossingTicks),
            Integer.toString(maxPersistentCrossingTicks),
            vectorField(playerPos, 0), vectorField(playerPos, 1), vectorField(playerPos, 2),
            vectorField(playerDelta, 0), vectorField(playerDelta, 1), vectorField(playerDelta, 2),
            Boolean.toString(player != null && player.isPassenger()),
            Boolean.toString(player != null && player.horizontalCollision),
            Boolean.toString(player != null && player.isInWater()),
            Boolean.toString(player != null && player.isInLava()),
            vehicle == null ? "" : Integer.toString(vehicle.getId()),
            vehicle == null ? "" : csv(vehicle.getType().toString()),
            vectorField(vehiclePos, 0), vectorField(vehiclePos, 1), vectorField(vehiclePos, 2),
            vectorField(vehicleDelta, 0), vectorField(vehicleDelta, 1), vectorField(vehicleDelta, 2),
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
        String text = "PhaseLab Active v" + VERSION + System.lineSeparator()
            + "run=" + runId + System.lineSeparator()
            + "scenario=" + scenario() + System.lineSeparator()
            + "verdict=" + verdict + System.lineSeparator()
            + "reason=" + clean(reason) + System.lineSeparator()
            + "barrier=" + (barrier == null ? "none" : barrier.description()) + System.lineSeparator()
            + "max_player_travel=" + number(maxPlayerTravel) + System.lineSeparator()
            + "max_vehicle_travel=" + number(maxVehicleTravel) + System.lineSeparator()
            + "max_progress=" + number(maxProgress) + System.lineSeparator()
            + "max_persistent_crossing_ticks=" + maxPersistentCrossingTicks + System.lineSeparator()
            + "dismount_tick=" + dismountTick + System.lineSeparator()
            + "collision=" + sawCollision + System.lineSeparator()
            + "water=" + sawWater + System.lineSeparator()
            + "lava=" + sawLava + System.lineSeparator()
            + "note=LOCAL_REPRODUCED is a client-observed candidate and should be confirmed with server logs." + System.lineSeparator();
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
        return OUTPUT_PATHS[1] == null ? "PHASELAB_ACTIVE_LATEST.csv" : OUTPUT_PATHS[1].toAbsolutePath().toString();
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

    private record Barrier(char axis, double threshold, double direction, String description) {
        double progress(Vec3 position) {
            double coordinate = axis == 'X' ? position.x : position.z;
            return direction * (coordinate - threshold);
        }
    }
}
