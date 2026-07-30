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
 * Pulse-based vehicle movement laboratory for servers the user owns or is
 * explicitly authorized to test.
 *
 * The important design rule is silence during rider/vehicle reconciliation:
 * one short movement pulse, no movement packets while the server settles, one
 * normal remount attempt, then a full stable-mount window before continuing.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final double STEP = 0.25D;

    // The boat profile preserves the movement family the user reproduced by
    // hand. Horse is intentionally independent and more conservative.
    private static final double BOAT_FORWARD_SEGMENT = 2.0D;
    private static final double BOAT_DOWN_SEGMENT = 0.75D;
    private static final double HORSE_FORWARD_SEGMENT = 1.0D;
    private static final double HORSE_DOWN_SEGMENT = 0.50D;

    private static final int BOAT_FORWARD_PACKETS_PER_TICK = 1;
    private static final int BOAT_DOWN_PACKETS_PER_TICK = 1;
    private static final int HORSE_FORWARD_PACKETS_PER_TICK = 2;
    private static final int HORSE_DOWN_PACKETS_PER_TICK = 1;

    private static final int POST_SEGMENT_SETTLE_TICKS = 10;
    private static final int SEPARATION_QUIET_TICKS = 8;
    private static final int AUTO_REMOUNT_RESULT_TICKS = 12;
    private static final int MANUAL_REMOUNT_TIMEOUT_TICKS = 120;
    private static final int REMOUNT_STABLE_TICKS = 20;
    private static final int MAX_RECONCILE_ATTEMPTS_PER_SEGMENT = 3;

    private static final double REMOUNT_RANGE_SQUARED = 25.0D;
    private static final double MAX_DISTANCE = 512.0D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;

    private enum Mode {
        FORWARD,
        DOWN
    }

    private enum State {
        MOVING,
        POST_SEGMENT_SETTLE,
        SEPARATION_QUIET,
        AUTO_REMOUNT_WAIT,
        MANUAL_REMOUNT_WAIT,
        REMOUNT_STABILIZE
    }

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "pulse_vehicle")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static boolean readyMessageShown;
    private static Entity activeVehicle;
    private static Mode mode;
    private static State state;
    private static Vec3 direction;
    private static Vec3 segmentAnchor;
    private static Vec3 lastSentTarget;
    private static double segmentLength;
    private static double segmentSent;
    private static double attemptedDistance;
    private static double acceptedDistance;
    private static int packetsPerTick;
    private static int sentPackets;
    private static int acceptedSegments;
    private static int correctionCount;
    private static int stateTicks;
    private static int reconcileAttempts;
    private static int separationCount;
    private static boolean autoRemountSent;
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

    /** Called at TAIL after vanilla applies a real server player correction. */
    public static void onServerPlayerCorrectionApplied() {
        if (!active) {
            return;
        }
        correctionCount++;
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_PLAYER_CORRECTION", player, vehiclePosition());

        if (player == null || activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "REJECTED: server correction removed the usable vehicle state.", true);
            return;
        }

        Entity controlled = controlledVehicle(player);
        if (controlled == activeVehicle) {
            // Riding-player synchronization is common and is not itself a
            // rejection. Require a quiet server window before doing more.
            state = State.POST_SEGMENT_SETTLE;
            stateTicks = POST_SEGMENT_SETTLE_TICKS;
            actionbar(player, "Server synchronized the rider. Holding all movement packets...");
            return;
        }

        if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
            beginSeparationQuiet(player,
                "Server separated rider and vehicle. Waiting before one clean remount attempt...");
            return;
        }

        stop(player, "PARTIAL: vehicle moved, but the server returned you outside normal remount reach.", true);
    }

    /** Called at TAIL after vanilla applies a real server vehicle correction. */
    public static void onServerVehicleCorrectionApplied() {
        if (!active) {
            return;
        }
        correctionCount++;
        LocalPlayer player = Minecraft.getInstance().player;
        if (player == null || activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "REJECTED: server removed or replaced the vehicle.", true);
            return;
        }

        Vec3 serverPosition = activeVehicle.position();
        double retainedProgress = projectedProgress(segmentAnchor, serverPosition, direction);
        log("SERVER_VEHICLE_CORRECTION", player, serverPosition);

        if (retainedProgress < STEP * 0.45D) {
            stop(player, String.format(Locale.ROOT,
                "REJECTED: server returned the vehicle after %.2f blocks of segment progress.",
                retainedProgress), true);
            return;
        }

        Entity controlled = controlledVehicle(player);
        if (controlled == activeVehicle) {
            state = State.POST_SEGMENT_SETTLE;
            stateTicks = POST_SEGMENT_SETTLE_TICKS;
            actionbar(player, String.format(Locale.ROOT,
                "Server retained %.2f blocks. Stabilizing the accepted position...", retainedProgress));
        } else if (player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED) {
            beginSeparationQuiet(player, String.format(Locale.ROOT,
                "Server retained %.2f blocks and separated the rider. Waiting before remount...",
                retainedProgress));
        } else {
            stop(player, String.format(Locale.ROOT,
                "PARTIAL: vehicle retained %.2f blocks but ended outside normal remount reach.",
                retainedProgress), true);
        }
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
                "Pulse 5.1 loaded. Mount boat/horse, face forward or look down, press P. O aborts.");
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                stop(player, "Pulse phase stopped manually.", false);
            } else {
                start(player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) {
                stop(player, "Pulse phase emergency-aborted.", false);
            }
        }

        if (!active) {
            return;
        }
        if (activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "Vehicle disappeared.", true);
            return;
        }
        if (attemptedDistance >= MAX_DISTANCE) {
            stop(player, "Safety distance reached.", false);
            return;
        }

        switch (state) {
            case MOVING -> tickMoving(player);
            case POST_SEGMENT_SETTLE -> tickPostSegmentSettle(player);
            case SEPARATION_QUIET -> tickSeparationQuiet(client, player);
            case AUTO_REMOUNT_WAIT -> tickAutoRemountWait(player);
            case MANUAL_REMOUNT_WAIT -> tickManualRemountWait(player);
            case REMOUNT_STABILIZE -> tickRemountStabilize(player);
        }
    }

    private static void tickMoving(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            beginSeparationQuiet(player,
                "Mount state changed. Holding packets before remount validation...");
            return;
        }

        for (int i = 0; i < packetsPerTick && segmentSent < segmentLength - 1.0E-9D; i++) {
            Vec3 next = activeVehicle.position().add(direction.scale(STEP));
            activeVehicle.noPhysics = true;
            activeVehicle.setPos(next.x, next.y, next.z);
            // Never force player.setPos(). Vanilla passenger synchronization and
            // the server own the rider position.
            player.connection.send(new ServerboundMoveVehiclePacket(
                next,
                activeVehicle.getYRot(),
                activeVehicle.getXRot(),
                mode != Mode.DOWN && activeVehicle.onGround()
            ));
            lastSentTarget = next;
            segmentSent += STEP;
            attemptedDistance += STEP;
            sentPackets++;
            log("SEND_STEP", player, next);
        }

        actionbar(player, String.format(Locale.ROOT,
            "%s %s pulse %.2f/%.2f | accepted %.2f | packets %d",
            vehicleLabel,
            mode == Mode.DOWN ? "DOWN" : directionLabel(direction),
            segmentSent,
            segmentLength,
            acceptedDistance,
            sentPackets
        ));

        if (segmentSent >= segmentLength - 1.0E-9D) {
            state = State.POST_SEGMENT_SETTLE;
            stateTicks = POST_SEGMENT_SETTLE_TICKS;
            log("PULSE_SENT", player, lastSentTarget);
        }
    }

    private static void tickPostSegmentSettle(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            beginSeparationQuiet(player,
                "Pulse separated rider and vehicle. Waiting for server reconciliation...");
            return;
        }

        stateTicks--;
        actionbar(player, String.format(Locale.ROOT,
            "Silent settle %d/%d | do not move",
            POST_SEGMENT_SETTLE_TICKS - Math.max(stateTicks, 0),
            POST_SEGMENT_SETTLE_TICKS
        ));
        if (stateTicks > 0) {
            return;
        }

        acceptCurrentPulse(player, "PULSE_ACCEPTED_MOUNT_STABLE");
    }

    private static void tickSeparationQuiet(Minecraft client, LocalPlayer player) {
        Entity controlled = controlledVehicle(player);
        if (controlled == activeVehicle) {
            beginRemountStabilize(player, "Mount returned during the quiet window. Verifying stability...");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            stop(player, "PARTIAL: vehicle moved beyond normal remount reach.", true);
            return;
        }

        stateTicks--;
        actionbar(player, String.format(Locale.ROOT,
            "Server separated rider/vehicle. Quiet window %d/%d",
            SEPARATION_QUIET_TICKS - Math.max(stateTicks, 0),
            SEPARATION_QUIET_TICKS
        ));
        if (stateTicks > 0) {
            return;
        }

        if (!autoRemountSent && client.gameMode != null) {
            autoRemountSent = true;
            client.gameMode.interact(player, activeVehicle, InteractionHand.MAIN_HAND);
            log("AUTO_REMOUNT_SINGLE_INTERACT", player, activeVehicle.position());
        }
        state = State.AUTO_REMOUNT_WAIT;
        stateTicks = AUTO_REMOUNT_RESULT_TICKS;
    }

    private static void tickAutoRemountWait(LocalPlayer player) {
        if (controlledVehicle(player) == activeVehicle) {
            beginRemountStabilize(player, "Server accepted the single normal remount. Stabilizing...");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            stop(player, "PARTIAL: vehicle left normal reach before remount completed.", true);
            return;
        }

        stateTicks--;
        actionbar(player, "Waiting for one clean remount result...");
        if (stateTicks > 0) {
            return;
        }

        state = State.MANUAL_REMOUNT_WAIT;
        stateTicks = MANUAL_REMOUNT_TIMEOUT_TICKS;
        message(player,
            "Auto-remount did not register. Right-click the SAME vehicle once; PhaseLab will resume automatically.");
        log("MANUAL_REMOUNT_REQUESTED", player, activeVehicle.position());
    }

    private static void tickManualRemountWait(LocalPlayer player) {
        if (controlledVehicle(player) == activeVehicle) {
            beginRemountStabilize(player, "Manual remount detected. Verifying one full second of stable mount...");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            stop(player, "PARTIAL: vehicle vanished or moved beyond normal manual-remount reach.", true);
            return;
        }

        stateTicks--;
        actionbar(player, String.format(Locale.ROOT,
            "Right-click the same %s once | waiting %.1fs",
            vehicleLabel.toLowerCase(Locale.ROOT),
            Math.max(stateTicks, 0) / 20.0D
        ));
        if (stateTicks <= 0) {
            stop(player, "REMOUNT BLOCKED: server never accepted a normal remount.", true);
        }
    }

    private static void tickRemountStabilize(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            if (reconcileAttempts >= MAX_RECONCILE_ATTEMPTS_PER_SEGMENT) {
                stop(player, "UNSTABLE: server repeatedly separated the same pulse after remount.", true);
            } else {
                beginSeparationQuiet(player,
                    "Mount separated during stabilization. Retrying after another quiet window...");
            }
            return;
        }

        stateTicks--;
        actionbar(player, String.format(Locale.ROOT,
            "Remount stable-check %d/%d | no movement packets",
            REMOUNT_STABLE_TICKS - Math.max(stateTicks, 0),
            REMOUNT_STABLE_TICKS
        ));
        if (stateTicks > 0) {
            return;
        }

        acceptCurrentPulse(player, "PULSE_ACCEPTED_AFTER_STABLE_REMOUNT");
    }

    private static void beginSeparationQuiet(LocalPlayer player, String reason) {
        separationCount++;
        reconcileAttempts++;
        state = State.SEPARATION_QUIET;
        stateTicks = SEPARATION_QUIET_TICKS;
        autoRemountSent = false;
        message(player, reason);
        log("SEPARATION_QUIET_BEGIN", player, vehiclePosition());
    }

    private static void beginRemountStabilize(LocalPlayer player, String reason) {
        state = State.REMOUNT_STABILIZE;
        stateTicks = REMOUNT_STABLE_TICKS;
        message(player, reason);
        log("REMOUNT_STABILIZE_BEGIN", player, vehiclePosition());
    }

    private static void acceptCurrentPulse(LocalPlayer player, String event) {
        Vec3 current = activeVehicle.position();
        double retained = Math.max(0.0D, projectedProgress(segmentAnchor, current, direction));
        acceptedDistance += retained;
        acceptedSegments++;
        segmentAnchor = current;
        lastSentTarget = current;
        segmentSent = 0.0D;
        reconcileAttempts = 0;
        autoRemountSent = false;
        state = State.MOVING;
        log(event, player, current);
        message(player, String.format(Locale.ROOT,
            "Pulse accepted: %.2f retained blocks. Total accepted %.2f.", retained, acceptedDistance));
    }

    private static void start(LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            message(player, "Mount and control a boat or saddled horse first, then press P.");
            return;
        }
        if (!isBoat(vehicle) && !isHorse(vehicle)) {
            message(player, "Pulse mode supports boats and horses only.");
            return;
        }

        boolean horse = isHorse(vehicle);
        vehicleLabel = horse ? "Horse" : "Boat";
        mode = player.getXRot() >= DOWN_PITCH_THRESHOLD ? Mode.DOWN : Mode.FORWARD;
        if (mode == Mode.DOWN) {
            direction = new Vec3(0.0D, -1.0D, 0.0D);
            segmentLength = horse ? HORSE_DOWN_SEGMENT : BOAT_DOWN_SEGMENT;
            packetsPerTick = horse ? HORSE_DOWN_PACKETS_PER_TICK : BOAT_DOWN_PACKETS_PER_TICK;
        } else {
            direction = nearestCardinal(player.getYRot());
            segmentLength = horse ? HORSE_FORWARD_SEGMENT : BOAT_FORWARD_SEGMENT;
            packetsPerTick = horse ? HORSE_FORWARD_PACKETS_PER_TICK : BOAT_FORWARD_PACKETS_PER_TICK;
        }

        active = true;
        activeVehicle = vehicle;
        state = State.MOVING;
        segmentAnchor = vehicle.position();
        lastSentTarget = segmentAnchor;
        segmentSent = 0.0D;
        attemptedDistance = 0.0D;
        acceptedDistance = 0.0D;
        sentPackets = 0;
        acceptedSegments = 0;
        correctionCount = 0;
        stateTicks = 0;
        reconcileAttempts = 0;
        separationCount = 0;
        autoRemountSent = false;
        originalVehicleNoPhysics = vehicle.noPhysics;
        vehicle.noPhysics = true;
        openLog();
        log("START", player, vehicle.position());
        message(player, String.format(Locale.ROOT,
            "%s pulse %s started. %.2f-block pulse, %d packet(s)/tick. P stops; O aborts.",
            vehicleLabel,
            mode == Mode.DOWN ? "DOWN" : directionLabel(direction),
            segmentLength,
            packetsPerTick
        ));
    }

    private static boolean vehicleWithinRemountReach(LocalPlayer player) {
        return activeVehicle != null
            && !activeVehicle.isRemoved()
            && player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED;
    }

    private static Vec3 vehiclePosition() {
        return activeVehicle == null ? null : activeVehicle.position();
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
            log(rejected ? "STOP_REJECTED" : "STOP", player, vehiclePosition());
            if (reason != null) {
                message(player, reason + String.format(Locale.ROOT,
                    " Attempted %.2f, server-retained %.2f, packets %d, accepted pulses %d, separations %d.",
                    attemptedDistance,
                    acceptedDistance,
                    sentPackets,
                    acceptedSegments,
                    separationCount
                ));
            }
        }

        active = false;
        activeVehicle = null;
        mode = null;
        state = null;
        direction = null;
        segmentAnchor = null;
        lastSentTarget = null;
        segmentLength = 0.0D;
        segmentSent = 0.0D;
        attemptedDistance = 0.0D;
        acceptedDistance = 0.0D;
        packetsPerTick = 0;
        sentPackets = 0;
        acceptedSegments = 0;
        correctionCount = 0;
        stateTicks = 0;
        reconcileAttempts = 0;
        separationCount = 0;
        autoRemountSent = false;
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
                "pulse-vehicle-v5.1-" + Instant.now().toString().replace(':', '-') + ".csv"
            );
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write(
                "time,event,mode,state,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,attempted,accepted,segment_sent,packets,accepted_pulses,separations,corrections\n"
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
                "%s,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%.3f,%d,%d,%d,%d%n",
                Instant.now(),
                event,
                mode == null ? "NONE" : mode,
                state == null ? "NONE" : state,
                playerPosition.x, playerPosition.y, playerPosition.z,
                vehicle.x, vehicle.y, vehicle.z,
                attemptedDistance,
                acceptedDistance,
                segmentSent,
                sentPackets,
                acceptedSegments,
                separationCount,
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
