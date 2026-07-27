package dev.denis.phaselab;

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
import net.minecraft.network.protocol.game.ServerboundMovePlayerPacket;
import net.minecraft.resources.Identifier;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

import com.mojang.blaze3d.platform.InputConstants;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Client-only position acceptance laboratory for servers the player owns or is
 * explicitly authorized to test.
 *
 * V3 deliberately separates three very different outcomes:
 *  1. LOCAL_ONLY: the camera/player moved locally, but the server gave no proof.
 *  2. SETBACK: the server sent a position correction.
 *  3. SERVER_VERIFIED: a target-only witness container opened from the target.
 *
 * The witness requirement fixes the false-positive flaw in V2, where a server
 * could silently ignore movement without sending a correction packet.
 */
public final class PhaseLabClient implements ClientModInitializer {
    private static final double PROFILE_STEP = 0.025D;
    private static final double EXTRA_LAYER_CLEARANCE = 1.10D;
    private static final double MAX_HARD_SCAN_DISTANCE = 5.00D;
    private static final int REQUIRED_SCAN_PASSES = 2;
    private static final int PREPARE_TICKS = 5;
    private static final int SCAN_VERIFY_TICKS = 80;
    private static final int RESTORE_TICKS = 8;
    private static final int APPLY_SETTLE_TICKS = 24;
    private static final int WITNESS_TIMEOUT_TICKS = 80;
    private static final double ACCEPT_ERROR = 0.18D;
    private static final double CORRECTION_ERROR = 0.45D;
    private static final double TARGET_WITNESS_MAX_DISTANCE = 5.50D;
    private static final double ORIGIN_WITNESS_MIN_DISTANCE = 6.25D;

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "main")
    );

    private static KeyMapping statusKey;
    private static KeyMapping witnessKey;
    private static KeyMapping directionKey;
    private static KeyMapping scanKey;
    private static KeyMapping applyKey;
    private static KeyMapping abortKey;

    private enum State {
        IDLE,
        PREPARING,
        SCAN_VERIFYING,
        RESTORING,
        APPLY_SETTLING,
        WITNESS_WAIT
    }

    private enum ScanDirection {
        FORWARD,
        RIGHT,
        BACKWARD,
        LEFT,
        DOWN,
        UP;

        private ScanDirection next() {
            ScanDirection[] values = values();
            return values[(ordinal() + 1) % values.length];
        }
    }

    private record Candidate(double distance, double gapStart, double gapEnd, double clearance) {
    }

    private static State state = State.IDLE;
    private static ScanDirection selectedDirection = ScanDirection.FORWARD;

    private static Vec3 scanOrigin;
    private static Vec3 applyOrigin;
    private static Vec3 target;
    private static Vec3 restorePoint;
    private static Vec3 scanVector;
    private static Candidate currentCandidate;
    private static Candidate bestCandidate;
    private static List<Candidate> candidates = List.of();
    private static BlockPos witnessPos;

    private static double scanMaxDistance;
    private static int candidateIndex;
    private static int trialNumber = 1;
    private static int stateTicks;
    private static int correctionPackets;
    private static int explicitOutboundPackets;
    private static boolean correctionObserved;
    private static boolean repeatCandidateAfterRestore;
    private static boolean packetHookSeen;
    private static boolean openScreenHookSeen;
    private static boolean witnessOpenObserved;
    private static boolean originalNoPhysics;

    private static BufferedWriter logWriter;
    private static Path logPath;

    @Override
    public void onInitializeClient() {
        registerKeys();
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabClient::onClientTick);
    }

    private static void registerKeys() {
        statusKey = register("key.phaselab.status", GLFW.GLFW_KEY_F5);
        witnessKey = register("key.phaselab.witness", GLFW.GLFW_KEY_F6);
        directionKey = register("key.phaselab.direction", GLFW.GLFW_KEY_F7);
        scanKey = register("key.phaselab.scan", GLFW.GLFW_KEY_F8);
        applyKey = register("key.phaselab.apply", GLFW.GLFW_KEY_F9);
        abortKey = register("key.phaselab.abort", GLFW.GLFW_KEY_F10);
    }

    private static KeyMapping register(String translationKey, int defaultKey) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(
            translationKey,
            InputConstants.Type.KEYSYM,
            defaultKey,
            CATEGORY
        ));
    }

    /** Called by the packet-listener mixin for a real server position correction. */
    public static void onServerPositionCorrection() {
        packetHookSeen = true;
        if (state == State.SCAN_VERIFYING || state == State.APPLY_SETTLING || state == State.WITNESS_WAIT) {
            correctionObserved = true;
            correctionPackets++;
        }
    }

    /** Called only when the server sends an OpenScreen packet. */
    public static void onServerOpenScreen() {
        openScreenHookSeen = true;
        if (state == State.WITNESS_WAIT) {
            witnessOpenObserved = true;
        }
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            resetDisconnectedState();
            return;
        }

        while (statusKey.consumeClick()) {
            showStatus(player);
        }
        while (witnessKey.consumeClick()) {
            captureWitness(client, player);
        }
        while (directionKey.consumeClick()) {
            if (state == State.IDLE) {
                selectedDirection = selectedDirection.next();
                message(player, "Direction: " + selectedDirection, false);
            } else {
                message(player, "Abort or finish the current probe first.", false);
            }
        }
        while (scanKey.consumeClick()) {
            if (state == State.IDLE) {
                startScan(player);
            } else {
                message(player, "A probe is already running. Use the abort key.", false);
            }
        }
        while (applyKey.consumeClick()) {
            if (state == State.IDLE) {
                applyBest(client, player);
            } else {
                message(player, "Finish or abort the current probe first.", false);
            }
        }
        while (abortKey.consumeClick()) {
            if (state != State.IDLE || restorePoint != null) {
                restore(player, "Probe aborted and position restored.");
            }
        }

        switch (state) {
            case PREPARING -> tickPreparing(player);
            case SCAN_VERIFYING -> tickScanVerifying(player);
            case RESTORING -> tickRestoring(player);
            case APPLY_SETTLING -> tickApplySettling(client, player);
            case WITNESS_WAIT -> tickWitnessWait(player);
            case IDLE -> {
            }
        }
    }

    private static void captureWitness(Minecraft client, LocalPlayer player) {
        HitResult hit = client.hitResult;
        if (!(hit instanceof BlockHitResult blockHit) || hit.getType() != HitResult.Type.BLOCK) {
            witnessPos = null;
            message(player, "Witness cleared. Look directly at a barrel/chest and press the witness key to set one.", false);
            return;
        }

        witnessPos = blockHit.getBlockPos().immutable();
        message(player, "Witness set at " + witnessPos.toShortString() + ". It must open a server screen.", false);
    }

    private static void showStatus(LocalPlayer player) {
        String witness = witnessPos == null ? "none" : witnessPos.toShortString();
        message(player,
            "state=" + state
                + " | direction=" + selectedDirection
                + " | correctionHook=" + (packetHookSeen ? "seen" : "not-seen-yet")
                + " | screenHook=" + (openScreenHookSeen ? "seen" : "not-seen-yet")
                + " | witness=" + witness,
            false
        );
    }

    private static void startScan(LocalPlayer player) {
        scanOrigin = player.position();
        restorePoint = scanOrigin;
        originalNoPhysics = player.noPhysics;
        bestCandidate = null;
        candidateIndex = 0;
        trialNumber = 1;
        repeatCandidateAfterRestore = false;
        scanVector = calculateDirection(player, selectedDirection);
        scanMaxDistance = calculateScanLimit(player.getBoundingBox(), scanVector);
        candidates = discoverCandidates(player, scanVector, scanMaxDistance);

        if (candidates.isEmpty()) {
            message(player, String.format(Locale.ROOT,
                "No complete collision layer with a clear player-sized exit was found within %.2f blocks.",
                scanMaxDistance
            ), false);
            return;
        }

        openLog();
        beginScanAttempt(player);
        message(player,
            "Found a real layer and " + candidates.size() + " safe gap points. Testing each twice.",
            false
        );
    }

    private static Vec3 calculateDirection(LocalPlayer player, ScanDirection direction) {
        double radians = Math.toRadians(player.getYRot());
        Vec3 forward = new Vec3(-Math.sin(radians), 0.0D, Math.cos(radians)).normalize();
        Vec3 right = new Vec3(-forward.z, 0.0D, forward.x);
        return switch (direction) {
            case FORWARD -> forward;
            case RIGHT -> right;
            case BACKWARD -> forward.scale(-1.0D);
            case LEFT -> right.scale(-1.0D);
            case DOWN -> new Vec3(0.0D, -1.0D, 0.0D);
            case UP -> new Vec3(0.0D, 1.0D, 0.0D);
        };
    }

    private static double calculateScanLimit(AABB box, Vec3 direction) {
        double widthX = box.maxX - box.minX;
        double heightY = box.maxY - box.minY;
        double widthZ = box.maxZ - box.minZ;
        double projectedBodyExtent = Math.abs(direction.x) * widthX
            + Math.abs(direction.y) * heightY
            + Math.abs(direction.z) * widthZ;
        return Math.min(MAX_HARD_SCAN_DISTANCE, 1.0D + projectedBodyExtent + EXTRA_LAYER_CLEARANCE);
    }

    /**
     * Finds the first clear interval after crossing a solid collision interval,
     * then emits a few interior points. It never chooses the farthest arbitrary
     * offset, which was another V2 failure mode.
     */
    private static List<Candidate> discoverCandidates(LocalPlayer player, Vec3 direction, double maxDistance) {
        AABB originBox = player.getBoundingBox();
        boolean crossedCollision = false;
        double gapStart = -1.0D;
        double gapEnd = -1.0D;

        for (double distance = PROFILE_STEP; distance <= maxDistance + 0.0001D; distance += PROFILE_STEP) {
            AABB sampledBox = originBox.move(direction.scale(distance)).deflate(0.001D);
            boolean clear = player.level().noCollision(player, sampledBox);

            if (!clear) {
                if (gapStart >= 0.0D) {
                    gapEnd = distance - PROFILE_STEP;
                    break;
                }
                crossedCollision = true;
            } else if (crossedCollision && gapStart < 0.0D) {
                gapStart = distance;
            }
        }

        if (gapStart < 0.0D) {
            return List.of();
        }
        if (gapEnd < 0.0D) {
            gapEnd = maxDistance;
        }

        double usableStart = gapStart + 0.025D;
        double usableEnd = gapEnd - 0.025D;
        if (usableEnd < usableStart) {
            return List.of();
        }

        double span = usableEnd - usableStart;
        Set<Double> unique = new LinkedHashSet<>();
        unique.add(roundDistance((usableStart + usableEnd) * 0.5D));
        unique.add(roundDistance(usableStart + Math.min(0.10D, span * 0.25D)));
        unique.add(roundDistance(usableEnd - Math.min(0.10D, span * 0.25D)));

        List<Candidate> result = new ArrayList<>();
        for (double distance : unique) {
            double clearance = Math.min(distance - gapStart, gapEnd - distance);
            if (clearance >= 0.0D) {
                result.add(new Candidate(distance, gapStart, gapEnd, clearance));
            }
        }
        result.sort(Comparator.comparingDouble(Candidate::clearance).reversed());
        return List.copyOf(result);
    }

    private static double roundDistance(double value) {
        return Math.round(value * 1000.0D) / 1000.0D;
    }

    private static void beginScanAttempt(LocalPlayer player) {
        currentCandidate = candidates.get(candidateIndex);
        target = scanOrigin.add(scanVector.scale(currentCandidate.distance()));
        correctionObserved = false;
        correctionPackets = 0;
        explicitOutboundPackets = 0;
        moveLocalAndSend(player, scanOrigin);
        stateTicks = 0;
        state = State.PREPARING;
        message(player, String.format(Locale.ROOT,
            "Candidate %.3f, pass %d/%d",
            currentCandidate.distance(), trialNumber, REQUIRED_SCAN_PASSES
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
        state = State.SCAN_VERIFYING;
    }

    private static void tickScanVerifying(LocalPlayer player) {
        freeze(player);
        stateTicks++;
        double error = player.position().distanceTo(target);

        if (correctionObserved) {
            finishScanAttempt(player, "SETBACK_PACKET", error);
            return;
        }
        if (error > CORRECTION_ERROR) {
            finishScanAttempt(player, "LOCAL_POSITION_DRIFT", error);
            return;
        }

        if (stateTicks == 15 || stateTicks == 45) {
            sendPosition(player, target);
        }

        if (stateTicks >= SCAN_VERIFY_TICKS) {
            String result = error <= ACCEPT_ERROR ? "LOCAL_ONLY_NO_SETBACK" : "INCONCLUSIVE";
            finishScanAttempt(player, result, error);
        }
    }

    private static void finishScanAttempt(LocalPlayer player, String result, double error) {
        writeLog("scan", result, player.position(), error, false, false);

        boolean passedLocally = "LOCAL_ONLY_NO_SETBACK".equals(result);
        if (passedLocally && trialNumber < REQUIRED_SCAN_PASSES) {
            repeatCandidateAfterRestore = true;
            trialNumber++;
        } else {
            if (passedLocally && trialNumber >= REQUIRED_SCAN_PASSES) {
                if (bestCandidate == null || currentCandidate.clearance() > bestCandidate.clearance()) {
                    bestCandidate = currentCandidate;
                }
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
            beginScanAttempt(player);
            return;
        }

        candidateIndex++;
        if (candidateIndex < candidates.size()) {
            beginScanAttempt(player);
            return;
        }

        moveLocalAndSend(player, scanOrigin);
        player.noPhysics = originalNoPhysics;
        state = State.IDLE;
        closeLogQuietly();

        if (bestCandidate == null) {
            message(player, "No candidate even survived locally. The server/client corrected every attempt.", false);
            return;
        }

        message(player, String.format(Locale.ROOT,
            "Best geometry point: %.3f. This is NOT server-verified. Set an exclusive witness, then use Apply.",
            bestCandidate.distance()
        ), false);
        message(player, "Log: " + logPath.toAbsolutePath(), false);
    }

    private static void applyBest(Minecraft client, LocalPlayer player) {
        if (bestCandidate == null || scanVector == null) {
            message(player, "Run a scan first.", false);
            return;
        }
        if (witnessPos == null) {
            message(player, "No witness set. Look at a barrel/chest reachable only from inside, then press Witness.", false);
            return;
        }

        applyOrigin = player.position();
        restorePoint = applyOrigin;
        originalNoPhysics = player.noPhysics;
        target = applyOrigin.add(scanVector.scale(bestCandidate.distance()));

        AABB proposedBox = player.getBoundingBox().move(target.subtract(applyOrigin)).deflate(0.001D);
        if (!player.level().noCollision(player, proposedBox)) {
            message(player, "Target is no longer clear. Return to the scan position and rescan.", false);
            return;
        }

        double targetDistance = eyePosition(target, player).distanceTo(Vec3.atCenterOf(witnessPos));
        double originDistance = eyePosition(applyOrigin, player).distanceTo(Vec3.atCenterOf(witnessPos));
        if (targetDistance > TARGET_WITNESS_MAX_DISTANCE || originDistance < ORIGIN_WITNESS_MIN_DISTANCE) {
            message(player, String.format(Locale.ROOT,
                "Witness is not exclusive: target=%.2f, origin=%.2f. Need target <= %.2f and origin >= %.2f.",
                targetDistance, originDistance, TARGET_WITNESS_MAX_DISTANCE, ORIGIN_WITNESS_MIN_DISTANCE
            ), false);
            return;
        }

        correctionObserved = false;
        correctionPackets = 0;
        explicitOutboundPackets = 0;
        witnessOpenObserved = false;
        openLog();
        moveLocalAndSend(player, target);
        stateTicks = 0;
        state = State.APPLY_SETTLING;
        message(player, "Applying candidate. Waiting for the server before witness interaction...", false);
    }

    private static Vec3 eyePosition(Vec3 feetPosition, LocalPlayer player) {
        return feetPosition.add(0.0D, player.getEyeHeight(), 0.0D);
    }

    private static void tickApplySettling(Minecraft client, LocalPlayer player) {
        freeze(player);
        stateTicks++;
        double error = player.position().distanceTo(target);

        if (correctionObserved || error > CORRECTION_ERROR) {
            writeLog("apply", "SETBACK_BEFORE_WITNESS", player.position(), error, false, false);
            restore(player, "Server corrected the target before witness verification.");
            return;
        }

        if (stateTicks == 10) {
            sendPosition(player, target);
        }

        if (stateTicks < APPLY_SETTLE_TICKS) {
            return;
        }

        BlockHitResult witnessHit = new BlockHitResult(
            Vec3.atCenterOf(witnessPos),
            Direction.UP,
            witnessPos,
            false
        );
        client.gameMode.useItemOn(player, InteractionHand.MAIN_HAND, witnessHit);
        stateTicks = 0;
        witnessOpenObserved = false;
        state = State.WITNESS_WAIT;
        message(player, "Witness request sent. Waiting for a server OpenScreen packet...", false);
    }

    private static void tickWitnessWait(LocalPlayer player) {
        freeze(player);
        stateTicks++;
        double error = player.position().distanceTo(target);

        if (correctionObserved || error > CORRECTION_ERROR) {
            writeLog("apply", "SETBACK_DURING_WITNESS", player.position(), error, true, false);
            restore(player, "Server corrected the target during witness verification.");
            return;
        }

        if (witnessOpenObserved) {
            writeLog("apply", "SERVER_VERIFIED_WITNESS_OPEN", player.position(), error, true, true);
            player.noPhysics = originalNoPhysics;
            state = State.IDLE;
            closeLogQuietly();
            message(player, "SERVER VERIFIED: the target-only witness opened. This is real server-position evidence.", false);
            return;
        }

        if (stateTicks >= WITNESS_TIMEOUT_TICKS) {
            writeLog("apply", "UNVERIFIED_WITNESS_TIMEOUT", player.position(), error, true, false);
            restore(player, "No witness screen arrived. The apparent movement was not server-verified.");
        }
    }

    private static void restore(LocalPlayer player, String text) {
        if (restorePoint != null) {
            moveLocalAndSend(player, restorePoint);
        }
        player.noPhysics = originalNoPhysics;
        player.setDeltaMovement(Vec3.ZERO);
        state = State.IDLE;
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
        player.absSnapTo(position.x, position.y, position.z);
        sendPosition(player, position);
    }

    private static void sendPosition(LocalPlayer player, Vec3 position) {
        player.connection.send(new ServerboundMovePlayerPacket.PosRot(
            position.x,
            position.y,
            position.z,
            player.getYRot(),
            player.getXRot(),
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
            String fileName = "phaselab-v3-" + Instant.now().toString().replace(':', '-') + ".csv";
            logPath = directory.resolve(fileName);
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write("timestamp,phase,direction,candidate,trial,gap_start,gap_end,clearance,outbound,corrections,witness_attempted,witness_open,target_x,target_y,target_z,final_x,final_y,final_z,error,result\n");
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
            logPath = null;
        }
    }

    private static void writeLog(
        String phase,
        String result,
        Vec3 finalPosition,
        double error,
        boolean witnessAttempted,
        boolean witnessOpen
    ) {
        if (logWriter == null || target == null) {
            return;
        }
        Candidate candidate = currentCandidate != null ? currentCandidate : bestCandidate;
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%s,%s,%s,%.3f,%d,%.3f,%.3f,%.3f,%d,%d,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s%n",
                Instant.now(),
                phase,
                selectedDirection,
                candidate == null ? -1.0D : candidate.distance(),
                trialNumber,
                candidate == null ? -1.0D : candidate.gapStart(),
                candidate == null ? -1.0D : candidate.gapEnd(),
                candidate == null ? -1.0D : candidate.clearance(),
                explicitOutboundPackets,
                correctionPackets,
                witnessAttempted,
                witnessOpen,
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

    private static void resetDisconnectedState() {
        closeLogQuietly();
        state = State.IDLE;
        scanOrigin = null;
        applyOrigin = null;
        target = null;
        restorePoint = null;
        bestCandidate = null;
        currentCandidate = null;
        candidates = List.of();
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }
}
