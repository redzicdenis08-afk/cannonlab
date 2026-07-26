package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ServerboundMovePlayerPacket;
import net.minecraft.world.phys.AABB;
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

/**
 * Client-only movement acceptance probe for an authorized Sakura test server.
 *
 * It does not cancel setbacks or hide packets. It deliberately records whether
 * a normal server correction packet is received after a candidate move.
 */
public final class PhaseLabClient implements ClientModInitializer {
    private static final double PROFILE_STEP = 0.025D;
    private static final double MAX_SCAN_DISTANCE = 2.20D;
    private static final int MAX_CANDIDATES = 18;
    private static final int REQUIRED_PASSES = 2;
    private static final int PREPARE_TICKS = 4;
    private static final int VERIFY_TICKS = 20;
    private static final int RESTORE_TICKS = 5;
    private static final int APPLY_VERIFY_TICKS = 60;
    private static final double ACCEPT_ERROR = 0.15D;
    private static final double CORRECTION_ERROR = 0.40D;

    private enum State {
        IDLE,
        PREPARING,
        VERIFYING,
        RESTORING,
        APPLYING_BEST
    }

    private enum ScanDirection {
        FORWARD,
        DOWN,
        UP;

        private ScanDirection next() {
            ScanDirection[] values = values();
            return values[(ordinal() + 1) % values.length];
        }
    }

    private static State state = State.IDLE;
    private static ScanDirection selectedDirection = ScanDirection.FORWARD;

    private static Vec3 scanOrigin;
    private static Vec3 target;
    private static Vec3 restorePoint;
    private static Vec3 scanVector;
    private static Vec3 bestOffset;
    private static List<Double> candidateDistances = List.of();

    private static double currentDistance;
    private static double bestAcceptedDistance = -1.0D;
    private static int candidateIndex;
    private static int trialNumber = 1;
    private static int stateTicks;
    private static int correctionPackets;
    private static int explicitOutboundPackets;
    private static boolean correctionObserved;
    private static boolean repeatCandidateAfterRestore;
    private static boolean packetHookSeen;
    private static boolean originalNoPhysics;
    private static boolean manualRestoreAvailable;

    private static boolean f6WasDown;
    private static boolean f7WasDown;
    private static boolean f8WasDown;
    private static boolean f9WasDown;
    private static boolean f10WasDown;

