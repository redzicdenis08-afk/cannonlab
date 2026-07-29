package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ServerboundMoveVehiclePacket;
import net.minecraft.resources.Identifier;
import net.minecraft.world.InteractionHand;
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
import java.util.Locale;

/**
 * Adaptive vehicle movement laboratory for servers the user owns or is
 * authorized to test. It deliberately uses short, tick-paced segments and
 * treats a successful normal remount as the only usable proof that a vehicle
 * remained at its advanced server position after rider separation.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final double STEP = 0.25D;
    private static final double BOAT_FORWARD_SEGMENT = 2.0D;
    private static final double HORSE_FORWARD_SEGMENT = 4.0D;
    private static final double DOWN_SEGMENT = 0.75D;
    private static final int BOAT_PACKETS_PER_TICK = 1;
    private static final int HORSE_PACKETS_PER_TICK = 4;
    private static final int DOWN_PACKETS_PER_TICK = 1;
    private static final int SETTLE_TICKS = 7;
    private static final int REMOUNT_TIMEOUT_TICKS = 36;
    private static final int REMOUNT_INTERVAL_TICKS = 4;
    private static final double REMOUNT_RANGE_SQUARED = 25.0D;
    private static final double MAX_DISTANCE = 512.0D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;

    private enum Mode {
        FORWARD,
        DOWN
    }

    private enum State {
        MOVING,
        SETTLING,
        REMOUNTING
    }

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "adaptive_vehicle")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static boolean readyMessageShown;
    private static LocalPlayer activePlayer;
    private static Entity activeVehicle;
    private static Mode mode;
    private static State state;
    private static Vec3 direction;
    private static Vec3 segmentStart;
    private static Vec3 lastSentTarget;
    private static double segmentLength;
    private static double segmentSent;
    private static double travelled;
    private static int sentPackets;
    private static int packetsPerTick;
    private static int acceptedSegments;
    private static int settleTicksRemaining;
    private static int remountTicks;
    private static int correctionCount;
    private static boolean originalVehicleNoPhysics;
    private static String vehicleLabel;
    private static BufferedWriter logWriter;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_toggle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    /** Called at TAIL after Minecraft applies a real server player correction. */
    public static void onServerPlayerCorrectionApplied() {
        if (!active) {
            return;
        }
        correctionCount++;
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_PLAYER_CORRECTION", player, activeVehicle == null ? null : activeVehicle.position());

        if (player == null || activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "REJECTED: server correction removed the usable vehicle state.", true);
            return;
        }

        Entity controlled = controlledVehicle(player);
        if (controlled == activeVehicle) {
            // Riding-player sync packets are not automatically failures. Keep a
            // short settle window and require the mount to remain authoritative.
            state = State.SETTLING;
            settleTicksRemaining = SETTLE_TICKS;
            actionbar(player, "Server synced the rider; checking whether the mount remains accepted...");
            return;
        }

        if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
            beginRemount(player, "Server separated rider and vehicle; validating with a normal remount...");
            return;
        }

        stop(player, "REJECTED: the server returned you outside remount range.", true);
    }

    /** Called at TAIL after Minecraft applies a real server vehicle correction. */
    public static void onServerVehicleCorrectionApplied() {
        if (!active) {
            return;
        }
        correctionCount++;
        LocalPlayer player = Minecraft.getInstance().player;
        if (player == null || activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "REJECTED: the server removed or replaced the vehicle.", true);
            return;
        }

        Vec3 serverVehiclePosition = activeVehicle.position();
        double progress = projectedProgress(segmentStart, serverVehiclePosition, direction);
        log("SERVER_VEHICLE_CORRECTION", player, serverVehiclePosition);

        if (progress >= Math.max(STEP, segmentLength * 0.45D)) {
            // The correction retained meaningful forward/downward progress. Use
            // the corrected position as the next authoritative segment anchor.
            segmentStart = serverVehiclePosition;
            lastSentTarget = serverVehiclePosition;
            segmentSent = 0.0D;
            Entity controlled = controlledVehicle(player);
            if (controlled == activeVehicle) {
                state = State.SETTLING;
                settleTicksRemaining = SETTLE_TICKS;
                actionbar(player, String.format(Locale.ROOT,
                    "Server retained %.2f blocks of this segment; stabilizing...", progress));
            } else if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
                beginRemount(player, String.format(Locale.ROOT,
                    "Server retained %.2f blocks but separated the rider; remounting...", progress));
            } else {
                stop(player, "PARTIAL: vehicle advanced but ended outside normal remount reach.", true);
            }
            return;
        }

        stop(player, String.format(Locale.ROOT,
            "REJECTED: server returned the vehicle after only %.2f segment progress.", progress), true);
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            readyMessageShown = false;
            stop(null, null, false);
            return;
        }

        if (!readyMessageShown) {
            readyMessageShown = true;
            message(player,
                "Adaptive 4.8 loaded. Mount a boat/horse. Face forward or look steeply down, then press P. O aborts.");
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                stop(player, "Adaptive phase stopped manually.", false);
            } else {
                start(player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) {
                stop(player, "Adaptive phase emergency-aborted.", false);
            }
        }

        if (!active) {
            return;
        }

        activePlayer = player;
        if (activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "Vehicle disappeared.", true);
            return;
        }

        if (travelled >= MAX_DISTANCE) {
            stop(player, "Safety limit reached.", false);
            return;
        }

        switch (state) {
            case REMOUNTING -> tickRemount(client, player);
            case SETTLING -> tickSettle(player);
            case MOVING -> tickMove(player);
        }
    }

    private static void tickMove(LocalPlayer player) {
        Entity controlled = controlledVehicle(player);
        if (controlled != activeVehicle) {
            if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
                beginRemount(player, "Mount state changed; validating with a normal remount...");
            } else {
                stop(player, "DISMOUNTED outside remount reach.", true);
            }
            return;
        }

        for (int i = 0; i < packetsPerTick && segmentSent < segmentLength - 1.0E-9D; i++) {
            Vec3 next = activeVehicle.position().add(direction.scale(STEP));
            activeVehicle.noPhysics = true;
            activeVehicle.setPos(next.x, next.y, next.z);
            // Deliberately do NOT force player.setPos(). The server's vehicle
            // handler and passenger logic own rider synchronization.
            player.connection.send(new ServerboundMoveVehiclePacket(
                next,
                activeVehicle.getYRot(),
                activeVehicle.getXRot(),
                mode == Mode.DOWN ? false : activeVehicle.onGround()
            ));
            lastSentTarget = next;
            segmentSent += STEP;
            travelled += STEP;
            sentPackets++;
            log("SEND_STEP", player, next);
        }

        actionbar(player, String.format(Locale.ROOT,
            "%s %s | %.2f/%.2f segment | %.1f total | %d accepted segments",
            vehicleLabel,
            mode == Mode.DOWN ? "DOWN" : directionLabel(direction),
            segmentSent,
            segmentLength,
            travelled,
            acceptedSegments
        ));

        if (segmentSent >= segmentLength - 1.0E-9D) {
            state = State.SETTLING;
            settleTicksRemaining = SETTLE_TICKS;
            log("SEGMENT_SENT", player, lastSentTarget);
        }
    }

    private static void tickSettle(LocalPlayer player) {
        Entity controlled = controlledVehicle(player);
        if (controlled != activeVehicle) {
            if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
                beginRemount(player, "Segment separated rider and vehicle; trying a normal remount...");
            } else {
                stop(player, "DISMOUNTED after segment outside remount reach.", true);
            }
            return;
        }

        settleTicksRemaining--;
        actionbar(player, String.format(Locale.ROOT,
            "Settling segment... %d/%d | corrections seen: %d",
            SETTLE_TICKS - Math.max(settleTicksRemaining, 0),
            SETTLE_TICKS,
            correctionCount
        ));
        if (settleTicksRemaining > 0) {
            return;
        }

        acceptedSegments++;
        segmentStart = activeVehicle.position();
        lastSentTarget = segmentStart;
        segmentSent = 0.0D;
        state = State.MOVING;
        log("SEGMENT_ACCEPTED_NO_SETBACK", player, segmentStart);
    }

    private static void tickRemount(Minecraft client, LocalPlayer player) {
        Entity controlled = controlledVehicle(player);
        if (controlled == activeVehicle) {
            remountTicks = 0;
            acceptedSegments++;
            segmentStart = activeVehicle.position();
            lastSentTarget = segmentStart;
            segmentSent = 0.0D;
            state = State.SETTLING;
            settleTicksRemaining = SETTLE_TICKS;
            message(player, "Server accepted a normal remount. Continuing from the vehicle's current position.");
            log("REMOUNT_ACCEPTED", player, activeVehicle.position());
            return;
        }

        remountTicks++;
        if (activeVehicle.isRemoved() || player.distanceToSqr(activeVehicle) > REMOUNT_RANGE_SQUARED) {
            stop(player, "REMOUNT FAILED: vehicle vanished or moved beyond normal reach.", true);
            return;
        }
        if (remountTicks > REMOUNT_TIMEOUT_TICKS) {
            stop(player, "REMOUNT BLOCKED: server refused normal interaction with the advanced vehicle.", true);
            return;
        }

        if (client.gameMode != null && remountTicks % REMOUNT_INTERVAL_TICKS == 1) {
            client.gameMode.interact(player, activeVehicle, InteractionHand.MAIN_HAND);
            log("REMOUNT_INTERACT", player, activeVehicle.position());
        }
        actionbar(player, String.format(Locale.ROOT,
            "Remount validation... %d/%d | distance %.2f",
            remountTicks,
            REMOUNT_TIMEOUT_TICKS,
            Math.sqrt(player.distanceToSqr(activeVehicle))
        ));
    }

    private static void beginRemount(LocalPlayer player, String reason) {
        state = State.REMOUNTING;
        remountTicks = 0;
        message(player, reason);
        log("REMOUNT_BEGIN", player, activeVehicle == null ? null : activeVehicle.position());
    }

    private static void start(LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            message(player, "Mount and control a boat or saddled horse first, then press P.");
            return;
        }
        if (!isBoat(vehicle) && !isHorse(vehicle)) {
            message(player, "Adaptive mode supports boats and horses only.");
            return;
        }

        boolean horse = isHorse(vehicle);
        vehicleLabel = horse ? "Horse" : "Boat";
        mode = player.getXRot() >= DOWN_PITCH_THRESHOLD ? Mode.DOWN : Mode.FORWARD;
        if (mode == Mode.DOWN) {
            direction = new Vec3(0.0D, -1.0D, 0.0D);
            segmentLength = DOWN_SEGMENT;
            packetsPerTick = DOWN_PACKETS_PER_TICK;
        } else {
            direction = nearestCardinal(player.getYRot());
            segmentLength = horse ? HORSE_FORWARD_SEGMENT : BOAT_FORWARD_SEGMENT;
            packetsPerTick = horse ? HORSE_PACKETS_PER_TICK : BOAT_PACKETS_PER_TICK;
        }

        active = true;
        activePlayer = player;
        activeVehicle = vehicle;
        state = State.MOVING;
        segmentStart = vehicle.position();
        lastSentTarget = segmentStart;
        segmentSent = 0.0D;
        travelled = 0.0D;
        sentPackets = 0;
        acceptedSegments = 0;
        settleTicksRemaining = 0;
        remountTicks = 0;
        correctionCount = 0;
        originalVehicleNoPhysics = vehicle.noPhysics;
        vehicle.noPhysics = true;
        openLog();
        log("START", player, vehicle.position());
        message(player, String.format(Locale.ROOT,
            "%s adaptive %s started. %.2f-block segments, %d x 0.25 packets per tick.",
            vehicleLabel,
            mode == Mode.DOWN ? "DOWN" : directionLabel(direction),
            segmentLength,
            packetsPerTick
        ));
    }

    private static Vec3 nearestCardinal(float yaw) {
        int cardinal = Math.floorMod((int) Math.round(yaw / 90.0D), 4);
        return switch (cardinal) {
            case 0 -> new Vec3(0.0D, 0.0D, 1.0D);
            case 1 -> new Vec3(-1.0D, 0.0D, 0.0D);
            case 2 -> new Vec3(0.0D, 0.0D, -1.0D);
            default -> new Vec3(1.0D, 0.0D, 0.0D);
        };
    }

    private static double projectedProgress(Vec3 start, Vec3 current, Vec3 vector) {
        if (start == null || current == null || vector == null) {
            return 0.0D;
        }
        return current.subtract(start).dot(vector.normalize());
    }

    private static String directionLabel(Vec3 vector) {
        if (vector.y < -0.5D) {
            return "DOWN";
        }
        double degrees = Math.toDegrees(Math.atan2(-vector.x, vector.z));
        if (degrees < 0.0D) {
            degrees += 360.0D;
        }
        String[] labels = {"S", "SW", "W", "NW", "N", "NE", "E", "SE"};
        return labels[(int) Math.round(degrees / 45.0D) & 7];
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        Entity vehicle = player.getRootVehicle();
        if (vehicle == player || vehicle.getControllingPassenger() != player) {
            return null;
        }
        return vehicle;
    }

    private static boolean isBoat(Entity vehicle) {
        return vehicle.getType().toString().toLowerCase(Locale.ROOT).contains("boat");
    }

    private static boolean isHorse(Entity vehicle) {
        return vehicle.getType().toString().toLowerCase(Locale.ROOT).contains("horse");
    }

    private static void stop(LocalPlayer player, String reason, boolean rejected) {
        if (!active && logWriter == null) {
            return;
        }

        if (activeVehicle != null) {
            activeVehicle.noPhysics = originalVehicleNoPhysics;
            activeVehicle.setDeltaMovement(Vec3.ZERO);
        }

        if (player != null) {
            log(rejected ? "STOP_REJECTED" : "STOP", player,
                activeVehicle == null ? null : activeVehicle.position());
            if (reason != null) {
                message(player, reason + String.format(Locale.ROOT,
                    " Travelled %.2f blocks, %d packets, %d accepted/remounted segments.",
                    travelled, sentPackets, acceptedSegments));
            }
        }

        active = false;
        activePlayer = null;
        activeVehicle = null;
        mode = null;
        state = null;
        direction = null;
        segmentStart = null;
        lastSentTarget = null;
        segmentLength = 0.0D;
        segmentSent = 0.0D;
        travelled = 0.0D;
        sentPackets = 0;
        acceptedSegments = 0;
        settleTicksRemaining = 0;
        remountTicks = 0;
        correctionCount = 0;
        packetsPerTick = 0;
        closeLog();
    }

    private static void openLog() {
        closeLog();
        try {
            Path directory = Minecraft.getInstance().gameDirectory.toPath()
                .resolve("config")
                .resolve("phaselab");
            Files.createDirectories(directory);
            Path logPath = directory.resolve(
                "adaptive-vehicle-v4.8-" + Instant.now().toString().replace(':', '-') + ".csv"
            );
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write(
                "time,event,mode,state,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,travelled,segment_sent,packets,accepted,corrections\n"
            );
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
        }
    }

    private static void log(String event, LocalPlayer player, Vec3 vehiclePosition) {
        if (logWriter == null) {
            return;
        }
        Vec3 playerPosition = player == null ? Vec3.ZERO : player.position();
        Vec3 vehicle = vehiclePosition == null ? Vec3.ZERO : vehiclePosition;
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%s,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%d,%d,%d%n",
                Instant.now(),
                event,
                mode == null ? "NONE" : mode,
                state == null ? "NONE" : state,
                playerPosition.x, playerPosition.y, playerPosition.z,
                vehicle.x, vehicle.y, vehicle.z,
                travelled,
                segmentSent,
                sentPackets,
                acceptedSegments,
                correctionCount
            ));
            logWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private static void closeLog() {
        if (logWriter != null) {
            try {
                logWriter.close();
            } catch (IOException ignored) {
            }
        }
        logWriter = null;
    }

    private static void message(LocalPlayer player, String text) {
        if (player != null) {
            player.displayClientMessage(Component.literal("[PhaseLab] " + text), false);
        }
    }

    private static void actionbar(LocalPlayer player, String text) {
        if (player != null) {
            player.displayClientMessage(Component.literal("[PhaseLab] " + text), true);
        }
    }
}
