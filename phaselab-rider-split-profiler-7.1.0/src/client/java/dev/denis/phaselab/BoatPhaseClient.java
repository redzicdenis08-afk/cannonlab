package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundSetPassengersPacket;
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
import java.util.List;
import java.util.Locale;
import java.util.Properties;
import java.util.UUID;

/**
 * Player-side bounded vehicle lifecycle proof harness.
 *
 * This client does not randomize packets, hide activity, spoof identities, or
 * disable server enforcement. It replays a small fixed evidence matrix and
 * classifies what the client actually observes after corrections, passenger
 * updates, remounts, a two-second coherence window, and an optional relog.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final String MOD_VERSION = "7.1.0-rider-split-profiler";
    private static final String CONFIG_DIRECTORY = "phaselab-rider-split-profiler";
    private static final String AUTHORIZED_TARGETS_FILE = "authorized-targets.txt";
    private static final int ARMING_TICKS = 10;
    private static final int COHERENCE_TICKS = 60;
    private static final int MISSING_VEHICLE_GRACE_TICKS = 40;
    private static final int MANUAL_REMOUNT_TIMEOUT_TICKS = 120;
    private static final int MAX_RECONCILE_ATTEMPTS = 1;
    private static final double REMOUNT_RANGE_SQUARED = 25.0D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;

    private enum Profile {
        LEGACY_5_1("legacy-5.1", 0.25D, 1.00D, 10, 8, 12, 20),
        MICRO_10("micro-0.10", 0.10D, 0.40D, 10, 8, 12, 20),
        MICRO_15("micro-0.15", 0.15D, 0.60D, 10, 8, 12, 20),
        MICRO_20("micro-0.20", 0.20D, 0.80D, 10, 8, 12, 20);

        final String label;
        final double step;
        final double segmentLength;
        final int settleTicks;
        final int quietTicks;
        final int autoRemountWaitTicks;
        final int stableTicks;

        Profile(String label, double step, double segmentLength, int settleTicks,
                int quietTicks, int autoRemountWaitTicks, int stableTicks) {
            this.label = label;
            this.step = step;
            this.segmentLength = segmentLength;
            this.settleTicks = settleTicks;
            this.quietTicks = quietTicks;
            this.autoRemountWaitTicks = autoRemountWaitTicks;
            this.stableTicks = stableTicks;
        }
    }

    private enum State {
        ARMING,
        SENDING,
        SETTLE,
        QUIET,
        AUTO_REMOUNT_WAIT,
        MANUAL_REMOUNT_WAIT,
        STABLE,
        COHERENCE
    }

    private enum Verdict {
        COHERENT_PROGRESS_CANDIDATE,
        VEHICLE_RETENTION_ONLY,
        ATTACHED_THEN_EJECTED,
        ATTACHED_ZERO_PROGRESS,
        CORRECTION_DOMINANT,
        DETACHED_NO_REATTACH,
        NO_SERVER_TRANSITION
    }

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "proof_harness")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping cycleProfileKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static boolean readyMessageShown;
    private static int selectedProfileIndex;
    private static Profile profile = Profile.LEGACY_5_1;
    private static State state;
    private static int stateTicks;
    private static long runStartNanos;
    private static long clientTick;

    private static Entity activeVehicle;
    private static UUID activeVehicleUuid;
    private static int activeVehicleId = -1;
    private static int vehicleMissingTicks;
    private static String vehicleLabel = "Vehicle";
    private static Vec3 direction;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static Vec3 segmentAnchor;
    private static Vec3 lastSentTarget;
    private static double segmentSent;
    private static double attemptedDistance;

    private static int packetsSent;
    private static int playerCorrections;
    private static int vehicleCorrections;
    private static int passengerDetaches;
    private static int passengerAttaches;
    private static int reconcileAttempts;
    private static long lastCorrectionTick = Long.MIN_VALUE;
    private static long lastDetachTick = Long.MIN_VALUE;
    private static long lastAttachTick = Long.MIN_VALUE;
    private static long firstSendNanos;
    private static long firstPlayerCorrectionNanos;
    private static long firstVehicleCorrectionNanos;
    private static long firstDetachNanos;
    private static long firstAttachNanos;
    private static long postAttachDetachNanos;
    private static int currentPostSendMountedStreakTicks;
    private static int longestPostSendMountedStreakTicks;
    private static final StringBuilder eventOrder = new StringBuilder();
    private static boolean autoRemountSent;

    private static BufferedWriter csvWriter;
    private static Path currentCsvPath;
    private static int pendingRelogTicks;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.proof_toggle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        cycleProfileKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.proof_profile",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_L,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.proof_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    public static void onServerPlayerCorrectionApplied() {
        if (!active) {
            return;
        }
        playerCorrections++;
        lastCorrectionTick = clientTick;
        if (firstPlayerCorrectionNanos == 0L) {
            firstPlayerCorrectionNanos = System.nanoTime();
        }
        appendEvent("PLAYER_CORRECTION");
        Minecraft client = Minecraft.getInstance();
        log("SERVER_PLAYER_CORRECTION", client.player, vehiclePosition());
    }

    public static void onServerVehicleCorrectionApplied() {
        if (!active) {
            return;
        }
        vehicleCorrections++;
        lastCorrectionTick = clientTick;
        if (firstVehicleCorrectionNanos == 0L) {
            firstVehicleCorrectionNanos = System.nanoTime();
        }
        appendEvent("VEHICLE_CORRECTION");
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        recoverActiveVehicle(client, player);
        log("SERVER_VEHICLE_CORRECTION", player, vehiclePosition());
    }

    public static void onServerPassengersApplied(ClientboundSetPassengersPacket packet) {
        if (!active) {
            return;
        }

        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        if (player == null) {
            return;
        }

        int trackedId = activeVehicle == null ? activeVehicleId : activeVehicle.getId();
        if (packet.getVehicle() != trackedId) {
            return;
        }

        boolean containsPlayer = false;
        for (int passengerId : packet.getPassengers()) {
            if (passengerId == player.getId()) {
                containsPlayer = true;
                break;
            }
        }

        if (containsPlayer) {
            passengerAttaches++;
            lastAttachTick = clientTick;
            if (firstAttachNanos == 0L) {
                firstAttachNanos = System.nanoTime();
            }
            appendEvent("PASSENGER_ATTACH");
            recoverActiveVehicle(client, player);
            log("SERVER_PASSENGER_ATTACHED", player, vehiclePosition());
            if (state == State.QUIET || state == State.AUTO_REMOUNT_WAIT || state == State.MANUAL_REMOUNT_WAIT) {
                beginStable(player, "Server passenger attach observed. Verifying stable rider/vehicle coherence...");
            }
            return;
        }

        passengerDetaches++;
        lastDetachTick = clientTick;
        long detachNanos = System.nanoTime();
        if (firstDetachNanos == 0L) {
            firstDetachNanos = detachNanos;
        }
        if (firstAttachNanos > 0L && postAttachDetachNanos == 0L && detachNanos > firstAttachNanos) {
            postAttachDetachNanos = detachNanos;
        }
        appendEvent(firstAttachNanos > 0L ? "POST_ATTACH_DETACH" : "PASSENGER_DETACH");
        log("SERVER_PASSENGER_DETACHED", player, vehiclePosition());
        if (state == State.STABLE && reconcileAttempts >= MAX_RECONCILE_ATTEMPTS) {
            beginCoherence(player, "Server ejected the rider after accepting the remount. Measuring the split without another retry...");
        } else if (state != State.QUIET && state != State.AUTO_REMOUNT_WAIT
            && state != State.MANUAL_REMOUNT_WAIT && state != State.COHERENCE) {
            beginQuiet(player, "Server detached the rider. Entering one fixed quiet/remount measurement cycle...");
        }
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            readyMessageShown = false;
            pendingRelogTicks = 0;
            if (active || csvWriter != null) {
                stop(null, "WORLD_LEFT", false);
            }
            return;
        }

        clientTick++;
        checkPendingRelogWitness(client, player);

        if (!readyMessageShown) {
            readyMessageShown = true;
            profile = Profile.values()[selectedProfileIndex];
            message(player, "Proof Harness " + MOD_VERSION + " loaded. L cycles fixed profiles, P runs one bounded test, O aborts.");
            message(player, "Selected profile: " + profile.label + ". No server plugin is used.");
        }

        while (cycleProfileKey.consumeClick()) {
            if (active) {
                message(player, "Stop the active run before changing profiles.");
            } else {
                selectedProfileIndex = (selectedProfileIndex + 1) % Profile.values().length;
                profile = Profile.values()[selectedProfileIndex];
                message(player, "Selected profile: " + profile.label + " | step " + format(profile.step)
                    + " | one bounded segment " + format(profile.segmentLength));
            }
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                stop(player, "STOPPED_MANUALLY", false);
            } else {
                start(client, player);
            }
        }

        while (abortKey.consumeClick()) {
            if (active) {
                stop(player, "EMERGENCY_ABORT", false);
            }
        }

        if (!active) {
            return;
        }

        if (!isCurrentTargetAuthorized(client)) {
            stop(player, "TARGET_NOT_ALLOWLISTED", true);
            return;
        }

        if (!recoverActiveVehicle(client, player)) {
            vehicleMissingTicks++;
            if (isReconciling() && vehicleMissingTicks <= MISSING_VEHICLE_GRACE_TICKS) {
                actionbar(player, "Waiting for the tracked vehicle entity to return...");
                return;
            }
            beginCoherence(player, "Tracked vehicle disappeared. Running final coherence classification...");
        } else {
            vehicleMissingTicks = 0;
        }

        updatePostSendMountedStreak(player);

        switch (state) {
            case ARMING -> tickArming(player);
            case SENDING -> tickSending(player);
            case SETTLE -> tickSettle(player);
            case QUIET -> tickQuiet(client, player);
            case AUTO_REMOUNT_WAIT -> tickAutoRemountWait(player);
            case MANUAL_REMOUNT_WAIT -> tickManualRemountWait(player);
            case STABLE -> tickStable(player);
            case COHERENCE -> tickCoherence(player);
        }
    }

    private static void start(Minecraft client, LocalPlayer player) {
        profile = Profile.values()[selectedProfileIndex];
        if (!isCurrentTargetAuthorized(client)) {
            String current = currentServerAddress(client);
            message(player, "Current server is not allowlisted: " + (current.isBlank() ? "<unknown>" : current));
            message(player, "Add that exact address to config/" + CONFIG_DIRECTORY + "/" + AUTHORIZED_TARGETS_FILE + ".");
            return;
        }

        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            message(player, "Mount and control a boat, raft, or saddled horse first, then press P.");
            return;
        }
        if (!isSupportedVehicle(vehicle)) {
            message(player, "This proof harness supports boats, rafts, and horses only.");
            return;
        }

        active = true;
        state = State.ARMING;
        stateTicks = ARMING_TICKS;
        runStartNanos = System.nanoTime();
        activeVehicle = vehicle;
        activeVehicleUuid = vehicle.getUUID();
        activeVehicleId = vehicle.getId();
        vehicleLabel = vehicleTypeLabel(vehicle);
        direction = player.getXRot() >= DOWN_PITCH_THRESHOLD
            ? new Vec3(0.0D, -1.0D, 0.0D)
            : nearestCardinal(player.getYRot());
        playerStart = player.position();
        vehicleStart = vehicle.position();
        segmentAnchor = vehicleStart;
        lastSentTarget = vehicleStart;
        segmentSent = 0.0D;
        attemptedDistance = 0.0D;
        packetsSent = 0;
        playerCorrections = 0;
        vehicleCorrections = 0;
        passengerDetaches = 0;
        passengerAttaches = 0;
        reconcileAttempts = 0;
        vehicleMissingTicks = 0;
        lastCorrectionTick = Long.MIN_VALUE;
        lastDetachTick = Long.MIN_VALUE;
        lastAttachTick = Long.MIN_VALUE;
        firstSendNanos = 0L;
        firstPlayerCorrectionNanos = 0L;
        firstVehicleCorrectionNanos = 0L;
        firstDetachNanos = 0L;
        firstAttachNanos = 0L;
        postAttachDetachNanos = 0L;
        currentPostSendMountedStreakTicks = 0;
        longestPostSendMountedStreakTicks = 0;
        eventOrder.setLength(0);
        appendEvent("START");
        autoRemountSent = false;
        openLog(client);
        log("START", player, vehicle.position());
        message(player, vehicleLabel + " profile " + profile.label + " armed for 10 stable ticks. Do not move manually.");
    }

    private static void tickArming(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            stop(player, "MOUNT_NOT_STABLE_DURING_ARMING", true);
            return;
        }
        stateTicks--;
        actionbar(player, "Arming stable mount " + (ARMING_TICKS - Math.max(stateTicks, 0)) + "/" + ARMING_TICKS);
        if (stateTicks <= 0) {
            state = State.SENDING;
            log("ARMING_COMPLETE", player, vehiclePosition());
        }
    }

    private static void tickSending(LocalPlayer player) {
        if (activeVehicle == null) {
            beginCoherence(player, "Vehicle missing during send.");
            return;
        }
        if (controlledVehicle(player) != activeVehicle) {
            beginQuiet(player, "Mount changed before the bounded segment completed.");
            return;
        }

        double remaining = profile.segmentLength - segmentSent;
        double delta = Math.min(profile.step, remaining);
        if (delta <= 1.0E-9D) {
            state = State.SETTLE;
            stateTicks = profile.settleTicks;
            return;
        }

        Vec3 target = segmentAnchor.add(direction.scale(segmentSent + delta));
        if (firstSendNanos == 0L) {
            firstSendNanos = System.nanoTime();
            appendEvent("FIRST_SEND");
        }
        player.connection.send(new ServerboundMoveVehiclePacket(
            target,
            activeVehicle.getYRot(),
            activeVehicle.getXRot(),
            activeVehicle.onGround()
        ));
        lastSentTarget = target;
        segmentSent += delta;
        attemptedDistance += delta;
        packetsSent++;
        log("SEND_PACKET_ONLY_STEP", player, target);
        actionbar(player, profile.label + " sent " + format(segmentSent) + "/" + format(profile.segmentLength)
            + " | packet " + packetsSent);

        if (segmentSent >= profile.segmentLength - 1.0E-9D) {
            state = State.SETTLE;
            stateTicks = profile.settleTicks;
            log("SEGMENT_SENT", player, target);
        }
    }

    private static void tickSettle(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            beginQuiet(player, "Rider/vehicle separated during settle.");
            return;
        }
        stateTicks--;
        actionbar(player, "Silent settle " + (profile.settleTicks - Math.max(stateTicks, 0)) + "/" + profile.settleTicks);
        if (stateTicks <= 0) {
            beginCoherence(player, "Segment remained mounted through settle. Starting two-second coherence proof...");
        }
    }

    private static void beginQuiet(LocalPlayer player, String reason) {
        if (state == State.QUIET || state == State.AUTO_REMOUNT_WAIT || state == State.MANUAL_REMOUNT_WAIT) {
            return;
        }
        if (reconcileAttempts >= MAX_RECONCILE_ATTEMPTS) {
            beginCoherence(player, "One remount measurement already completed. Holding state for final classification...");
            return;
        }
        reconcileAttempts++;
        appendEvent("QUIET_BEGIN");
        state = State.QUIET;
        stateTicks = profile.quietTicks;
        autoRemountSent = false;
        log("QUIET_BEGIN", player, vehiclePosition());
        message(player, reason);
    }

    private static void tickQuiet(Minecraft client, LocalPlayer player) {
        if (controlledVehicle(player) == activeVehicle) {
            beginStable(player, "Mount returned during quiet window.");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            beginCoherence(player, "Vehicle left normal remount reach.");
            return;
        }
        stateTicks--;
        actionbar(player, "Quiet window " + (profile.quietTicks - Math.max(stateTicks, 0)) + "/" + profile.quietTicks);
        if (stateTicks > 0) {
            return;
        }

        if (!autoRemountSent && client.gameMode != null && activeVehicle != null) {
            autoRemountSent = true;
            client.gameMode.interact(player, activeVehicle, InteractionHand.MAIN_HAND);
            log("AUTO_REMOUNT_SINGLE_INTERACT", player, vehiclePosition());
        }
        state = State.AUTO_REMOUNT_WAIT;
        stateTicks = profile.autoRemountWaitTicks;
    }

    private static void tickAutoRemountWait(LocalPlayer player) {
        if (controlledVehicle(player) == activeVehicle) {
            beginStable(player, "Normal remount accepted locally. Waiting for stable passenger proof...");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            beginCoherence(player, "Vehicle left reach before remount result.");
            return;
        }
        stateTicks--;
        actionbar(player, "Waiting for remount result...");
        if (stateTicks <= 0) {
            state = State.MANUAL_REMOUNT_WAIT;
            stateTicks = MANUAL_REMOUNT_TIMEOUT_TICKS;
            message(player, "Right-click the SAME vehicle once. Do not press P again.");
            log("MANUAL_REMOUNT_REQUESTED", player, vehiclePosition());
        }
    }

    private static void tickManualRemountWait(LocalPlayer player) {
        if (controlledVehicle(player) == activeVehicle) {
            beginStable(player, "Manual remount detected. Waiting for stable passenger proof...");
            return;
        }
        if (!vehicleWithinRemountReach(player)) {
            beginCoherence(player, "Vehicle left reach during manual remount window.");
            return;
        }
        stateTicks--;
        actionbar(player, "Right-click same " + vehicleLabel.toLowerCase(Locale.ROOT) + " once | "
            + format(Math.max(stateTicks, 0) / 20.0D) + "s");
        if (stateTicks <= 0) {
            beginCoherence(player, "Manual remount timeout.");
        }
    }

    private static void beginStable(LocalPlayer player, String reason) {
        state = State.STABLE;
        stateTicks = profile.stableTicks;
        appendEvent("STABLE_BEGIN");
        log("STABLE_BEGIN", player, vehiclePosition());
        message(player, reason);
    }

    private static void tickStable(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            if (reconcileAttempts < MAX_RECONCILE_ATTEMPTS) {
                beginQuiet(player, "Mount separated during stable check. One final fixed reconciliation cycle...");
            } else {
                beginCoherence(player, "Mount remained unstable after fixed reconciliation attempts.");
            }
            return;
        }
        stateTicks--;
        actionbar(player, "Stable mount proof " + (profile.stableTicks - Math.max(stateTicks, 0)) + "/" + profile.stableTicks);
        if (stateTicks <= 0) {
            beginCoherence(player, "Stable remount window completed. Starting two-second coherence proof...");
        }
    }

    private static void beginCoherence(LocalPlayer player, String reason) {
        if (state == State.COHERENCE) {
            return;
        }
        state = State.COHERENCE;
        stateTicks = COHERENCE_TICKS;
        appendEvent("COHERENCE_BEGIN");
        log("COHERENCE_BEGIN", player, vehiclePosition());
        message(player, reason);
    }

    private static void tickCoherence(LocalPlayer player) {
        stateTicks--;
        double playerProgress = projectedProgress(playerStart, player.position(), direction);
        double vehicleProgress = projectedProgress(vehicleStart, vehiclePosition(), direction);
        boolean mounted = controlledVehicle(player) == activeVehicle;
        actionbar(player, "Coherence " + (COHERENCE_TICKS - Math.max(stateTicks, 0)) + "/" + COHERENCE_TICKS
            + " | player " + format(playerProgress) + " | vehicle " + format(vehicleProgress)
            + " | mounted " + mounted);
        log("COHERENCE_TICK", player, vehiclePosition());
        if (stateTicks <= 0) {
            finishRun(player);
        }
    }

    private static void finishRun(LocalPlayer player) {
        Verdict verdict = classify(player);
        double playerProgress = projectedProgress(playerStart, player.position(), direction);
        double vehicleProgress = projectedProgress(vehicleStart, vehiclePosition(), direction);
        boolean mounted = controlledVehicle(player) == activeVehicle;
        log("VERDICT_" + verdict, player, vehiclePosition());
        writeSummaryJson(player, verdict, playerProgress, vehicleProgress, mounted);
        if (verdict == Verdict.COHERENT_PROGRESS_CANDIDATE) {
            savePendingRelogWitness(player);
        }
        message(player, "Verdict: " + verdict + " | player " + format(playerProgress)
            + " | vehicle " + format(vehicleProgress) + " | mounted " + mounted
            + " | corrections " + (playerCorrections + vehicleCorrections)
            + " | detach/attach " + passengerDetaches + "/" + passengerAttaches
            + " | attach->eject " + format(millisBetween(firstAttachNanos, postAttachDetachNanos)) + "ms.");
        stop(player, "RUN_COMPLETE", false);
    }

    private static Verdict classify(LocalPlayer player) {
        Vec3 vehicle = vehiclePosition();
        double playerProgress = projectedProgress(playerStart, player.position(), direction);
        double vehicleProgress = projectedProgress(vehicleStart, vehicle, direction);
        boolean mounted = controlledVehicle(player) == activeVehicle;
        boolean correctedRecently = lastCorrectionTick != Long.MIN_VALUE && clientTick - lastCorrectionTick <= COHERENCE_TICKS + 20L;
        double threshold = Math.max(0.12D, attemptedDistance * 0.55D);

        if (mounted && playerProgress >= threshold && vehicleProgress >= threshold
            && !correctedRecently && passengerDetaches <= passengerAttaches) {
            return Verdict.COHERENT_PROGRESS_CANDIDATE;
        }
        if (vehicleProgress >= threshold && playerProgress < threshold) {
            return Verdict.VEHICLE_RETENTION_ONLY;
        }
        if (firstAttachNanos > 0L && postAttachDetachNanos > firstAttachNanos) {
            return Verdict.ATTACHED_THEN_EJECTED;
        }
        if (passengerAttaches > 0 && playerProgress < threshold && vehicleProgress < threshold) {
            return Verdict.ATTACHED_ZERO_PROGRESS;
        }
        if (playerCorrections + vehicleCorrections > 0) {
            return Verdict.CORRECTION_DOMINANT;
        }
        if (passengerDetaches > 0 && passengerAttaches == 0) {
            return Verdict.DETACHED_NO_REATTACH;
        }
        return Verdict.NO_SERVER_TRANSITION;
    }

    private static void updatePostSendMountedStreak(LocalPlayer player) {
        if (firstSendNanos == 0L) {
            return;
        }
        if (controlledVehicle(player) == activeVehicle) {
            currentPostSendMountedStreakTicks++;
            longestPostSendMountedStreakTicks = Math.max(
                longestPostSendMountedStreakTicks,
                currentPostSendMountedStreakTicks
            );
        } else {
            currentPostSendMountedStreakTicks = 0;
        }
    }

    private static void appendEvent(String event) {
        if (eventOrder.length() > 0) {
            eventOrder.append(" > ");
        }
        eventOrder.append(event);
    }

    private static double millisBetween(long start, long end) {
        if (start <= 0L || end <= 0L || end < start) {
            return -1.0D;
        }
        return (end - start) / 1_000_000.0D;
    }

    private static boolean isReconciling() {
        return state == State.QUIET || state == State.AUTO_REMOUNT_WAIT
            || state == State.MANUAL_REMOUNT_WAIT || state == State.STABLE;
    }

    private static boolean vehicleWithinRemountReach(LocalPlayer player) {
        return player != null && activeVehicle != null && !activeVehicle.isRemoved()
            && player.distanceToSqr(activeVehicle) <= REMOUNT_RANGE_SQUARED;
    }

    private static boolean recoverActiveVehicle(Minecraft client, LocalPlayer player) {
        if (player == null) {
            return false;
        }
        Entity controlled = controlledVehicle(player);
        if (sameTrackedVehicle(controlled)) {
            rebindActiveVehicle(controlled);
            return true;
        }
        if (client != null && client.level != null) {
            Entity byId = activeVehicleId < 0 ? null : client.level.getEntity(activeVehicleId);
            if (sameTrackedVehicle(byId)) {
                rebindActiveVehicle(byId);
                return true;
            }
            if (activeVehicleUuid != null) {
                List<Entity> nearby = client.level.getEntities(
                    player,
                    player.getBoundingBox().inflate(Math.sqrt(REMOUNT_RANGE_SQUARED) + 1.0D),
                    candidate -> activeVehicleUuid.equals(candidate.getUUID())
                );
                if (!nearby.isEmpty()) {
                    rebindActiveVehicle(nearby.getFirst());
                    return true;
                }
            }
        }
        return activeVehicle != null && !activeVehicle.isRemoved();
    }

    private static boolean sameTrackedVehicle(Entity candidate) {
        return candidate != null && !candidate.isRemoved() && activeVehicleUuid != null
            && activeVehicleUuid.equals(candidate.getUUID());
    }

    private static void rebindActiveVehicle(Entity replacement) {
        if (replacement == null) {
            return;
        }
        boolean changed = activeVehicle != replacement;
        activeVehicle = replacement;
        activeVehicleId = replacement.getId();
        if (changed) {
            LocalPlayer player = Minecraft.getInstance().player;
            log("VEHICLE_REFERENCE_REBOUND", player, replacement.position());
        }
    }

    private static boolean isCurrentTargetAuthorized(Minecraft client) {
        String address = currentServerAddress(client);
        return ClientOnlyTargetGuard.isAuthorized(client.gameDirectory.toPath(), address);
    }

    private static String currentServerAddress(Minecraft client) {
        if (client == null) {
            return "";
        }
        ServerData server = client.getCurrentServer();
        return server == null || server.ip == null ? "" : server.ip.trim();
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
        if (start == null || current == null || vector == null || vector.lengthSqr() < 1.0E-12D) {
            return 0.0D;
        }
        return current.subtract(start).dot(vector.normalize());
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        if (player == null) {
            return null;
        }
        Entity vehicle = player.getRootVehicle();
        if (vehicle == player || vehicle.getControllingPassenger() != player) {
            return null;
        }
        return vehicle;
    }

    private static boolean isSupportedVehicle(Entity vehicle) {
        String type = vehicle.getType().toString().toLowerCase(Locale.ROOT);
        return type.contains("boat") || type.contains("raft") || type.contains("horse");
    }

    private static String vehicleTypeLabel(Entity vehicle) {
        String type = vehicle.getType().toString().toLowerCase(Locale.ROOT);
        if (type.contains("horse")) {
            return "Horse";
        }
        if (type.contains("raft")) {
            return "Raft";
        }
        return "Boat";
    }

    private static Vec3 vehiclePosition() {
        return activeVehicle == null ? null : activeVehicle.position();
    }

    private static void openLog(Minecraft client) {
        closeLog();
        try {
            Path directory = client.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY).resolve("logs");
            Files.createDirectories(directory);
            String stamp = Instant.now().toString().replace(':', '-');
            currentCsvPath = directory.resolve("proof-" + stamp + "-" + profile.label + ".csv");
            csvWriter = Files.newBufferedWriter(
                currentCsvPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            csvWriter.write("time,nano_ms,tick,event,profile,state,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,attempted,segment_sent,packets,player_corrections,vehicle_corrections,detaches,attaches,reconcile_attempts,mounted\n");
            csvWriter.flush();
        } catch (IOException ignored) {
            csvWriter = null;
            currentCsvPath = null;
        }
    }

    private static void log(String event, LocalPlayer player, Vec3 vehiclePosition) {
        if (csvWriter == null) {
            return;
        }
        Vec3 p = player == null ? Vec3.ZERO : player.position();
        Vec3 v = vehiclePosition == null ? Vec3.ZERO : vehiclePosition;
        boolean mounted = player != null && controlledVehicle(player) == activeVehicle;
        double nanoMs = (System.nanoTime() - runStartNanos) / 1_000_000.0D;
        try {
            csvWriter.write(String.format(Locale.ROOT,
                "%s,%.3f,%d,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%d,%d,%d,%d,%d,%d,%s%n",
                Instant.now(), nanoMs, clientTick, event, profile.label,
                state == null ? "NONE" : state,
                p.x, p.y, p.z, v.x, v.y, v.z,
                attemptedDistance, segmentSent, packetsSent,
                playerCorrections, vehicleCorrections, passengerDetaches, passengerAttaches,
                reconcileAttempts, mounted));
            csvWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private static void writeSummaryJson(LocalPlayer player, Verdict verdict,
                                         double playerProgress, double vehicleProgress, boolean mounted) {
        try {
            Minecraft client = Minecraft.getInstance();
            Path directory = client.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY).resolve("logs");
            Files.createDirectories(directory);
            String baseName = currentCsvPath == null
                ? "proof-" + Instant.now().toString().replace(':', '-')
                : currentCsvPath.getFileName().toString().replace(".csv", "");
            Path summary = directory.resolve(baseName + "-summary.json");
            String json = "{\n"
                + "  \"version\": \"" + MOD_VERSION + "\",\n"
                + "  \"server\": \"" + escapeJson(currentServerAddress(client)) + "\",\n"
                + "  \"profile\": \"" + profile.label + "\",\n"
                + "  \"verdict\": \"" + verdict + "\",\n"
                + "  \"attemptedDistance\": " + format(attemptedDistance) + ",\n"
                + "  \"playerProgress\": " + format(playerProgress) + ",\n"
                + "  \"vehicleProgress\": " + format(vehicleProgress) + ",\n"
                + "  \"mountedAfterCoherence\": " + mounted + ",\n"
                + "  \"packetsSent\": " + packetsSent + ",\n"
                + "  \"playerCorrections\": " + playerCorrections + ",\n"
                + "  \"vehicleCorrections\": " + vehicleCorrections + ",\n"
                + "  \"passengerDetaches\": " + passengerDetaches + ",\n"
                + "  \"passengerAttaches\": " + passengerAttaches + ",\n"
                + "  \"lastDetachTick\": " + lastDetachTick + ",\n"
                + "  \"lastAttachTick\": " + lastAttachTick + ",\n"
                + "  \"sendToPlayerCorrectionMs\": " + format(millisBetween(firstSendNanos, firstPlayerCorrectionNanos)) + ",\n"
                + "  \"sendToVehicleCorrectionMs\": " + format(millisBetween(firstSendNanos, firstVehicleCorrectionNanos)) + ",\n"
                + "  \"sendToFirstDetachMs\": " + format(millisBetween(firstSendNanos, firstDetachNanos)) + ",\n"
                + "  \"detachToFirstAttachMs\": " + format(millisBetween(firstDetachNanos, firstAttachNanos)) + ",\n"
                + "  \"attachToNextDetachMs\": " + format(millisBetween(firstAttachNanos, postAttachDetachNanos)) + ",\n"
                + "  \"longestPostSendMountedStreakTicks\": " + longestPostSendMountedStreakTicks + ",\n"
                + "  \"eventOrder\": \"" + escapeJson(eventOrder.toString()) + "\",\n"
                + "  \"csv\": \"" + escapeJson(currentCsvPath == null ? "" : currentCsvPath.toString()) + "\"\n"
                + "}\n";
            Files.writeString(summary, json, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        } catch (IOException ignored) {
        }
    }

    private static void savePendingRelogWitness(LocalPlayer player) {
        if (player == null) {
            return;
        }
        try {
            Minecraft client = Minecraft.getInstance();
            Path directory = client.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY);
            Files.createDirectories(directory);
            Properties properties = new Properties();
            properties.setProperty("server", currentServerAddress(client));
            properties.setProperty("x", Double.toString(player.getX()));
            properties.setProperty("y", Double.toString(player.getY()));
            properties.setProperty("z", Double.toString(player.getZ()));
            properties.setProperty("created", Instant.now().toString());
            properties.setProperty("profile", profile.label);
            try (BufferedWriter writer = Files.newBufferedWriter(directory.resolve("pending-relog-witness.properties"),
                StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE)) {
                properties.store(writer, "PhaseLab proof harness pending relog witness");
            }
            message(player, "Candidate saved. Relog once; the harness will compare your server position after 3 seconds.");
        } catch (IOException ignored) {
        }
    }

    private static void checkPendingRelogWitness(Minecraft client, LocalPlayer player) {
        if (active || player == null) {
            return;
        }
        Path file = client.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY)
            .resolve("pending-relog-witness.properties");
        if (Files.notExists(file)) {
            pendingRelogTicks = 0;
            return;
        }
        pendingRelogTicks++;
        if (pendingRelogTicks < 60) {
            return;
        }
        pendingRelogTicks = 0;

        try {
            Properties properties = new Properties();
            try (var reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
                properties.load(reader);
            }
            String expectedServer = properties.getProperty("server", "");
            if (!ClientOnlyTargetGuard.normalizeForComparison(expectedServer)
                .equals(ClientOnlyTargetGuard.normalizeForComparison(currentServerAddress(client)))) {
                return;
            }
            Vec3 expected = new Vec3(
                Double.parseDouble(properties.getProperty("x")),
                Double.parseDouble(properties.getProperty("y")),
                Double.parseDouble(properties.getProperty("z"))
            );
            double distance = player.position().distanceTo(expected);
            String verdict = distance <= 2.0D ? "RELOG_PERSISTED_CANDIDATE" : "RELOG_FAILED";
            Path log = file.getParent().resolve("relog-witness.log");
            Files.writeString(log,
                Instant.now() + "," + verdict + ",distance=" + format(distance)
                    + ",profile=" + properties.getProperty("profile", "unknown") + "\n",
                StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND, StandardOpenOption.WRITE);
            message(player, "Relog witness: " + verdict + " | distance from saved server position " + format(distance) + ".");
            Files.deleteIfExists(file);
        } catch (Exception exception) {
            try {
                Files.deleteIfExists(file);
            } catch (IOException ignored) {
            }
        }
    }

    private static void stop(LocalPlayer player, String reason, boolean rejected) {
        if (!active && csvWriter == null) {
            return;
        }
        if (player != null) {
            log(rejected ? "STOP_REJECTED_" + reason : "STOP_" + reason, player, vehiclePosition());
        }
        active = false;
        state = null;
        stateTicks = 0;
        activeVehicle = null;
        activeVehicleUuid = null;
        activeVehicleId = -1;
        vehicleMissingTicks = 0;
        direction = null;
        playerStart = null;
        vehicleStart = null;
        segmentAnchor = null;
        lastSentTarget = null;
        segmentSent = 0.0D;
        attemptedDistance = 0.0D;
        packetsSent = 0;
        reconcileAttempts = 0;
        autoRemountSent = false;
        closeLog();
    }

    private static void closeLog() {
        if (csvWriter != null) {
            try {
                csvWriter.close();
            } catch (IOException ignored) {
            }
        }
        csvWriter = null;
        currentCsvPath = null;
    }

    private static String format(double value) {
        return String.format(Locale.ROOT, "%.3f", value);
    }

    private static String escapeJson(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
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