    private static BufferedWriter logWriter;
    private static Path logPath;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabClient::onClientTick);
    }

    /** Called by the client packet-listener mixin when the server sends a position packet. */
    public static void onServerPositionCorrection() {
        packetHookSeen = true;
        if (state == State.VERIFYING || state == State.APPLYING_BEST) {
            correctionObserved = true;
            correctionPackets++;
        }
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            closeLogQuietly();
            state = State.IDLE;
            return;
        }

        var window = client.getWindow();
        boolean f6Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F6);
        boolean f7Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F7);
        boolean f8Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F8);
        boolean f9Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F9);
        boolean f10Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F10);

        if (f6Down && !f6WasDown) {
            message(player,
                "Hook=" + (packetHookSeen ? "seen" : "not-seen-yet")
                    + " | direction=" + selectedDirection
                    + " | state=" + state,
                false
            );
        }

        if (f7Down && !f7WasDown) {
            if (state == State.IDLE) {
                selectedDirection = selectedDirection.next();
                message(player, "Direction: " + selectedDirection, false);
            } else {
                message(player, "Finish or abort the scan before changing direction.", false);
            }
        }

        if (f8Down && !f8WasDown) {
            if (state == State.IDLE) {
                startScan(player);
            } else {
                message(player, "PhaseLab is already running. F10 aborts.", false);
            }
        }

        if (f9Down && !f9WasDown) {
            if (state == State.IDLE) {
                applyBest(player);
            } else {
                message(player, "Finish or abort the current scan first.", false);
            }
        }

        if (f10Down && !f10WasDown) {
            if (state != State.IDLE || manualRestoreAvailable) {
                restore(player, "Restored test position.");
            }
        }

        f6WasDown = f6Down;
        f7WasDown = f7Down;
        f8WasDown = f8Down;
        f9WasDown = f9Down;
        f10WasDown = f10Down;

        switch (state) {
            case PREPARING -> tickPreparing(player);
            case VERIFYING -> tickVerifying(player);
            case RESTORING -> tickRestoring(player);
            case APPLYING_BEST -> tickApplyingBest(player);
            case IDLE -> {
            }
        }
    }

    private static void startScan(LocalPlayer player) {
        scanOrigin = player.position();
        restorePoint = scanOrigin;
        originalNoPhysics = player.noPhysics;
        manualRestoreAvailable = false;
        bestAcceptedDistance = -1.0D;
        bestOffset = null;
        candidateIndex = 0;
        trialNumber = 1;
        repeatCandidateAfterRestore = false;
        scanVector = calculateDirection(player, selectedDirection);
        candidateDistances = discoverCandidates(player, scanVector);

        if (candidateDistances.isEmpty()) {
            message(player, "No solid layer with a clear player-sized gap behind it was found within 2.20 blocks.", false);
            return;
        }

        openLog();
        beginAttempt(player);
        message(player,
            "Wall-aware " + selectedDirection + " scan started with " + candidateDistances.size()
                + " candidates. Each must pass twice. F10 aborts.",
            false
        );
    }

    private static Vec3 calculateDirection(LocalPlayer player, ScanDirection direction) {
        return switch (direction) {
            case DOWN -> new Vec3(0.0D, -1.0D, 0.0D);
            case UP -> new Vec3(0.0D, 1.0D, 0.0D);
            case FORWARD -> {
                double radians = Math.toRadians(player.getYRot());
                double x = -Math.sin(radians);
                double z = Math.cos(radians);
                double length = Math.sqrt(x * x + z * z);
                yield length == 0.0D ? new Vec3(0.0D, 0.0D, 1.0D) : new Vec3(x / length, 0.0D, z / length);
            }
        };
    }

    /**
     * Finds only useful destinations: the player-sized box must cross a collision
     * and then become clear again. This avoids reporting ordinary movement in open air.
     */
    private static List<Double> discoverCandidates(LocalPlayer player, Vec3 direction) {
        List<Double> candidates = new ArrayList<>();
        AABB originBox = player.getBoundingBox();
        boolean crossedCollision = false;
        boolean enteredExitGap = false;

        for (double distance = PROFILE_STEP; distance <= MAX_SCAN_DISTANCE + 0.0001D; distance += PROFILE_STEP) {
            AABB sampledBox = originBox.move(
                direction.x * distance,
                direction.y * distance,
                direction.z * distance
            ).deflate(0.001D);

            boolean clear = player.level().noCollision(player, sampledBox);
            if (!clear) {
                if (enteredExitGap) {
                    break;
                }
                crossedCollision = true;
                continue;
            }

            if (crossedCollision) {
                enteredExitGap = true;
                candidates.add(roundDistance(distance));
                if (candidates.size() >= MAX_CANDIDATES) {
                    break;
                }
            }
        }

        return List.copyOf(candidates);
    }

    private static double roundDistance(double distance) {
        return Math.round(distance * 1000.0D) / 1000.0D;
    }

    private static void beginAttempt(LocalPlayer player) {
        currentDistance = candidateDistances.get(candidateIndex);
        target = scanOrigin.add(scanVector.scale(currentDistance));
        correctionObserved = false;
        correctionPackets = 0;
        explicitOutboundPackets = 0;
        moveLocalAndSend(player, scanOrigin);
        stateTicks = 0;
        state = State.PREPARING;
        message(player, String.format(Locale.ROOT,
            "Testing %.3f blocks, pass %d/%d...",
            currentDistance,
            trialNumber,
            REQUIRED_PASSES
        ), true);
    }

    private static void tickPreparing(LocalPlayer player) {
        freeze(player);
        stateTicks++;
        if (stateTicks < PREPARE_TICKS) {
            return;
        }

        correctionObserved = false;
        correctionPackets = 0;
        moveLocalAndSend(player, target);
        stateTicks = 0;
        state = State.VERIFYING;
    }

    private static void tickVerifying(LocalPlayer player) {
        freeze(player);
        stateTicks++;

        double error = player.position().distanceTo(target);
        if (correctionObserved) {
            finishAttempt(player, "REJECTED_SERVER_SETBACK", error);
            return;
        }
        if (error > CORRECTION_ERROR) {
            finishAttempt(player, "REJECTED_POSITION_DRIFT", error);
            return;
        }

        // One explicit confirmation packet makes the result less dependent on
        // the vanilla client's packet batching without flooding the server.
        if (stateTicks == 10) {
            sendPosition(player, target);
        }

        if (stateTicks >= VERIFY_TICKS) {
            String result = error <= ACCEPT_ERROR ? "NO_SETBACK_OBSERVED" : "INCONCLUSIVE_DRIFT";
            finishAttempt(player, result, error);
        }
    }

    private static void finishAttempt(LocalPlayer player, String result, double error) {
        writeLog(result, player.position(), error);

        boolean passed = "NO_SETBACK_OBSERVED".equals(result);
        if (passed && trialNumber < REQUIRED_PASSES) {
            repeatCandidateAfterRestore = true;
            trialNumber++;
        } else {
            if (passed && trialNumber >= REQUIRED_PASSES && currentDistance > bestAcceptedDistance) {
                bestAcceptedDistance = currentDistance;
                bestOffset = scanVector.scale(currentDistance);
            }
            repeatCandidateAfterRestore = false;
            trialNumber = 1;
        }

        correctionObserved = false;
        moveLocalAndSend(player, scanOrigin);
        stateTicks = 0;
        state = State.RESTORING;
    }

    private static void tickRestoring(LocalPlayer player) {
        freeze(player);
        stateTicks++;
        if (stateTicks < RESTORE_TICKS) {
            return;
        }

        if (repeatCandidateAfterRestore) {
            repeatCandidateAfterRestore = false;
            beginAttempt(player);
            return;
        }

        candidateIndex++;
        if (candidateIndex < candidateDistances.size()) {
            beginAttempt(player);
            return;
        }

        player.noPhysics = originalNoPhysics;
        player.setDeltaMovement(Vec3.ZERO);
        state = State.IDLE;
        closeLogQuietly();

        if (bestOffset != null) {
            message(player, String.format(Locale.ROOT,
                "Scan done. Largest two-pass candidate: %.3f. Press F9 to retry it.", bestAcceptedDistance), false);
        } else {
            message(player, "Scan done. No candidate survived two independent passes.", false);
        }

        if (logPath != null) {
            message(player, "Log: " + logPath.toAbsolutePath(), false);
        }
    }

    private static void applyBest(LocalPlayer player) {
        if (bestOffset == null) {
            message(player, "Run an F8 scan first. No two-pass candidate is stored.", false);
            return;
        }

        restorePoint = player.position();
        originalNoPhysics = player.noPhysics;
        manualRestoreAvailable = true;
        target = restorePoint.add(bestOffset);
        correctionObserved = false;
        correctionPackets = 0;
        explicitOutboundPackets = 0;
        moveLocalAndSend(player, target);
        stateTicks = 0;
        state = State.APPLYING_BEST;
        message(player, String.format(Locale.ROOT,
            "Retrying %.3f blocks for a 3-second verification. F10 restores.", bestAcceptedDistance), false);
    }

    private static void tickApplyingBest(LocalPlayer player) {
        freeze(player);
        stateTicks++;

        double error = player.position().distanceTo(target);
        if (correctionObserved || error > CORRECTION_ERROR) {
            restore(player, "Best candidate was corrected by the server.");
            return;
        }

        if (stateTicks == 10 || stateTicks == 30) {
            sendPosition(player, target);
        }

        if (stateTicks >= APPLY_VERIFY_TICKS) {
            player.noPhysics = originalNoPhysics;
            state = State.IDLE;
            message(player, "No setback arrived through the 3-second verification window. F10 returns to the start.", false);
        }
    }

    private static void restore(LocalPlayer player, String text) {
        if (restorePoint != null) {
            moveLocalAndSend(player, restorePoint);
        }
        player.noPhysics = originalNoPhysics;
        state = State.IDLE;
        manualRestoreAvailable = false;
        closeLogQuietly();
        message(player, text, false);
    }

    private static void freeze(LocalPlayer player) {
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
    }

    private static void moveLocalAndSend(LocalPlayer player, Vec3 position) {
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        player.setPos(position.x, position.y, position.z);
        sendPosition(player, position);
    }

    private static void sendPosition(LocalPlayer player, Vec3 position) {
        player.connection.send(new ServerboundMovePlayerPacket.Pos(
            position.x,
            position.y,
            position.z,
            player.onGround(),
            player.horizontalCollision
        ));
        explicitOutboundPackets++;
    }

    private static void openLog() {
        closeLogQuietly();
        try {
            Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Files.createDirectories(directory);
            String fileName = "scan-v2-" + Instant.now().toString().replace(':', '-') + ".csv";
            logPath = directory.resolve(fileName);
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write("timestamp,direction,attempt,trial,distance,explicit_outbound,server_corrections,target_x,target_y,target_z,final_x,final_y,final_z,error,result\n");
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
            logPath = null;
        }
    }

    private static void writeLog(String result, Vec3 finalPosition, double error) {
        if (logWriter == null || target == null) {
            return;
        }
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%s,%s,%d,%d,%.3f,%d,%d,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s%n",
                Instant.now(),
                selectedDirection,
                candidateIndex + 1,
                trialNumber,
                currentDistance,
                explicitOutboundPackets,
                correctionPackets,
                target.x, target.y, target.z,
                finalPosition.x, finalPosition.y, finalPosition.z,
                error,
                result
            ));
            logWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private static void closeLogQuietly() {
        if (logWriter == null) {
            return;
        }
        try {
            logWriter.close();
        } catch (IOException ignored) {
        } finally {
            logWriter = null;
        }
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }
}
