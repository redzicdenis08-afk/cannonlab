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
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
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
import java.util.UUID;

/**
 * Client-only adaptive vehicle ratchet for explicitly authorized private clone testing.
 *
 * The state machine is built from the verifier evidence:
 *  - rider separation normally arrives 50-93 ms after the trigger pulse;
 *  - only player-position corrections were observed, not vehicle corrections;
 *  - a normal remount can take roughly 1-5.3 seconds;
 *  - the useful continuation must begin on the first client tick that the remount exists.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final double STEP = 0.25D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;
    private static final double MAX_TOTAL_ATTEMPTED = 256.0D;
    private static final int MAX_CYCLES = 128;
    private static final int WAIT_RESPONSE_TICKS = 4;
    private static final int REMOUNT_TIMEOUT_TICKS = 140;
    private static final double REMOUNT_RANGE_SQUARED = 36.0D;
    private static final double HORSE_BACKWARD_ABORT = -0.75D;
    private static final int[] REMOUNT_ATTEMPT_TICKS = {20, 40, 70, 100, 115, 130};

    private enum VehicleKind { BOAT, HORSE }
    private enum Mode { FORWARD, DOWN }
    private enum State { IDLE, SENDING, WAIT_RESPONSE, REMOUNT_WAIT }
    private enum SegmentKind { INITIAL, REMOUNT_KICK, CRUISE }

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "ratchet_vehicle")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean readyMessageShown;
    private static boolean active;
    private static boolean originalVehicleNoPhysics;
    private static boolean wasMounted;
    private static boolean separationCountedForCurrentLoss;

    private static State state = State.IDLE;
    private static SegmentKind segmentKind = SegmentKind.INITIAL;
    private static VehicleKind vehicleKind;
    private static Mode mode;
    private static Entity activeVehicle;
    private static UUID activeVehicleUuid;
    private static Vec3 direction;
    private static Vec3 runStartVehicle;
    private static Vec3 runStartPlayer;
    private static Vec3 segmentAnchor;

    private static double segmentDistance;
    private static double segmentSent;
    private static double totalAttempted;
    private static double bestObservedProgress;
    private static double lastCorrectionProgress;
    private static int packetsPerTick;
    private static int sentPackets;
    private static int stateTicks;
    private static int cycles;
    private static int correctionsPlayer;
    private static int correctionsVehicle;
    private static int separations;
    private static int remounts;
    private static int remountAttempts;
    private static int negativeHorseCorrections;

    private static BufferedWriter logWriter;
    private static Path logPath;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.ratchet_toggle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.ratchet_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    public static void onServerPlayerCorrectionHead(ClientboundPlayerPositionPacket packet) {
        if (!active) return;
        restoreVehiclePhysics();
        log("PLAYER_CORRECTION_HEAD");
    }

    public static void onServerPlayerCorrectionTail(ClientboundPlayerPositionPacket packet) {
        if (!active) return;
        correctionsPlayer++;
        LocalPlayer player = Minecraft.getInstance().player;
        lastCorrectionProgress = projected(runStartVehicle, activeVehicle == null ? null : activeVehicle.position());
        log("PLAYER_CORRECTION_TAIL");

        if (vehicleKind == VehicleKind.HORSE && mode == Mode.FORWARD
            && lastCorrectionProgress <= HORSE_BACKWARD_ABORT) {
            negativeHorseCorrections++;
            if (negativeHorseCorrections >= 2) {
                stop(player, String.format(Locale.ROOT,
                    "Horse rollback measured at %.2f blocks. Aborting this run.", lastCorrectionProgress), true);
                return;
            }
        }

        if (player == null || activeVehicle == null || activeVehicle.isRemoved()) {
            stop(player, "Server correction removed the active vehicle state.", true);
            return;
        }
        if (controlledVehicle(player) != activeVehicle) {
            beginRemountWait(player, "Server separated rider and vehicle.");
        }
    }

    public static void onServerVehicleCorrectionHead(ClientboundMoveVehiclePacket packet) {
        if (!active) return;
        restoreVehiclePhysics();
        log("VEHICLE_CORRECTION_HEAD");
    }

    public static void onServerVehicleCorrectionTail(ClientboundMoveVehiclePacket packet) {
        if (!active) return;
        correctionsVehicle++;
        LocalPlayer player = Minecraft.getInstance().player;
        lastCorrectionProgress = projected(segmentAnchor, activeVehicle == null ? null : activeVehicle.position());
        log("VEHICLE_CORRECTION_TAIL");
        if (lastCorrectionProgress < STEP * 0.45D && correctionsVehicle >= 2) {
            stop(player, "Vehicle rollback repeated with no retained segment progress.", true);
            return;
        }
        if (player != null && controlledVehicle(player) != activeVehicle) {
            beginRemountWait(player, "Vehicle correction separated the rider.");
        }
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            readyMessageShown = false;
            if (active) stop(null, "Disconnected.", true);
            return;
        }

        if (!readyMessageShown) {
            readyMessageShown = true;
            message(player, "Ratchet 5.3 loaded. Mount boat/horse, face forward or look down, press P. O aborts.");
        }

        while (toggleKey.consumeClick()) {
            if (active) stop(player, "Stopped manually.", false);
            else start(client, player);
        }
        while (abortKey.consumeClick()) {
            if (active) stop(player, "Emergency abort.", true);
        }
        if (!active) return;

        if (activeVehicle == null || activeVehicle.isRemoved()
            || !activeVehicle.getUUID().equals(activeVehicleUuid)) {
            stop(player, "The active vehicle vanished or was replaced.", true);
            return;
        }

        observeMountTransition(client, player);
        if (!active) return;
        bestObservedProgress = Math.max(bestObservedProgress, projected(runStartVehicle, activeVehicle.position()));
        log("TICK");

        switch (state) {
            case SENDING -> tickSending(player);
            case WAIT_RESPONSE -> tickWaitResponse(player);
            case REMOUNT_WAIT -> tickRemountWait(client, player);
            case IDLE -> { }
        }
    }

    private static void start(Minecraft client, LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        VehicleKind kind = classifyVehicle(vehicle);
        if (vehicle == null || kind == null) {
            message(player, "Mount and control a normal boat or tamed horse first.");
            return;
        }

        active = true;
        activeVehicle = vehicle;
        activeVehicleUuid = vehicle.getUUID();
        vehicleKind = kind;
        mode = player.getXRot() >= DOWN_PITCH_THRESHOLD ? Mode.DOWN : Mode.FORWARD;
        direction = mode == Mode.DOWN ? new Vec3(0.0D, -1.0D, 0.0D) : nearestCardinal(player.getLookAngle());
        runStartVehicle = vehicle.position();
        runStartPlayer = player.position();
        bestObservedProgress = 0.0D;
        totalAttempted = 0.0D;
        sentPackets = 0;
        cycles = 0;
        correctionsPlayer = 0;
        correctionsVehicle = 0;
        separations = 0;
        remounts = 0;
        remountAttempts = 0;
        negativeHorseCorrections = 0;
        wasMounted = true;
        separationCountedForCurrentLoss = false;
        originalVehicleNoPhysics = vehicle.noPhysics;
        openLog();
        configureSegment(SegmentKind.INITIAL);

        message(player, String.format(Locale.ROOT,
            "%s %s ratchet started. Trigger %.2f blocks, then timed remount continuation. P stops; O aborts.",
            kind.name(), mode.name(), segmentDistance));
        log("START");
    }

    private static void configureSegment(SegmentKind kind) {
        segmentKind = kind;
        if (kind == SegmentKind.INITIAL) {
            segmentDistance = STEP;
            packetsPerTick = 1;
        } else if (kind == SegmentKind.REMOUNT_KICK) {
            if (vehicleKind == VehicleKind.BOAT && mode == Mode.FORWARD) {
                segmentDistance = 2.0D;
                packetsPerTick = 4;
            } else if (vehicleKind == VehicleKind.BOAT) {
                segmentDistance = 0.50D;
                packetsPerTick = 2;
            } else if (mode == Mode.FORWARD) {
                segmentDistance = 4.0D;
                packetsPerTick = 8;
            } else {
                segmentDistance = STEP;
                packetsPerTick = 1;
            }
        } else {
            if (vehicleKind == VehicleKind.BOAT && mode == Mode.FORWARD) {
                segmentDistance = 0.50D;
                packetsPerTick = 1;
            } else if (vehicleKind == VehicleKind.BOAT) {
                segmentDistance = STEP;
                packetsPerTick = 1;
            } else if (mode == Mode.FORWARD) {
                segmentDistance = 2.0D;
                packetsPerTick = 8;
            } else {
                segmentDistance = STEP;
                packetsPerTick = 1;
            }
        }
        segmentSent = 0.0D;
        stateTicks = 0;
        segmentAnchor = activeVehicle == null ? null : activeVehicle.position();
        state = State.SENDING;
        cycles++;
        log("SEGMENT_CONFIGURED_" + kind.name());
    }

    private static void tickSending(LocalPlayer player) {
        if (controlledVehicle(player) != activeVehicle) {
            beginRemountWait(player, "Mount state changed before the segment completed.");
            return;
        }
        int sentThisTick = 0;
        while (sentThisTick < packetsPerTick && segmentSent + 1.0E-9 < segmentDistance) {
            double step = Math.min(STEP, segmentDistance - segmentSent);
            Vec3 target = activeVehicle.position().add(direction.scale(step));
            activeVehicle.noPhysics = true;
            activeVehicle.setPos(target.x, target.y, target.z);
            player.connection.send(new ServerboundMoveVehiclePacket(
                target, activeVehicle.getYRot(), activeVehicle.getXRot(), activeVehicle.onGround()
            ));
            segmentSent += step;
            totalAttempted += step;
            sentPackets++;
            sentThisTick++;
            log("SEND_STEP");
        }
        if (segmentSent + 1.0E-9 >= segmentDistance) {
            restoreVehiclePhysics();
            state = State.WAIT_RESPONSE;
            stateTicks = 0;
            log("SEGMENT_SENT");
        }
    }

    private static void tickWaitResponse(LocalPlayer player) {
        stateTicks++;
        if (controlledVehicle(player) != activeVehicle) {
            beginRemountWait(player, "Rider separated after the segment.");
            return;
        }
        if (stateTicks < WAIT_RESPONSE_TICKS) return;

        double retained = projected(segmentAnchor, activeVehicle.position());
        bestObservedProgress = Math.max(bestObservedProgress, projected(runStartVehicle, activeVehicle.position()));
        log("SEGMENT_SETTLED");

        if (vehicleKind == VehicleKind.HORSE && mode == Mode.FORWARD && retained <= HORSE_BACKWARD_ABORT) {
            stop(player, String.format(Locale.ROOT,
                "Horse was pushed %.2f blocks opposite the selected direction.", retained), true);
            return;
        }
        if (totalAttempted >= MAX_TOTAL_ATTEMPTED || cycles >= MAX_CYCLES) {
            stop(player, "Safety limit reached.", false);
            return;
        }
        configureSegment(SegmentKind.CRUISE);
    }

    private static void beginRemountWait(LocalPlayer player, String reason) {
        restoreVehiclePhysics();
        if (state != State.REMOUNT_WAIT) {
            if (!separationCountedForCurrentLoss) {
                separations++;
                separationCountedForCurrentLoss = true;
            }
            state = State.REMOUNT_WAIT;
            stateTicks = 0;
            log("REMOUNT_WAIT_BEGIN");
            message(player, reason + " Ratchet is silent while remount timing is tested.");
        }
        wasMounted = false;
    }

    private static void tickRemountWait(Minecraft client, LocalPlayer player) {
        stateTicks++;
        if (controlledVehicle(player) == activeVehicle) return;
        if (activeVehicle.isRemoved()) {
            stop(player, "Vehicle vanished during the remount window.", true);
            return;
        }
        double distanceSquared = player.distanceToSqr(activeVehicle);
        if (distanceSquared > REMOUNT_RANGE_SQUARED) {
            stop(player, String.format(Locale.ROOT,
                "Vehicle moved beyond normal interaction reach: %.2f blocks.", Math.sqrt(distanceSquared)), true);
            return;
        }

        for (int scheduled : REMOUNT_ATTEMPT_TICKS) {
            if (stateTicks == scheduled && client.gameMode != null) {
                remountAttempts++;
                client.gameMode.interact(player, activeVehicle, InteractionHand.MAIN_HAND);
                log("AUTO_REMOUNT_ATTEMPT");
                actionbar(player, String.format(Locale.ROOT,
                    "Remount attempt %d at %.2fs | vehicle %.2fm away",
                    remountAttempts, stateTicks / 20.0D, Math.sqrt(distanceSquared)));
                break;
            }
        }

        if (stateTicks >= REMOUNT_TIMEOUT_TICKS) {
            stop(player, "Server did not accept a remount within seven seconds.", true);
        }
    }

    private static void observeMountTransition(Minecraft client, LocalPlayer player) {
        boolean mountedSame = controlledVehicle(player) == activeVehicle;
        if (wasMounted && !mountedSame) {
            beginRemountWait(player, "Rider separation detected.");
        } else if (!wasMounted && mountedSame) {
            remounts++;
            separationCountedForCurrentLoss = false;
            log("REMOUNT_ACCEPTED");
            message(player, String.format(Locale.ROOT,
                "Remount accepted after %.2fs. Sending immediate %s kick now.",
                stateTicks / 20.0D, vehicleKind.name().toLowerCase(Locale.ROOT)));
            configureSegment(SegmentKind.REMOUNT_KICK);
        }
        wasMounted = mountedSame;
    }

    private static void restoreVehiclePhysics() {
        if (activeVehicle != null && !activeVehicle.isRemoved()) {
            activeVehicle.noPhysics = originalVehicleNoPhysics;
        }
    }

    private static void stop(LocalPlayer player, String reason, boolean rejected) {
        if (!active && logWriter == null) return;
        restoreVehiclePhysics();
        log(rejected ? "STOP_REJECTED" : "STOP");
        if (player != null) {
            double currentProgress = projected(runStartVehicle,
                activeVehicle == null ? null : activeVehicle.position());
            message(player, String.format(Locale.ROOT,
                "%s Travel %.2f, best observed %.2f, attempted %.2f, packets %d, remounts %d, corrections P%d/V%d. %s",
                rejected ? "Stopped:" : "Finished:", currentProgress, bestObservedProgress,
                totalAttempted, sentPackets, remounts, correctionsPlayer, correctionsVehicle, reason));
            if (logPath != null) message(player, "Log: " + logPath);
        }
        closeLog();
        active = false;
        state = State.IDLE;
        activeVehicle = null;
        activeVehicleUuid = null;
        vehicleKind = null;
        mode = null;
        direction = null;
        runStartVehicle = null;
        runStartPlayer = null;
        segmentAnchor = null;
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        if (player == null) return null;
        Entity vehicle = player.getRootVehicle();
        if (vehicle == player || vehicle.getControllingPassenger() != player) return null;
        return vehicle;
    }

    private static VehicleKind classifyVehicle(Entity entity) {
        if (entity == null) return null;
        String type = entity.getType().toString().toLowerCase(Locale.ROOT);
        if (type.contains("boat")) return VehicleKind.BOAT;
        if (type.contains("horse")) return VehicleKind.HORSE;
        return null;
    }

    private static Vec3 nearestCardinal(Vec3 look) {
        if (Math.abs(look.x) >= Math.abs(look.z)) {
            return new Vec3(look.x >= 0.0D ? 1.0D : -1.0D, 0.0D, 0.0D);
        }
        return new Vec3(0.0D, 0.0D, look.z >= 0.0D ? 1.0D : -1.0D);
    }

    private static double projected(Vec3 start, Vec3 position) {
        if (start == null || position == null || direction == null) return 0.0D;
        return position.subtract(start).dot(direction);
    }

    private static void openLog() {
        closeLog();
        try {
            Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Files.createDirectories(directory);
            String stamp = Instant.now().toString().replace(':', '-');
            logPath = directory.resolve("ratchet-vehicle-v5.3-" + stamp + ".csv");
            logWriter = Files.newBufferedWriter(logPath, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            logWriter.write("time,event,state,segment_kind,vehicle_kind,mode,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,segment_sent,total_attempted,best_progress,packets,cycles,separations,remounts,remount_attempts,player_corrections,vehicle_corrections,distance_to_vehicle\n");
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
            logPath = null;
        }
    }

    private static void log(String event) {
        if (logWriter == null) return;
        LocalPlayer player = Minecraft.getInstance().player;
        Vec3 pp = player == null ? Vec3.ZERO : player.position();
        Vec3 vp = activeVehicle == null ? Vec3.ZERO : activeVehicle.position();
        double distance = player == null || activeVehicle == null ? -1.0D : Math.sqrt(player.distanceToSqr(activeVehicle));
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%s,%s,%s,%s,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%.3f,%d,%d,%d,%d,%d,%d,%d,%.3f%n",
                Instant.now(), event, state, segmentKind,
                vehicleKind == null ? "" : vehicleKind,
                mode == null ? "" : mode,
                pp.x, pp.y, pp.z, vp.x, vp.y, vp.z,
                segmentSent, totalAttempted, bestObservedProgress,
                sentPackets, cycles, separations, remounts, remountAttempts,
                correctionsPlayer, correctionsVehicle, distance));
            logWriter.flush();
        } catch (IOException ignored) { }
    }

    private static void closeLog() {
        if (logWriter != null) {
            try { logWriter.close(); } catch (IOException ignored) { }
        }
        logWriter = null;
    }

    private static void message(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab] " + text), false);
    }

    private static void actionbar(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab] " + text), true);
    }
}
