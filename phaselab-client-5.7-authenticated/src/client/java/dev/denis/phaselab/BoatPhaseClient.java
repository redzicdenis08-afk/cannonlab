package dev.denis.phaselab;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.PlayerInfo;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ClientboundSetPassengersPacket;
import net.minecraft.network.protocol.game.ServerboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ServerboundPlayerInputPacket;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.animal.equine.AbstractHorse;
import net.minecraft.world.entity.vehicle.boat.AbstractBoat;
import net.minecraft.world.entity.player.Input;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Client-only bounded verifier for authorized private server testing.
 *
 * P runs one legacy bounded diagnostic profile. F6 cycles the bamboo-raft
 * red-team profiles and F7 runs the selected profile. All active probes remain
 * target-authorized, bounded, fail-closed on telemetry loss, and client-observed
 * until a server snapshot plus inside-only witness confirms the result.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final String MOD_VERSION = "5.7.0-authenticated";
    private static final String AUTHORIZED_TARGETS_FILE = "authorized-targets.txt";
    private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().setPrettyPrinting().create();
    private static final AtomicLong EVENT_SEQUENCE = new AtomicLong();
    private static final double STEP = 0.25D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;
    private static final int DEFAULT_SETTLE_TICKS = 40;
    private static final int MANUAL_REMOUNT_WINDOW_TICKS = 120;
    private static final int REMOUNT_STABLE_TICKS = 20;
    private static final int MOUNT_ARM_TICKS = 10;
    private static final double MIN_RETAINED_PROGRESS = 0.125D;
    private static final int RATCHET_WARMUP_STEPS = 3;
    private static final int RATCHET_HANDSHAKE_TIMEOUT_TICKS = 50;
    private static final int RATCHET_QUIET_TICKS = 4;
    private static final int RATCHET_BATCH_SIZE = 12;
    private static final double RATCHET_TOTAL_DISTANCE = 241.52D;
    private static final double RATCHET_BURST_DISTANCE = 241.50D;
    private static final int RATCHET_FINAL_SETTLE_PACKETS = 4;
    private static final int RATCHET_FINAL_SETTLE_INTERVAL_TICKS = 3;
    private static final int RATCHET_PRE_DISMOUNT_TICKS = 20;
    private static final int RATCHET_DISMOUNT_WAIT_TICKS = 40;
    private static final int RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS = 4;
    private static final int RATCHET_EXPECTED_TOTAL_MOVE_PACKETS = 970;
    private static final Profile RATCHET_PROFILE =
        new Profile("ratchet-full-b12", RATCHET_BATCH_SIZE, RATCHET_TOTAL_DISTANCE, 60);
    private static final Profile RAFT_WALL_PROFILE =
        new Profile("bamboo-raft-wall-1", 1, 2.15D, 20);

    private record Profile(String name, int packetsPerTick, double distance, int settleTicks) {}

    private enum RaftStrategy {
        STEPPED,
        EDGE_LEAP,
        ADAPTIVE_RAMP
    }

    private enum RaftTransport {
        LOCAL_MIRROR,
        PACKET_ONLY
    }

    private record RaftProbe(String name, RaftStrategy strategy, RaftTransport transport, double step,
                             double distance, double approachDistance, int settleTicks, int paceTicks,
                             boolean syncInput, boolean forceOnGround) {}

    private static final List<RaftProbe> RAFT_PROBES = List.of(
        new RaftProbe("packet-only-005-3t", RaftStrategy.STEPPED, RaftTransport.PACKET_ONLY,
            0.05D, 2.15D, 0.0D, 40, 3, true, true),
        new RaftProbe("packet-only-010-2t", RaftStrategy.STEPPED, RaftTransport.PACKET_ONLY,
            0.10D, 2.15D, 0.0D, 40, 2, true, true),
        new RaftProbe("packet-only-015-2t", RaftStrategy.STEPPED, RaftTransport.PACKET_ONLY,
            0.15D, 2.15D, 0.0D, 40, 2, true, true),
        new RaftProbe("packet-only-020-1t", RaftStrategy.STEPPED, RaftTransport.PACKET_ONLY,
            0.20D, 2.15D, 0.0D, 30, 1, true, true),
        new RaftProbe("packet-only-025-1t", RaftStrategy.STEPPED, RaftTransport.PACKET_ONLY,
            0.25D, 2.15D, 0.0D, 30, 1, true, true),
        new RaftProbe("packet-edge-140", RaftStrategy.EDGE_LEAP, RaftTransport.PACKET_ONLY,
            0.25D, 2.15D, 0.75D, 30, 1, true, true),
        new RaftProbe("packet-adaptive-ramp", RaftStrategy.ADAPTIVE_RAMP, RaftTransport.PACKET_ONLY,
            0.05D, 2.15D, 0.0D, 40, 2, true, true),
        new RaftProbe("legacy-local-025", RaftStrategy.STEPPED, RaftTransport.LOCAL_MIRROR,
            0.25D, 2.15D, 0.0D, 20, 1, false, false)
    );

    private enum TestKind {
        PROFILE,
        RATCHET
    }

    private enum VehicleKind {
        BOAT,
        HORSE
    }

    private enum Mode {
        FORWARD,
        DOWN
    }

    private enum State {
        IDLE,
        ARMING,
        SENDING,
        RATCHET_WARMUP,
        RATCHET_BORDER_SEND,
        RATCHET_BORDER_WAIT,
        RATCHET_QUIET,
        RATCHET_BURST,
        RATCHET_FINAL_SETTLE,
        RATCHET_PRE_DISMOUNT,
        RATCHET_DISMOUNT_SEND,
        RATCHET_DISMOUNT_WAIT,
        SETTLING,
        REMOUNT_WINDOW,
        REMOUNT_STABLE
    }

    private static final List<Profile> BOAT_FORWARD_PROFILES = List.of(
        new Profile("bf-01-tiny", 1, 0.50D, 40),
        new Profile("bf-02-slow", 1, 1.00D, 40),
        new Profile("bf-03-paced2", 2, 1.00D, 50),
        new Profile("bf-04-paced4", 4, 2.00D, 60),
        new Profile("bf-05-fast4", 4, 4.00D, 70),
        new Profile("bf-06-fast8", 8, 4.00D, 80)
    );

    private static final List<Profile> BOAT_DOWN_PROFILES = List.of(
        new Profile("bd-01-quarter", 1, 0.25D, 50),
        new Profile("bd-02-half", 1, 0.50D, 60),
        new Profile("bd-03-three-quarter", 1, 0.75D, 70),
        new Profile("bd-04-one", 1, 1.00D, 80),
        new Profile("bd-05-paced2", 2, 1.00D, 90)
    );

    private static final List<Profile> HORSE_FORWARD_PROFILES = List.of(
        new Profile("hf-01-quarter", 1, 0.25D, 50),
        new Profile("hf-02-half", 1, 0.50D, 60),
        new Profile("hf-03-one", 1, 1.00D, 70),
        new Profile("hf-04-paced2", 2, 1.00D, 80),
        new Profile("hf-05-paced4", 4, 2.00D, 90),
        new Profile("hf-06-fast8", 8, 4.00D, 100)
    );

    private static final List<Profile> HORSE_DOWN_PROFILES = List.of(
        new Profile("hd-01-quarter", 1, 0.25D, 60),
        new Profile("hd-02-half", 1, 0.50D, 80),
        new Profile("hd-03-three-quarter", 1, 0.75D, 100),
        new Profile("hd-04-paced2", 2, 0.75D, 120)
    );

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "verifier")
    );

    private static KeyMapping testKey;
    private static KeyMapping cycleRaftKey;
    private static KeyMapping ratchetKey;
    private static KeyMapping abortKey;

    private static final Map<String, Integer> profileIndices = new HashMap<>();
    private static final JsonArray completedTests = new JsonArray();

    private static boolean readyMessageShown;
    private static boolean active;
    private static State state = State.IDLE;
    private static long clientTick;
    private static int stateTicks;
    private static int testSequence;
    private static int sentPackets;
    private static int playerCorrectionCount;
    private static int vehicleCorrectionCount;
    private static int separationCount;
    private static int remountCount;
    private static int remountStableTicks;
    private static int mountHandshakeStableTicks;
    private static int ratchetWarmupSteps;
    private static int ratchetFinalSettlePackets;
    private static int passengerPacketCount;
    private static boolean wasMounted;
    private static boolean remountAccepted;
    private static boolean secondSeparation;
    private static boolean ratchetHandshakeCorrection;
    private static boolean ratchetDismountRequested;
    private static boolean clientVehicleRemovedObserved;
    private static boolean localPassengerGraphSeparated;
    private static boolean serverPassengerAttached;
    private static boolean serverPassengerDetached;
    private static boolean serverPassengerDetachObserved;
    private static boolean serverPassengerReattachObserved;
    private static boolean logWriteFailed;
    private static String logWriteFailure = "";
    private static boolean originalVehicleNoPhysics;
    private static double sentDistance;
    private static double maxObservedVehicleProgress;
    private static double maxObservedPlayerProgress;
    private static double lastPlayerCorrectionProgress;
    private static double lastVehicleCorrectionProgress;
    private static long testStartNanos;
    private static long firstSeparationNanos;
    private static long remountNanos;

    private static Entity activeVehicle;
    private static UUID activeVehicleUuid;
    private static TestKind testKind;
    private static VehicleKind vehicleKind;
    private static Mode mode;
    private static Profile profile;
    private static int profileIndex;
    private static Vec3 direction;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static Vec3 correctionHeadPlayer;
    private static Vec3 correctionHeadVehicle;
    private static String currentTestId;
    private static int raftProbeIndex;
    private static RaftProbe activeRaftProbe;

    private static Path sessionDirectory;
    private static Path sessionJsonl;
    private static Path summaryJson;
    private static BufferedWriter writer;
    private static String sessionId;

    @Override
    public void onInitializeClient() {
        testKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.verifier_test",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        cycleRaftKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.verifier_cycle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_F6,
            CATEGORY
        ));
        ratchetKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.verifier_ratchet",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_F7,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.verifier_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    public static void onServerPlayerCorrectionHead(ClientboundPlayerPositionPacket packet) {
        if (!active) return;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        correctionHeadPlayer = player == null ? null : player.position();
        correctionHeadVehicle = activeVehicle == null ? null : activeVehicle.position();
        JsonObject event = event("PLAYER_CORRECTION_HEAD", player);
        event.addProperty("packet", String.valueOf(packet));
        event.add("player_before", vec(correctionHeadPlayer));
        event.add("vehicle_before", vec(correctionHeadVehicle));
        append(event);
        if (testKind != TestKind.RATCHET) {
            silenceAfterCorrection(player, "Player correction received. Verifier is now silent.");
        }
    }

    public static void onServerPlayerCorrectionTail(ClientboundPlayerPositionPacket packet) {
        if (!active) return;
        playerCorrectionCount++;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        Vec3 playerAfter = player == null ? null : player.position();
        Vec3 vehicleAfter = activeVehicle == null ? null : activeVehicle.position();
        lastPlayerCorrectionProgress = projectedProgress(playerStart, playerAfter, direction);
        JsonObject event = event("PLAYER_CORRECTION_TAIL", player);
        event.addProperty("packet", String.valueOf(packet));
        event.add("player_before", vec(correctionHeadPlayer));
        event.add("player_after", vec(playerAfter));
        event.add("vehicle_before", vec(correctionHeadVehicle));
        event.add("vehicle_after", vec(vehicleAfter));
        event.addProperty("player_progress", lastPlayerCorrectionProgress);
        event.addProperty("vehicle_progress", projectedProgress(vehicleStart, vehicleAfter, direction));
        append(event);

        if (testKind == TestKind.RATCHET
            && state == State.RATCHET_BORDER_WAIT
            && !ratchetHandshakeCorrection) {
            ratchetHandshakeCorrection = true;
            state = State.RATCHET_QUIET;
            stateTicks = 0;
            JsonObject handshake = event("RATCHET_HANDSHAKE_ACCEPTED", player);
            handshake.addProperty("quiet_ticks", RATCHET_QUIET_TICKS);
            append(handshake);
            actionbar(player, "Border correction captured. Quiet window started...");
        }
    }

    public static void onServerVehicleCorrectionHead(ClientboundMoveVehiclePacket packet) {
        if (!active) return;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        correctionHeadPlayer = player == null ? null : player.position();
        correctionHeadVehicle = activeVehicle == null ? null : activeVehicle.position();
        JsonObject event = event("VEHICLE_CORRECTION_HEAD", player);
        event.addProperty("packet", String.valueOf(packet));
        event.add("player_before", vec(correctionHeadPlayer));
        event.add("vehicle_before", vec(correctionHeadVehicle));
        append(event);
        if (!ratchetCorrectionRecoverableState()) {
            silenceAfterCorrection(player, "Vehicle correction received. Verifier is now silent.");
        }
    }

    public static void onServerVehicleCorrectionTail(ClientboundMoveVehiclePacket packet) {
        if (!active) return;
        vehicleCorrectionCount++;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        Vec3 playerAfter = player == null ? null : player.position();
        Vec3 vehicleAfter = activeVehicle == null ? null : activeVehicle.position();
        lastVehicleCorrectionProgress = projectedProgress(vehicleStart, vehicleAfter, direction);
        JsonObject event = event("VEHICLE_CORRECTION_TAIL", player);
        event.addProperty("packet", String.valueOf(packet));
        event.add("player_before", vec(correctionHeadPlayer));
        event.add("player_after", vec(playerAfter));
        event.add("vehicle_before", vec(correctionHeadVehicle));
        event.add("vehicle_after", vec(vehicleAfter));
        event.addProperty("player_progress", projectedProgress(playerStart, playerAfter, direction));
        event.addProperty("vehicle_progress", lastVehicleCorrectionProgress);
        append(event);

        if (testKind == TestKind.RATCHET && ratchetCorrectionRecoverableState()) {
            JsonObject recovery = event("RATCHET_VEHICLE_CORRECTION_RECOVERY", player);
            recovery.addProperty("correction_count", vehicleCorrectionCount);
            recovery.addProperty("maximum", RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS);
            recovery.addProperty("absolute_targets_preserved", true);
            append(recovery);
            if (vehicleCorrectionCount > RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS) {
                finishTest(player, "RATCHET_CORRECTION_LIMIT_EXCEEDED");
            } else {
                actionbar(player, "Recoverable vehicle sync "
                    + vehicleCorrectionCount + "/" + RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS
                    + ". Continuing absolute route...");
            }
        }
    }

    public static void onServerPassengersHead(ClientboundSetPassengersPacket packet) {
        if (!active) return;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        JsonObject event = event("PASSENGERS_HEAD", player);
        addPassengerPacket(event, packet, player);
        event.addProperty("mounted_same_before", player != null && controlledVehicle(player) == activeVehicle);
        append(event);
    }

    public static void onServerPassengersTail(ClientboundSetPassengersPacket packet) {
        if (!active) return;
        passengerPacketCount++;
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        boolean activeVehiclePacket = activeVehicle != null && packet.getVehicle() == activeVehicle.getId();
        boolean containsPlayer = player != null && contains(packet.getPassengers(), player.getId());
        if (activeVehiclePacket) {
            boolean detachWasAlreadyObserved = serverPassengerDetachObserved;
            serverPassengerAttached = containsPlayer;
            serverPassengerDetached = !containsPlayer;
            if (!containsPlayer) {
                serverPassengerDetachObserved = true;
            } else if (detachWasAlreadyObserved) {
                serverPassengerReattachObserved = true;
            }
        }

        JsonObject event = event("PASSENGERS_TAIL", player);
        addPassengerPacket(event, packet, player);
        event.addProperty("active_vehicle_packet", activeVehiclePacket);
        event.addProperty("contains_player", containsPlayer);
        event.addProperty("server_passenger_detach_observed", serverPassengerDetachObserved);
        event.addProperty("server_passenger_reattach_observed", serverPassengerReattachObserved);
        event.addProperty("mounted_same_after", player != null && controlledVehicle(player) == activeVehicle);
        append(event);
    }

    private static void onClientTick(Minecraft client) {
        clientTick++;
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            readyMessageShown = false;
            if (active) finishTest(null, "DISCONNECTED");
            closeSession();
            return;
        }

        if (!readyMessageShown) {
            readyMessageShown = true;
            message(player,
                "PhaseLab Red Team " + MOD_VERSION
                    + " armed. Authorized lab targets only. F6=cycle raft profile, F7=run, P=legacy, O=abort.");
        }

        while (testKey.consumeClick()) {
            if (active) {
                message(player, "A verifier test is already running. Press O to abort it.");
            } else {
                startTest(client, player);
            }
        }
        while (cycleRaftKey.consumeClick()) {
            if (active) {
                message(player, "Abort the active verifier before changing raft profiles.");
            } else {
                raftProbeIndex = (raftProbeIndex + 1) % RAFT_PROBES.size();
                RaftProbe selected = RAFT_PROBES.get(raftProbeIndex);
                message(player, String.format(Locale.ROOT,
                    "Selected raft profile %d/%d: %s | %s/%s | step %.2f | pace %dt | distance %.2f",
                    raftProbeIndex + 1, RAFT_PROBES.size(), selected.name(), selected.strategy(), selected.transport(),
                    selected.step(), selected.paceTicks(), selected.distance()));
            }
        }
        while (ratchetKey.consumeClick()) {
            if (active) {
                message(player, "A verifier test is already running. Press O to abort it.");
            } else {
                startRatchetTest(client, player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) finishTest(player, "ABORTED");
        }

        if (!active) return;
        recordTick(client, player);
        observeMountTransition(player);
        if (!active) {
            flushLog();
            return;
        }
        if (logWriteFailed) {
            String failure = logWriteFailure;
            finishTest(player, "LOG_IO_FAILURE");
            message(player, "Evidence logging failed, so the run was aborted: " + failure);
            return;
        }
        if (serverPassengerReattachObserved) {
            finishTest(player, "SERVER_PASSENGER_REATTACHED_AFTER_DETACH");
            return;
        }
        if (serverPassengerDetachObserved) {
            finishTest(player, "SERVER_PASSENGER_DETACH_OBSERVED");
            return;
        }

        maxObservedVehicleProgress = Math.max(maxObservedVehicleProgress,
            projectedProgress(vehicleStart, activeVehicle == null ? null : activeVehicle.position(), direction));
        maxObservedPlayerProgress = Math.max(maxObservedPlayerProgress,
            projectedProgress(playerStart, player.position(), direction));

        switch (state) {
            case ARMING -> tickArming(player);
            case SENDING -> sendPackets(player);
            case RATCHET_WARMUP -> tickRatchetWarmup(player);
            case RATCHET_BORDER_SEND -> sendRatchetBorder(player);
            case RATCHET_BORDER_WAIT -> tickRatchetBorderWait(player);
            case RATCHET_QUIET -> tickRatchetQuiet(player);
            case RATCHET_BURST -> tickRatchetBurst(player);
            case RATCHET_FINAL_SETTLE -> tickRatchetFinalSettle(player);
            case RATCHET_PRE_DISMOUNT -> tickRatchetPreDismount(player);
            case RATCHET_DISMOUNT_SEND -> sendRatchetDismount(player);
            case RATCHET_DISMOUNT_WAIT -> tickRatchetDismountWait(player);
            case SETTLING -> tickSettling(player);
            case REMOUNT_WINDOW -> tickRemountWindow(player);
            case REMOUNT_STABLE -> tickRemountStable(player);
            case IDLE -> { }
        }
        flushLog();
    }

    private static void startTest(Minecraft client, LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        VehicleKind kind = classifyVehicle(vehicle);
        if (vehicle == null || kind == null) {
            message(player, "Mount and control a normal boat or tamed horse first.");
            return;
        }

        if (!authorizeTarget(client, player)) return;
        if (!ensureSession(client, player)) return;
        vehicleKind = kind;
        mode = player.getXRot() >= DOWN_PITCH_THRESHOLD ? Mode.DOWN : Mode.FORWARD;
        direction = mode == Mode.DOWN ? new Vec3(0.0D, -1.0D, 0.0D) : snappedCardinal(player.getLookAngle());
        List<Profile> profiles = profiles(kind, mode);
        String ladderKey = kind.name() + ":" + mode.name();
        profileIndex = profileIndices.getOrDefault(ladderKey, 0) % profiles.size();
        profile = profiles.get(profileIndex);
        profileIndices.put(ladderKey, (profileIndex + 1) % profiles.size());
        activeRaftProbe = null;

        testKind = TestKind.PROFILE;
        active = true;
        state = State.SENDING;
        stateTicks = 0;
        mountHandshakeStableTicks = 0;
        sentPackets = 0;
        sentDistance = 0.0D;
        playerCorrectionCount = 0;
        vehicleCorrectionCount = 0;
        separationCount = 0;
        remountCount = 0;
        remountStableTicks = 0;
        ratchetWarmupSteps = 0;
        ratchetFinalSettlePackets = 0;
        passengerPacketCount = 0;
        remountAccepted = false;
        secondSeparation = false;
        ratchetHandshakeCorrection = false;
        ratchetDismountRequested = false;
        clientVehicleRemovedObserved = false;
        localPassengerGraphSeparated = false;
        serverPassengerAttached = false;
        serverPassengerDetached = false;
        serverPassengerDetachObserved = false;
        serverPassengerReattachObserved = false;
        maxObservedVehicleProgress = 0.0D;
        maxObservedPlayerProgress = 0.0D;
        lastPlayerCorrectionProgress = 0.0D;
        lastVehicleCorrectionProgress = 0.0D;
        firstSeparationNanos = 0L;
        remountNanos = 0L;
        testStartNanos = System.nanoTime();

        activeVehicle = vehicle;
        activeVehicleUuid = vehicle.getUUID();
        originalVehicleNoPhysics = vehicle.noPhysics;
        playerStart = player.position();
        vehicleStart = vehicle.position();
        wasMounted = true;
        currentTestId = String.format(Locale.ROOT, "%03d-%s-%s-%s",
            ++testSequence, kind.name().toLowerCase(Locale.ROOT), mode.name().toLowerCase(Locale.ROOT), profile.name());

        JsonObject start = event("TEST_START", player);
        start.addProperty("test_id", currentTestId);
        start.addProperty("vehicle_kind", kind.name());
        start.addProperty("mode", mode.name());
        start.addProperty("profile_index", profileIndex);
        start.addProperty("profile_name", profile.name());
        start.addProperty("packets_per_tick", profile.packetsPerTick());
        start.addProperty("distance", profile.distance());
        start.addProperty("settle_ticks", profile.settleTicks());
        start.add("direction", vec(direction));
        start.add("player_start", vec(playerStart));
        start.add("vehicle_start", vec(vehicleStart));
        start.add("environment", environment(client, player, vehicle));
        append(start);

        message(player, String.format(Locale.ROOT,
            "Test %s | %s %s | profile %d/%d: %s, %.2f blocks, %d packet(s)/tick. Stay still.",
            currentTestId,
            kind.name(), mode.name(), profileIndex + 1, profiles.size(), profile.name(),
            profile.distance(), profile.packetsPerTick()));
    }

    private static void startRatchetTest(Minecraft client, LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        VehicleKind kind = classifyVehicle(vehicle);
        if (vehicle == null || kind != VehicleKind.BOAT || !isBambooRaft(vehicle)) {
            message(player, "Mount and control a bamboo raft first. The proven local profile is raft-only.");
            return;
        }
        if (player.getXRot() >= DOWN_PITCH_THRESHOLD) {
            message(player, "Look horizontally through the wall before starting the raft probe.");
            return;
        }

        if (!authorizeTarget(client, player)) return;
        if (!ensureSession(client, player)) return;
        testKind = TestKind.PROFILE;
        vehicleKind = VehicleKind.BOAT;
        mode = Mode.FORWARD;
        direction = snappedCardinal(player.getLookAngle());
        activeRaftProbe = RAFT_PROBES.get(Math.floorMod(raftProbeIndex, RAFT_PROBES.size()));
        profile = new Profile(activeRaftProbe.name(), 1, activeRaftProbe.distance(), activeRaftProbe.settleTicks());
        profileIndex = raftProbeIndex;

        active = true;
        state = State.ARMING;
        stateTicks = 0;
        mountHandshakeStableTicks = 0;
        sentPackets = 0;
        sentDistance = 0.0D;
        playerCorrectionCount = 0;
        vehicleCorrectionCount = 0;
        separationCount = 0;
        remountCount = 0;
        remountStableTicks = 0;
        ratchetWarmupSteps = 0;
        ratchetFinalSettlePackets = 0;
        passengerPacketCount = 0;
        remountAccepted = false;
        secondSeparation = false;
        ratchetHandshakeCorrection = false;
        ratchetDismountRequested = false;
        clientVehicleRemovedObserved = false;
        localPassengerGraphSeparated = false;
        serverPassengerAttached = false;
        serverPassengerDetached = false;
        serverPassengerDetachObserved = false;
        serverPassengerReattachObserved = false;
        maxObservedVehicleProgress = 0.0D;
        maxObservedPlayerProgress = 0.0D;
        lastPlayerCorrectionProgress = 0.0D;
        lastVehicleCorrectionProgress = 0.0D;
        firstSeparationNanos = 0L;
        remountNanos = 0L;
        testStartNanos = System.nanoTime();

        activeVehicle = vehicle;
        activeVehicleUuid = vehicle.getUUID();
        originalVehicleNoPhysics = vehicle.noPhysics;
        playerStart = player.position();
        vehicleStart = vehicle.position();
        wasMounted = true;
        currentTestId = String.format(Locale.ROOT, "%03d-bamboo-raft-%s", ++testSequence, activeRaftProbe.name());

        JsonObject start = event("TEST_START", player);
        start.addProperty("test_id", currentTestId);
        start.addProperty("test_kind", "RAFT_WALL_PROBE");
        start.addProperty("vehicle_kind", vehicleKind.name());
        start.addProperty("entity_type", BuiltInRegistries.ENTITY_TYPE.getKey(vehicle.getType()).toString());
        start.addProperty("mode", mode.name());
        start.addProperty("profile_name", profile.name());
        start.addProperty("packets_per_tick", profile.packetsPerTick());
        start.addProperty("distance", profile.distance());
        start.addProperty("strategy", activeRaftProbe.strategy().name());
        start.addProperty("transport", activeRaftProbe.transport().name());
        start.addProperty("step", activeRaftProbe.step());
        start.addProperty("approach_distance", activeRaftProbe.approachDistance());
        start.addProperty("pace_ticks", activeRaftProbe.paceTicks());
        start.addProperty("sync_input", activeRaftProbe.syncInput());
        start.addProperty("force_on_ground", activeRaftProbe.forceOnGround());
        start.addProperty("mount_arm_ticks", MOUNT_ARM_TICKS);
        start.addProperty("server_endpoint", serverAddress(client));
        start.addProperty("authoritative_server_witness", false);
        start.add("direction", vec(direction));
        start.add("player_start", vec(playerStart));
        start.add("vehicle_start", vec(vehicleStart));
        start.add("environment", environment(client, player, vehicle));
        append(start);

        message(player, String.format(Locale.ROOT,
            "Raft probe %s armed: %s/%s, step %.2f, pace %dt, distance %.2f. Keep hands off; packets start after mount handshake stabilizes.",
            currentTestId, activeRaftProbe.strategy(), activeRaftProbe.transport(), activeRaftProbe.step(),
            activeRaftProbe.paceTicks(), profile.distance()));
    }

    private static void tickArming(LocalPlayer player) {
        stateTicks++;
        if (controlledVehicle(player) != activeVehicle) {
            finishTest(player, "MOUNT_LOST_DURING_ARM");
            return;
        }
        mountHandshakeStableTicks++;
        if (mountHandshakeStableTicks >= MOUNT_ARM_TICKS) {
            state = State.SENDING;
            stateTicks = 0;
            JsonObject stable = event("MOUNT_HANDSHAKE_STABLE", player);
            stable.addProperty("stable_ticks", mountHandshakeStableTicks);
            stable.addProperty("server_passenger_attached_observed", serverPassengerAttached);
            append(stable);
            actionbar(player, "Mount handshake stable. Starting bounded packet-only route...");
        }
    }

    private static void sendForwardInput(LocalPlayer player, String type) {
        player.connection.send(new ServerboundPlayerInputPacket(
            new Input(true, false, false, false, false, false, false)
        ));
        append(event(type, player));
    }

    private static double adaptiveStep(double progress, double remaining) {
        double step = progress < 0.50D ? 0.05D
            : progress < 1.00D ? 0.10D
            : progress < 1.60D ? 0.15D
            : 0.20D;
        return Math.min(step, remaining);
    }

    private static void sendPackets(LocalPlayer player) {
        if (activeVehicle == null || activeVehicle.isRemoved()) {
            finishTest(player, "VEHICLE_REMOVED_DURING_SEND");
            return;
        }

        stateTicks++;
        int paceTicks = activeRaftProbe == null ? 1 : Math.max(1, activeRaftProbe.paceTicks());
        if (activeRaftProbe != null && activeRaftProbe.syncInput()
            && paceTicks > 1 && stateTicks % paceTicks == paceTicks - 1) {
            sendForwardInput(player, "INPUT_SYNC_PRIME");
            return;
        }
        if (stateTicks % paceTicks != 0) return;

        int sentThisTick = 0;
        while (sentThisTick < profile.packetsPerTick() && sentDistance + 1.0E-9 < profile.distance()) {
            double remaining = profile.distance() - sentDistance;
            double step;
            if (activeRaftProbe == null) {
                step = Math.min(STEP, remaining);
            } else if (activeRaftProbe.strategy() == RaftStrategy.ADAPTIVE_RAMP) {
                step = adaptiveStep(sentDistance, remaining);
            } else if (activeRaftProbe.strategy() == RaftStrategy.EDGE_LEAP
                && sentDistance + 1.0E-9 >= activeRaftProbe.approachDistance()) {
                step = remaining;
            } else if (activeRaftProbe.strategy() == RaftStrategy.EDGE_LEAP) {
                step = Math.min(activeRaftProbe.step(),
                    Math.min(remaining, activeRaftProbe.approachDistance() - sentDistance));
            } else {
                step = Math.min(activeRaftProbe.step(), remaining);
            }

            Vec3 before = activeVehicle.position();
            double nextDistance = sentDistance + step;
            boolean packetOnly = activeRaftProbe != null
                && activeRaftProbe.transport() == RaftTransport.PACKET_ONLY;
            Vec3 target = packetOnly
                ? vehicleStart.add(direction.scale(nextDistance))
                : before.add(direction.scale(step));

            if (activeRaftProbe != null && activeRaftProbe.syncInput() && paceTicks == 1) {
                sendForwardInput(player, "INPUT_SYNC_INLINE");
            }
            if (!packetOnly) {
                activeVehicle.noPhysics = true;
                activeVehicle.setPos(target.x, target.y, target.z);
            }
            boolean onGround = activeRaftProbe != null && activeRaftProbe.forceOnGround()
                ? true
                : activeVehicle.onGround();
            player.connection.send(new ServerboundMoveVehiclePacket(
                target,
                activeVehicle.getYRot(),
                activeVehicle.getXRot(),
                onGround
            ));
            if (activeRaftProbe != null && activeRaftProbe.syncInput()) {
                player.connection.send(new ServerboundPlayerInputPacket(Input.EMPTY));
            }
            sentDistance = nextDistance;
            sentPackets++;
            sentThisTick++;

            JsonObject packet = event("PACKET_SEND", player);
            packet.addProperty("packet_index", sentPackets);
            packet.addProperty("sent_distance", sentDistance);
            packet.addProperty("packet_step", step);
            packet.addProperty("packet_only", packetOnly);
            packet.addProperty("pace_ticks", paceTicks);
            packet.addProperty("sync_input", activeRaftProbe != null && activeRaftProbe.syncInput());
            packet.addProperty("on_ground_sent", onGround);
            packet.addProperty("raft_strategy", activeRaftProbe == null ? "LEGACY" : activeRaftProbe.strategy().name());
            packet.add("vehicle_before", vec(before));
            packet.add("target", vec(target));
            packet.add("environment", environment(Minecraft.getInstance(), player, activeVehicle));
            append(packet);
        }

        if (sentDistance + 1.0E-9 >= profile.distance()) {
            player.connection.send(new ServerboundPlayerInputPacket(Input.EMPTY));
            restoreVehiclePhysics();
            state = State.SETTLING;
            stateTicks = 0;
            actionbar(player, "Route sent. Waiting for server correction or passenger detach evidence...");
            append(event("SEND_COMPLETE", player));
        }
    }

    private static void tickRatchetWarmup(LocalPlayer player) {
        if (!sendRatchetStep(player, "RATCHET_WARMUP_PACKET")) return;
        ratchetWarmupSteps++;
        if (ratchetWarmupSteps >= RATCHET_WARMUP_STEPS) {
            state = State.RATCHET_BORDER_SEND;
            stateTicks = 0;
            append(event("RATCHET_WARMUP_COMPLETE", player));
        }
    }

    private static void sendRatchetBorder(LocalPlayer player) {
        if (!sendRatchetStep(player, "RATCHET_BORDER_PACKET")) return;
        state = State.RATCHET_BORDER_WAIT;
        stateTicks = 0;
        append(event("RATCHET_BORDER_SENT", player));
        actionbar(player, "Border packet sent. Waiting for authoritative player correction...");
    }

    private static void tickRatchetBorderWait(LocalPlayer player) {
        stateTicks++;
        if (stateTicks >= RATCHET_HANDSHAKE_TIMEOUT_TICKS) {
            finishTest(player, "RATCHET_HANDSHAKE_TIMEOUT");
        }
    }

    private static void tickRatchetQuiet(LocalPlayer player) {
        stateTicks++;
        if (stateTicks >= RATCHET_QUIET_TICKS) {
            state = State.RATCHET_BURST;
            stateTicks = 0;
            append(event("RATCHET_BURST_START", player));
            actionbar(player, "Correction handshake retained mount. Sending bounded ratchet burst...");
        }
    }

    private static void tickRatchetBurst(LocalPlayer player) {
        int sentThisTick = 0;
        while (sentThisTick < RATCHET_BATCH_SIZE
            && sentDistance + 1.0E-9 < RATCHET_BURST_DISTANCE) {
            if (!sendRatchetStep(player, "RATCHET_BURST_PACKET")) return;
            sentThisTick++;
        }

        if (sentDistance + 1.0E-9 >= RATCHET_BURST_DISTANCE) {
            state = State.RATCHET_FINAL_SETTLE;
            stateTicks = 0;
            JsonObject complete = event("RATCHET_BURST_COMPLETE", player);
            complete.addProperty("sent_packets", sentPackets);
            complete.addProperty("sent_distance", sentDistance);
            append(complete);
            actionbar(player, "Route sent. Holding the final target before automatic dismount...");
        }
    }

    private static boolean sendRatchetStep(LocalPlayer player, String eventType) {
        if (activeVehicle == null) {
            finishTest(player, "RATCHET_VEHICLE_REFERENCE_LOST");
            return false;
        }
        if (serverPassengerDetached) {
            finishTest(player, "RATCHET_UNEXPECTED_SERVER_PASSENGER_DETACH");
            return false;
        }
        observeUntrustedVehicleRemoval(player);

        double nextDistance = Math.min(RATCHET_BURST_DISTANCE, sentDistance + STEP);
        if (nextDistance - sentDistance <= 1.0E-9) return true;
        Vec3 before = activeVehicle.position();
        Vec3 target = vehicleStart.add(direction.scale(nextDistance));
        activeVehicle.noPhysics = true;
        activeVehicle.setPos(target.x, target.y, target.z);
        player.connection.send(new ServerboundMoveVehiclePacket(
            target,
            activeVehicle.getYRot(),
            activeVehicle.getXRot(),
            true
        ));
        sentDistance = nextDistance;
        sentPackets++;

        JsonObject packet = event(eventType, player);
        packet.addProperty("packet_index", sentPackets);
        packet.addProperty("sent_distance", sentDistance);
        packet.addProperty("absolute_target", true);
        packet.add("vehicle_before", vec(before));
        packet.add("target", vec(target));
        append(packet);
        return true;
    }

    private static void tickRatchetFinalSettle(LocalPlayer player) {
        stateTicks++;
        if (ratchetFinalSettlePackets < RATCHET_FINAL_SETTLE_PACKETS
            && stateTicks % RATCHET_FINAL_SETTLE_INTERVAL_TICKS == 0) {
            if (!sendRatchetAbsoluteTarget(player, "RATCHET_FINAL_SETTLE_PACKET")) return;
            ratchetFinalSettlePackets++;
        }
        if (ratchetFinalSettlePackets >= RATCHET_FINAL_SETTLE_PACKETS) {
            restoreVehiclePhysics();
            state = State.RATCHET_PRE_DISMOUNT;
            stateTicks = 0;
            JsonObject complete = event("RATCHET_FINAL_SETTLE_COMPLETE", player);
            complete.addProperty("settle_packets", ratchetFinalSettlePackets);
            append(complete);
            actionbar(player, "Final target settled. Preparing a normal dismount...");
        }
    }

    private static boolean sendRatchetAbsoluteTarget(LocalPlayer player, String eventType) {
        if (activeVehicle == null) {
            finishTest(player, "RATCHET_VEHICLE_REFERENCE_LOST");
            return false;
        }
        if (serverPassengerDetached) {
            finishTest(player, "RATCHET_UNEXPECTED_SERVER_PASSENGER_DETACH");
            return false;
        }
        observeUntrustedVehicleRemoval(player);

        Vec3 before = activeVehicle.position();
        Vec3 target = vehicleStart.add(direction.scale(RATCHET_TOTAL_DISTANCE));
        activeVehicle.noPhysics = true;
        activeVehicle.setPos(target.x, target.y, target.z);
        player.connection.send(new ServerboundMoveVehiclePacket(
            target,
            activeVehicle.getYRot(),
            activeVehicle.getXRot(),
            true
        ));
        sentDistance = RATCHET_TOTAL_DISTANCE;
        sentPackets++;

        JsonObject packet = event(eventType, player);
        packet.addProperty("packet_index", sentPackets);
        packet.addProperty("sent_distance", sentDistance);
        packet.addProperty("absolute_target", true);
        packet.addProperty("settle_packet_index", ratchetFinalSettlePackets + 1);
        packet.add("vehicle_before", vec(before));
        packet.add("target", vec(target));
        append(packet);
        return true;
    }

    private static void tickRatchetPreDismount(LocalPlayer player) {
        stateTicks++;
        if (serverPassengerDetached) {
            finishTest(player, "RATCHET_UNEXPECTED_SERVER_PASSENGER_DETACH");
            return;
        }
        if (stateTicks >= RATCHET_PRE_DISMOUNT_TICKS) {
            state = State.RATCHET_DISMOUNT_SEND;
            stateTicks = 0;
        }
    }

    private static void sendRatchetDismount(LocalPlayer player) {
        ratchetDismountRequested = true;
        player.connection.send(new ServerboundPlayerInputPacket(
            new Input(false, false, false, false, false, true, false)
        ));
        state = State.RATCHET_DISMOUNT_WAIT;
        stateTicks = 0;
        JsonObject dismount = event("RATCHET_DISMOUNT_REQUESTED", player);
        dismount.addProperty("normal_shift_input", true);
        append(dismount);
        actionbar(player, "Dismount requested. Waiting for the server passenger update...");
    }

    private static void tickRatchetDismountWait(LocalPlayer player) {
        stateTicks++;
        if (stateTicks == 1) {
            player.connection.send(new ServerboundPlayerInputPacket(Input.EMPTY));
            append(event("RATCHET_DISMOUNT_INPUT_RELEASED", player));
        }
        if (serverPassengerDetached) {
            finishTest(player, "RATCHET_DISMOUNT_OBSERVED");
            return;
        }
        if (stateTicks >= RATCHET_DISMOUNT_WAIT_TICKS) {
            finishTest(player, localPassengerGraphSeparated
                ? "RATCHET_DISMOUNT_SERVER_UNCONFIRMED"
                : "RATCHET_DISMOUNT_UNCONFIRMED");
        }
    }

    private static boolean ratchetCorrectionRecoverableState() {
        return testKind == TestKind.RATCHET
            && (state == State.RATCHET_BURST
                || state == State.RATCHET_FINAL_SETTLE
                || state == State.RATCHET_PRE_DISMOUNT
                || state == State.RATCHET_DISMOUNT_SEND
                || state == State.RATCHET_DISMOUNT_WAIT);
    }

    private static void observeUntrustedVehicleRemoval(LocalPlayer player) {
        if (activeVehicle == null || !activeVehicle.isRemoved() || clientVehicleRemovedObserved) return;
        clientVehicleRemovedObserved = true;
        JsonObject event = event("CLIENT_VEHICLE_REMOVED_UNTRUSTED", player);
        event.addProperty("continuing_absolute_route", true);
        event.addProperty("reason", "private lab proved client tracker removal can occur while Sakura remains mounted");
        append(event);
    }

    private static void tickSettling(LocalPlayer player) {
        stateTicks++;
        if (stateTicks >= Math.max(DEFAULT_SETTLE_TICKS, profile.settleTicks())) {
            finishTest(player, "SETTLE_COMPLETE");
        }
    }

    private static void tickRemountWindow(LocalPlayer player) {
        stateTicks++;
        if (stateTicks == 1) {
            message(player, "Rider separated. Do not move. Right-click the SAME vehicle once during the next 6 seconds.");
        }
        if (stateTicks >= MANUAL_REMOUNT_WINDOW_TICKS) {
            finishTest(player, "REMOUNT_WINDOW_EXPIRED");
        }
    }

    private static void tickRemountStable(LocalPlayer player) {
        remountStableTicks++;
        if (remountStableTicks >= REMOUNT_STABLE_TICKS) {
            finishTest(player, "REMOUNT_STABLE");
        }
    }

    private static void observeMountTransition(LocalPlayer player) {
        Entity controlled = controlledVehicle(player);
        boolean mountedSame = controlled != null && controlled == activeVehicle;
        if (wasMounted && !mountedSame) {
            separationCount++;
            if (firstSeparationNanos == 0L) firstSeparationNanos = System.nanoTime();
            restoreVehiclePhysics();
            JsonObject event = event("SEPARATED", player);
            event.addProperty("distance_to_vehicle", activeVehicle == null ? -1.0D : Math.sqrt(player.distanceToSqr(activeVehicle)));
            event.addProperty("vehicle_exists", activeVehicle != null && !activeVehicle.isRemoved());
            append(event);

            if (testKind == TestKind.RATCHET) {
                localPassengerGraphSeparated = true;
                JsonObject interpretation = event("RATCHET_LOCAL_GRAPH_SEPARATION_OBSERVED", player);
                interpretation.addProperty("dismount_requested", ratchetDismountRequested);
                interpretation.addProperty("server_passenger_detached", serverPassengerDetached);
                interpretation.addProperty("continuing_until_server_gate", !serverPassengerDetached);
                append(interpretation);
                if (serverPassengerDetached && !ratchetDismountRequested) {
                    finishTest(player, "RATCHET_UNEXPECTED_SERVER_PASSENGER_DETACH");
                } else if (serverPassengerDetached) {
                    finishTest(player, "RATCHET_DISMOUNT_OBSERVED");
                }
                return;
            }
            if (activeRaftProbe != null) {
                localPassengerGraphSeparated = true;
                finishTest(player, "LOCAL_PASSENGER_GRAPH_SEPARATED");
                return;
            }
            if (remountAccepted) {
                secondSeparation = true;
                finishTest(player, "SECOND_SEPARATION_AFTER_REMOUNT");
                return;
            }
            state = State.REMOUNT_WINDOW;
            stateTicks = 0;
        } else if (!wasMounted && mountedSame) {
            remountCount++;
            remountAccepted = true;
            remountNanos = System.nanoTime();
            state = State.REMOUNT_STABLE;
            stateTicks = 0;
            remountStableTicks = 0;
            JsonObject event = event("REMOUNT_ACCEPTED", player);
            event.addProperty("separation_to_remount_ms", firstSeparationNanos == 0L ? -1.0D :
                (remountNanos - firstSeparationNanos) / 1_000_000.0D);
            append(event);
            message(player, "Manual remount accepted. Stay still for one second while stability is measured.");
        }
        wasMounted = mountedSame;
    }

    private static void silenceAfterCorrection(LocalPlayer player, String text) {
        restoreVehiclePhysics();
        if (testKind == TestKind.RATCHET) {
            state = State.SETTLING;
            stateTicks = 0;
        } else if (state == State.SENDING) {
            state = State.SETTLING;
            stateTicks = 0;
        }
        if (player != null) actionbar(player, text);
    }

    private static void finishTest(LocalPlayer player, String reason) {
        if (!active) return;
        restoreVehiclePhysics();
        Minecraft client = Minecraft.getInstance();
        Vec3 finalPlayer = player == null ? null : player.position();
        Vec3 finalVehicle = activeVehicle == null ? null : activeVehicle.position();
        double playerProgress = projectedProgress(playerStart, finalPlayer, direction);
        double vehicleProgress = projectedProgress(vehicleStart, finalVehicle, direction);
        boolean vehicleExists = activeVehicle != null && !activeVehicle.isRemoved();
        boolean mountedSame = player != null && controlledVehicle(player) == activeVehicle;
        String classification = classifyResult(vehicleProgress, playerProgress, vehicleExists, mountedSame, reason);

        JsonObject result = event("TEST_END", player);
        result.addProperty("test_id", currentTestId);
        result.addProperty("reason", reason);
        result.addProperty("classification", classification);
        result.addProperty("test_kind", testKind == null ? "UNKNOWN" : testKind.name());
        result.addProperty("vehicle_kind", vehicleKind == null ? "UNKNOWN" : vehicleKind.name());
        result.addProperty("mode", mode == null ? "UNKNOWN" : mode.name());
        result.addProperty("profile_index", profileIndex);
        result.addProperty("profile_name", profile == null ? "UNKNOWN" : profile.name());
        result.addProperty("packets_per_tick", profile == null ? 0 : profile.packetsPerTick());
        result.addProperty("planned_distance", profile == null ? 0.0D : profile.distance());
        result.addProperty("raft_profile_selected", activeRaftProbe != null);
        result.addProperty("raft_strategy", activeRaftProbe == null ? "LEGACY" : activeRaftProbe.strategy().name());
        result.addProperty("raft_transport", activeRaftProbe == null ? "LEGACY" : activeRaftProbe.transport().name());
        result.addProperty("raft_step", activeRaftProbe == null ? STEP : activeRaftProbe.step());
        result.addProperty("raft_pace_ticks", activeRaftProbe == null ? 1 : activeRaftProbe.paceTicks());
        result.addProperty("raft_sync_input", activeRaftProbe != null && activeRaftProbe.syncInput());
        result.addProperty("raft_force_on_ground", activeRaftProbe != null && activeRaftProbe.forceOnGround());
        result.addProperty("mount_handshake_stable_ticks", mountHandshakeStableTicks);
        result.addProperty("raft_approach_distance", activeRaftProbe == null ? 0.0D : activeRaftProbe.approachDistance());
        result.addProperty("sent_distance", sentDistance);
        result.addProperty("sent_packets", sentPackets);
        result.addProperty("expected_total_move_packets",
            testKind == TestKind.RATCHET ? RATCHET_EXPECTED_TOTAL_MOVE_PACKETS : 0);
        result.addProperty("exact_move_packet_count",
            testKind == TestKind.RATCHET && sentPackets == RATCHET_EXPECTED_TOTAL_MOVE_PACKETS);
        result.addProperty("player_corrections", playerCorrectionCount);
        result.addProperty("vehicle_corrections", vehicleCorrectionCount);
        result.addProperty("separations", separationCount);
        result.addProperty("remounts", remountCount);
        result.addProperty("remount_accepted", remountAccepted);
        result.addProperty("second_separation", secondSeparation);
        result.addProperty("ratchet_handshake_correction", ratchetHandshakeCorrection);
        result.addProperty("ratchet_final_settle_packets", ratchetFinalSettlePackets);
        result.addProperty("ratchet_dismount_requested", ratchetDismountRequested);
        result.addProperty("client_vehicle_removed_observed", clientVehicleRemovedObserved);
        result.addProperty("local_passenger_graph_separated", localPassengerGraphSeparated);
        result.addProperty("max_recoverable_vehicle_corrections",
            testKind == TestKind.RATCHET ? RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS : 0);
        result.addProperty("passenger_packets", passengerPacketCount);
        result.addProperty("server_passenger_attached", serverPassengerAttached);
        result.addProperty("server_passenger_detached", serverPassengerDetached);
        result.addProperty("server_passenger_detach_observed", serverPassengerDetachObserved);
        result.addProperty("server_passenger_reattach_observed", serverPassengerReattachObserved);
        result.addProperty("evidence_log_healthy", !logWriteFailed);
        result.addProperty("evidence_log_failure", logWriteFailure);
        result.addProperty("authoritative_server_verified", false);
        result.addProperty("vehicle_exists", vehicleExists);
        result.addProperty("mounted_same_vehicle", mountedSame);
        result.addProperty("player_progress", playerProgress);
        result.addProperty("vehicle_progress", vehicleProgress);
        result.addProperty("max_player_progress", maxObservedPlayerProgress);
        result.addProperty("max_vehicle_progress", maxObservedVehicleProgress);
        result.addProperty("last_player_correction_progress", lastPlayerCorrectionProgress);
        result.addProperty("last_vehicle_correction_progress", lastVehicleCorrectionProgress);
        result.addProperty("elapsed_ms", (System.nanoTime() - testStartNanos) / 1_000_000.0D);
        result.add("player_final", vec(finalPlayer));
        result.add("vehicle_final", vec(finalVehicle));
        result.add("environment_final", environment(client, player, activeVehicle));
        append(result);
        flushLog();
        if (logWriteFailed) {
            classification = "EVIDENCE_LOG_FAILURE";
            result.addProperty("classification", classification);
            result.addProperty("evidence_log_healthy", false);
            result.addProperty("evidence_log_failure", logWriteFailure);
        }
        completedTests.add(result.deepCopy());
        writeSummary(client, player);
        if (logWriteFailed) {
            classification = "EVIDENCE_LOG_FAILURE";
            result.addProperty("classification", classification);
            result.addProperty("evidence_log_healthy", false);
            result.addProperty("evidence_log_failure", logWriteFailure);
            completedTests.set(completedTests.size() - 1, result.deepCopy());
        }

        if (player != null) {
            message(player, String.format(Locale.ROOT,
                "%s | vehicle %.2f | player %.2f | corrections P%d/V%d | separated %d | remount %s",
                classification, vehicleProgress, playerProgress,
                playerCorrectionCount, vehicleCorrectionCount, separationCount,
                remountAccepted ? "YES" : "NO"));
            if (activeRaftProbe != null) {
                message(player, "Raft result is CLIENT-OBSERVED only. Confirm server snapshot, far-side witness, then normal sneak dismount.");
            } else {
                message(player, "Next P press advances to the next profile for this vehicle + direction mode.");
            }
            if (logWriteFailed) {
                message(player, "Evidence session failed and was closed: " + logWriteFailure);
            }
        }

        active = false;
        state = State.IDLE;
        activeVehicle = null;
        activeVehicleUuid = null;
        testKind = null;
        vehicleKind = null;
        mode = null;
        profile = null;
        activeRaftProbe = null;
        direction = null;
        playerStart = null;
        vehicleStart = null;
        currentTestId = null;
        if (logWriteFailed) closeSession();
    }

    private static String classifyResult(double vehicleProgress, double playerProgress,
                                         boolean vehicleExists, boolean mountedSame, String reason) {
        if (logWriteFailed || reason.equals("LOG_IO_FAILURE")) return "EVIDENCE_LOG_FAILURE";
        if (reason.equals("SERVER_PASSENGER_REATTACHED_AFTER_DETACH")) return "SERVER_PASSENGER_REATTACHED_AFTER_DETACH";
        if (reason.equals("SERVER_PASSENGER_DETACH_OBSERVED")) return "SERVER_PASSENGER_DETACHED_DURING_PROBE";
        if (reason.equals("ABORTED")) return "ABORTED";
        if (testKind == TestKind.RATCHET) {
            if (!ratchetHandshakeCorrection) return "RATCHET_NO_CORRECTION_HANDSHAKE";
            if (vehicleCorrectionCount > RATCHET_MAX_RECOVERABLE_VEHICLE_CORRECTIONS) {
                return "RATCHET_CORRECTION_LIMIT_EXCEEDED";
            }
            if (serverPassengerDetached && !ratchetDismountRequested) {
                return "RATCHET_UNEXPECTED_SERVER_PASSENGER_DETACH";
            }
            boolean fullRouteSent = sentDistance + 1.0E-9 >= RATCHET_TOTAL_DISTANCE
                && ratchetFinalSettlePackets >= RATCHET_FINAL_SETTLE_PACKETS
                && sentPackets == RATCHET_EXPECTED_TOTAL_MOVE_PACKETS;
            if (fullRouteSent && ratchetDismountRequested && serverPassengerDetached) {
                return "RATCHET_FULL_PROFILE_DISMOUNTED_SERVER_WITNESS_REQUIRED";
            }
            if (fullRouteSent && ratchetDismountRequested && localPassengerGraphSeparated) {
                return "RATCHET_FULL_PROFILE_DISMOUNT_LOCAL_ONLY_SERVER_UNCONFIRMED";
            }
            if (fullRouteSent && ratchetDismountRequested) {
                return "RATCHET_FULL_PROFILE_DISMOUNT_UNCONFIRMED";
            }
            if (fullRouteSent) {
                return "RATCHET_FULL_PROFILE_SENT_SERVER_WITNESS_REQUIRED";
            }
            if (clientVehicleRemovedObserved || !vehicleExists) {
                return "RATCHET_CLIENT_TRACKER_REMOVED_BEFORE_PROFILE_COMPLETE";
            }
            if (localPassengerGraphSeparated || !mountedSame) {
                return "RATCHET_LOCAL_GRAPH_SEPARATED_BEFORE_PROFILE_COMPLETE";
            }
            return "RATCHET_PROFILE_INCOMPLETE";
        }
        if (!vehicleExists) return "VEHICLE_REMOVED";
        if (secondSeparation) return "REMOUNT_ACCEPTED_THEN_SEPARATED";
        if (remountAccepted && mountedSame) return "REMOUNT_ACCEPTED_STABLE";
        if (separationCount > 0 && !remountAccepted) return "SEPARATED_NO_REMOUNT";
        if (vehicleCorrectionCount > 0 && lastVehicleCorrectionProgress < MIN_RETAINED_PROGRESS)
            return "VEHICLE_ROLLBACK";
        if (playerCorrectionCount > 0 && vehicleProgress >= MIN_RETAINED_PROGRESS)
            return "VEHICLE_RETAINED_WITH_PLAYER_SYNC";
        if (vehicleCorrectionCount > 0 && vehicleProgress >= MIN_RETAINED_PROGRESS)
            return "VEHICLE_RETAINED_WITH_SERVER_SYNC";
        if (vehicleProgress >= MIN_RETAINED_PROGRESS && playerProgress >= MIN_RETAINED_PROGRESS)
            return "CLIENT_OBSERVED_RETAINED_UNVERIFIED";
        return "NO_RETAINED_PROGRESS";
    }

    private static void recordTick(Minecraft client, LocalPlayer player) {
        JsonObject tick = event("TICK", player);
        tick.addProperty("state_tick", stateTicks);
        tick.addProperty("mounted_same_vehicle", controlledVehicle(player) == activeVehicle);
        tick.addProperty("distance_to_vehicle", activeVehicle == null ? -1.0D : Math.sqrt(player.distanceToSqr(activeVehicle)));
        tick.addProperty("player_progress", projectedProgress(playerStart, player.position(), direction));
        tick.addProperty("vehicle_progress", projectedProgress(vehicleStart,
            activeVehicle == null ? null : activeVehicle.position(), direction));
        tick.add("environment", environment(client, player, activeVehicle));
        append(tick);
    }

    private static JsonObject environment(Minecraft client, LocalPlayer player, Entity vehicle) {
        JsonObject env = new JsonObject();
        if (client == null || client.level == null) return env;
        Entity subject = vehicle != null ? vehicle : player;
        if (subject == null) return env;
        BlockPos center = BlockPos.containing(subject.position());
        env.addProperty("dimension", client.level.dimension().identifier().toString());
        env.addProperty("chunk_loaded", client.level.hasChunkAt(center));
        env.addProperty("collision_free", client.level.noCollision(subject, subject.getBoundingBox().deflate(0.01D)));
        env.addProperty("in_water", subject.isInWater());
        env.addProperty("in_lava", subject.isInLava());
        env.addProperty("on_ground", subject.onGround());
        env.addProperty("center_block", client.level.getBlockState(center).getBlock().toString());
        env.addProperty("below_block", client.level.getBlockState(center.below()).getBlock().toString());
        env.addProperty("above_block", client.level.getBlockState(center.above()).getBlock().toString());
        env.addProperty("center_fluid", client.level.getFluidState(center).toString());
        env.add("velocity", vec(subject.getDeltaMovement()));
        env.add("bounding_box", box(subject));
        return env;
    }

    private static JsonObject event(String type, LocalPlayer player) {
        JsonObject event = new JsonObject();
        event.addProperty("timestamp", Instant.now().toString());
        event.addProperty("nano_time", System.nanoTime());
        event.addProperty("event_sequence", EVENT_SEQUENCE.incrementAndGet());
        event.addProperty("client_tick", clientTick);
        event.addProperty("event", type);
        event.addProperty("session_id", sessionId == null ? "" : sessionId);
        event.addProperty("test_id", currentTestId == null ? "" : currentTestId);
        event.addProperty("state", state.name());
        event.add("player", entity(player));
        event.add("vehicle", entity(activeVehicle));
        return event;
    }

    private static void addPassengerPacket(JsonObject event, ClientboundSetPassengersPacket packet,
                                           LocalPlayer player) {
        event.addProperty("packet_vehicle_id", packet.getVehicle());
        event.addProperty("active_vehicle_id", activeVehicle == null ? -1 : activeVehicle.getId());
        event.addProperty("active_vehicle_uuid", activeVehicleUuid == null ? "" : activeVehicleUuid.toString());
        event.addProperty("player_id", player == null ? -1 : player.getId());
        JsonArray passengerIds = new JsonArray();
        for (int passengerId : packet.getPassengers()) passengerIds.add(passengerId);
        event.add("packet_passenger_ids", passengerIds);
        Minecraft client = Minecraft.getInstance();
        Entity packetVehicle = client.level == null ? null : client.level.getEntity(packet.getVehicle());
        event.add("packet_vehicle_client_state", entity(packetVehicle));
    }

    private static boolean contains(int[] values, int expected) {
        for (int value : values) {
            if (value == expected) return true;
        }
        return false;
    }

    private static JsonObject entity(Entity entity) {
        JsonObject object = new JsonObject();
        if (entity == null) return object;
        object.addProperty("id", entity.getId());
        object.addProperty("uuid", entity.getUUID().toString());
        object.addProperty("type", entity.getType().toString());
        object.add("position", vec(entity.position()));
        object.add("velocity", vec(entity.getDeltaMovement()));
        object.addProperty("removed", entity.isRemoved());
        object.addProperty("on_ground", entity.onGround());
        object.addProperty("no_physics", entity.noPhysics);
        object.addProperty("passenger_count", entity.getPassengers().size());
        object.add("bounding_box", box(entity));
        return object;
    }

    private static JsonObject box(Entity entity) {
        JsonObject object = new JsonObject();
        if (entity == null) return object;
        var box = entity.getBoundingBox();
        object.addProperty("min_x", box.minX);
        object.addProperty("min_y", box.minY);
        object.addProperty("min_z", box.minZ);
        object.addProperty("max_x", box.maxX);
        object.addProperty("max_y", box.maxY);
        object.addProperty("max_z", box.maxZ);
        return object;
    }

    private static JsonObject vec(Vec3 vector) {
        JsonObject object = new JsonObject();
        if (vector == null) return object;
        object.addProperty("x", vector.x);
        object.addProperty("y", vector.y);
        object.addProperty("z", vector.z);
        return object;
    }

    private static boolean ensureSession(Minecraft client, LocalPlayer player) {
        if (writer != null && !logWriteFailed) return true;
        if (writer != null) {
            message(player, "Previous evidence session was unhealthy and has been closed: " + logWriteFailure);
            closeSession();
        }
        try {
            logWriteFailed = false;
            logWriteFailure = "";
            EVENT_SEQUENCE.set(0L);
            while (completedTests.size() > 0) completedTests.remove(completedTests.size() - 1);
            sessionDirectory = FabricLoader.getInstance().getConfigDir().resolve("phaselab-verifier");
            Files.createDirectories(sessionDirectory);
            sessionId = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss-SSS", Locale.ROOT)
                .withZone(ZoneOffset.UTC).format(Instant.now());
            sessionJsonl = sessionDirectory.resolve("session-" + sessionId + ".jsonl");
            summaryJson = sessionDirectory.resolve("summary-" + sessionId + ".json");
            writer = Files.newBufferedWriter(sessionJsonl, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);

            JsonObject start = event("SESSION_START", player);
            start.addProperty("mod_version", MOD_VERSION);
            start.addProperty("minecraft", "1.21.11");
            start.addProperty("server_address", serverAddress(client));
            start.addProperty("server_brand", "unavailable");
            start.addProperty("player_name", player.getGameProfile().name());
            start.addProperty("player_uuid", player.getUUID().toString());
            start.addProperty("latency_ms", latency(player));
            append(start);
            writeSummary(client, player);
            if (logWriteFailed) {
                message(player, "Verifier evidence storage failed: " + logWriteFailure);
                closeSession();
                return false;
            }
            return true;
        } catch (IOException exception) {
            message(player, "Could not create verifier log: " + exception.getMessage());
            closeSession();
            return false;
        }
    }

    private static boolean authorizeTarget(Minecraft client, LocalPlayer player) {
        if (client == null || client.getCurrentServer() == null) return true;
        String current = normalizeTarget(client.getCurrentServer().ip);
        if (current.equals("localhost") || current.startsWith("localhost:")
            || current.equals("127.0.0.1") || current.startsWith("127.0.0.1:")
            || current.equals("[::1]") || current.startsWith("[::1]:")) {
            return true;
        }

        Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab-verifier");
        Path targets = directory.resolve(AUTHORIZED_TARGETS_FILE);
        try {
            Files.createDirectories(directory);
            if (!Files.exists(targets)) {
                Files.writeString(targets,
                    "# One explicitly authorized server address per line.\n"
                        + "# Use the exact address shown in the multiplayer server list, including port when present.\n",
                    StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            }
            for (String line : Files.readAllLines(targets, StandardCharsets.UTF_8)) {
                String candidate = normalizeTarget(line);
                if (!candidate.isEmpty() && !candidate.startsWith("#") && candidate.equals(current)) {
                    return true;
                }
            }
            message(player, "Target is not authorized. Add the exact address '" + current + "' to " + targets + ".");
            return false;
        } catch (IOException exception) {
            message(player, "Could not verify authorized target list: " + exception.getMessage());
            return false;
        }
    }

    private static String normalizeTarget(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    private static void append(JsonObject event) {
        if (writer == null || event == null) return;
        try {
            writer.write(GSON.toJson(event));
            writer.newLine();
        } catch (IOException exception) {
            markLogFailure("append: " + exception.getMessage());
        }
    }

    private static void flushLog() {
        if (writer == null) return;
        try {
            writer.flush();
        } catch (IOException exception) {
            markLogFailure("flush: " + exception.getMessage());
        }
    }

    private static void writeSummary(Minecraft client, LocalPlayer player) {
        if (summaryJson == null) return;
        JsonObject summary = new JsonObject();
        summary.addProperty("session_id", sessionId);
        summary.addProperty("mod_version", MOD_VERSION);
        summary.addProperty("minecraft", "1.21.11");
        summary.addProperty("server_address", serverAddress(client));
        summary.addProperty("server_brand", "unavailable");
        summary.addProperty("player", player == null ? "" : player.getGameProfile().name());
        summary.addProperty("latency_ms", player == null ? -1 : latency(player));
        summary.add("tests", completedTests);
        JsonObject ladders = new JsonObject();
        for (var entry : profileIndices.entrySet()) ladders.addProperty(entry.getKey(), entry.getValue());
        summary.add("next_profile_indices", ladders);
        summary.addProperty("jsonl", sessionJsonl == null ? "" : sessionJsonl.toString());
        try {
            Files.writeString(summaryJson, GSON.toJson(summary), StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        } catch (IOException exception) {
            markLogFailure("summary: " + exception.getMessage());
        }
    }

    private static void markLogFailure(String failure) {
        logWriteFailed = true;
        if (logWriteFailure.isBlank()) {
            logWriteFailure = failure == null ? "unknown I/O failure" : failure;
        }
    }

    private static void closeSession() {
        if (writer != null) {
            try { writer.close(); } catch (IOException ignored) { }
        }
        writer = null;
        sessionDirectory = null;
        sessionJsonl = null;
        summaryJson = null;
        sessionId = null;
    }

    private static int latency(LocalPlayer player) {
        try {
            PlayerInfo info = player.connection.getPlayerInfo(player.getUUID());
            return info == null ? -1 : info.getLatency();
        } catch (RuntimeException ignored) {
            return -1;
        }
    }

    private static String serverAddress(Minecraft client) {
        return client == null || client.getCurrentServer() == null
            ? "singleplayer"
            : client.getCurrentServer().ip;
    }

    private static boolean isBambooRaft(Entity entity) {
        return entity != null
            && BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString()
                .equals("minecraft:bamboo_raft");
    }

    private static List<Profile> profiles(VehicleKind kind, Mode mode) {
        if (kind == VehicleKind.BOAT) return mode == Mode.DOWN ? BOAT_DOWN_PROFILES : BOAT_FORWARD_PROFILES;
        return mode == Mode.DOWN ? HORSE_DOWN_PROFILES : HORSE_FORWARD_PROFILES;
    }

    private static VehicleKind classifyVehicle(Entity entity) {
        if (entity instanceof AbstractBoat) return VehicleKind.BOAT;
        if (entity instanceof AbstractHorse) return VehicleKind.HORSE;
        return null;
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        if (player == null) return null;
        Entity vehicle = player.getVehicle();
        return vehicle != null && vehicle.getControllingPassenger() == player ? vehicle : null;
    }

    private static Vec3 snappedCardinal(Vec3 look) {
        if (Math.abs(look.x) >= Math.abs(look.z)) return new Vec3(look.x >= 0.0D ? 1.0D : -1.0D, 0.0D, 0.0D);
        return new Vec3(0.0D, 0.0D, look.z >= 0.0D ? 1.0D : -1.0D);
    }

    private static double projectedProgress(Vec3 start, Vec3 current, Vec3 vector) {
        if (start == null || current == null || vector == null) return 0.0D;
        return current.subtract(start).dot(vector);
    }

    private static void restoreVehiclePhysics() {
        if (activeVehicle != null && !activeVehicle.isRemoved()) activeVehicle.noPhysics = originalVehicleNoPhysics;
    }

    private static void message(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab Verify] " + text), false);
    }

    private static void actionbar(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab Verify] " + text), true);
    }
}
