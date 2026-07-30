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
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ServerboundMoveVehiclePacket;
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
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * Client-only bounded verifier for authorized private clone testing.
 *
 * Each press sends exactly one small vehicle profile, then becomes silent and
 * records the server response. If rider and vehicle separate, the verifier
 * opens a manual remount window but never sends an automatic interaction.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().setPrettyPrinting().create();
    private static final double STEP = 0.25D;
    private static final float DOWN_PITCH_THRESHOLD = 55.0F;
    private static final int DEFAULT_SETTLE_TICKS = 40;
    private static final int MANUAL_REMOUNT_WINDOW_TICKS = 120;
    private static final int REMOUNT_STABLE_TICKS = 20;
    private static final double MIN_RETAINED_PROGRESS = 0.125D;

    private record Profile(String name, int packetsPerTick, double distance, int settleTicks) {}

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
        SENDING,
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
    private static KeyMapping abortKey;

    private static final Map<String, Integer> profileIndices = new HashMap<>();
    private static JsonArray completedTests = new JsonArray();

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
    private static boolean wasMounted;
    private static boolean remountAccepted;
    private static boolean secondSeparation;
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
        silenceAfterCorrection(player, "Player correction received. Verifier is now silent.");
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
        silenceAfterCorrection(player, "Vehicle correction received. Verifier is now silent.");
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
            message(player, "Verifier 5.2 loaded. Mount boat/horse, face forward or look down, press P. Each press runs ONE bounded profile.");
        }

        while (testKey.consumeClick()) {
            if (active) {
                message(player, "A verifier test is already running. Press O to abort it.");
            } else {
                startTest(client, player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) finishTest(player, "ABORTED");
        }

        if (!active) return;
        recordTick(client, player);
        observeMountTransition(player);
        if (!active) return;

        maxObservedVehicleProgress = Math.max(maxObservedVehicleProgress,
            projectedProgress(vehicleStart, activeVehicle == null ? null : activeVehicle.position(), direction));
        maxObservedPlayerProgress = Math.max(maxObservedPlayerProgress,
            projectedProgress(playerStart, player.position(), direction));

        switch (state) {
            case SENDING -> sendPackets(player);
            case SETTLING -> tickSettling(player);
            case REMOUNT_WINDOW -> tickRemountWindow(player);
            case REMOUNT_STABLE -> tickRemountStable(player);
            case IDLE -> { }
        }
    }

    private static void startTest(Minecraft client, LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        VehicleKind kind = classifyVehicle(vehicle);
        if (vehicle == null || kind == null) {
            message(player, "Mount and control a normal boat or tamed horse first.");
            return;
        }

        ensureSession(client, player);
        vehicleKind = kind;
        mode = player.getXRot() >= DOWN_PITCH_THRESHOLD ? Mode.DOWN : Mode.FORWARD;
        direction = mode == Mode.DOWN ? new Vec3(0.0D, -1.0D, 0.0D) : snappedCardinal(player.getLookAngle());
        List<Profile> profiles = profiles(kind, mode);
        String ladderKey = kind.name() + ":" + mode.name();
        profileIndex = profileIndices.getOrDefault(ladderKey, 0) % profiles.size();
        profile = profiles.get(profileIndex);
        profileIndices.put(ladderKey, (profileIndex + 1) % profiles.size());

        active = true;
        state = State.SENDING;
        stateTicks = 0;
        sentPackets = 0;
        sentDistance = 0.0D;
        playerCorrectionCount = 0;
        vehicleCorrectionCount = 0;
        separationCount = 0;
        remountCount = 0;
        remountStableTicks = 0;
        remountAccepted = false;
        secondSeparation = false;
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

    private static void sendPackets(LocalPlayer player) {
        if (activeVehicle == null || activeVehicle.isRemoved()) {
            finishTest(player, "VEHICLE_REMOVED_DURING_SEND");
            return;
        }
        int sentThisTick = 0;
        while (sentThisTick < profile.packetsPerTick() && sentDistance + 1.0E-9 < profile.distance()) {
            double step = Math.min(STEP, profile.distance() - sentDistance);
            Vec3 before = activeVehicle.position();
            Vec3 target = before.add(direction.scale(step));
            activeVehicle.noPhysics = true;
            activeVehicle.setPos(target.x, target.y, target.z);
            player.connection.send(new ServerboundMoveVehiclePacket(
                target,
                activeVehicle.getYRot(),
                activeVehicle.getXRot(),
                activeVehicle.onGround()
            ));
            sentDistance += step;
            sentPackets++;
            sentThisTick++;

            JsonObject packet = event("PACKET_SEND", player);
            packet.addProperty("packet_index", sentPackets);
            packet.addProperty("sent_distance", sentDistance);
            packet.add("vehicle_before", vec(before));
            packet.add("target", vec(target));
            packet.add("environment", environment(Minecraft.getInstance(), player, activeVehicle));
            append(packet);
        }

        if (sentDistance + 1.0E-9 >= profile.distance()) {
            restoreVehiclePhysics();
            state = State.SETTLING;
            stateTicks = 0;
            actionbar(player, "Pulse sent. Waiting silently for corrections or separation...");
            append(event("SEND_COMPLETE", player));
        }
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
        if (state == State.SENDING) {
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
        result.addProperty("vehicle_kind", vehicleKind == null ? "UNKNOWN" : vehicleKind.name());
        result.addProperty("mode", mode == null ? "UNKNOWN" : mode.name());
        result.addProperty("profile_index", profileIndex);
        result.addProperty("profile_name", profile == null ? "UNKNOWN" : profile.name());
        result.addProperty("packets_per_tick", profile == null ? 0 : profile.packetsPerTick());
        result.addProperty("planned_distance", profile == null ? 0.0D : profile.distance());
        result.addProperty("sent_distance", sentDistance);
        result.addProperty("sent_packets", sentPackets);
        result.addProperty("player_corrections", playerCorrectionCount);
        result.addProperty("vehicle_corrections", vehicleCorrectionCount);
        result.addProperty("separations", separationCount);
        result.addProperty("remounts", remountCount);
        result.addProperty("remount_accepted", remountAccepted);
        result.addProperty("second_separation", secondSeparation);
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
        completedTests.add(result.deepCopy());
        writeSummary(client, player);

        if (player != null) {
            message(player, String.format(Locale.ROOT,
                "%s | vehicle %.2f | player %.2f | corrections P%d/V%d | separated %d | remount %s",
                classification, vehicleProgress, playerProgress,
                playerCorrectionCount, vehicleCorrectionCount, separationCount,
                remountAccepted ? "YES" : "NO"));
            message(player, "Next P press advances to the next profile for this vehicle + direction mode.");
            if (sessionJsonl != null && summaryJson != null) {
                message(player, "Logs: " + sessionJsonl);
                message(player, "Summary: " + summaryJson);
            }
        }

        active = false;
        state = State.IDLE;
        activeVehicle = null;
        activeVehicleUuid = null;
        vehicleKind = null;
        mode = null;
        profile = null;
        direction = null;
        playerStart = null;
        vehicleStart = null;
        currentTestId = null;
    }

    private static String classifyResult(double vehicleProgress, double playerProgress,
                                         boolean vehicleExists, boolean mountedSame, String reason) {
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
        if (reason.equals("ABORTED")) return "ABORTED";
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
        env.addProperty("dimension", client.level.dimension().toString());
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
        event.addProperty("client_tick", clientTick);
        event.addProperty("event", type);
        event.addProperty("session_id", sessionId == null ? "" : sessionId);
        event.addProperty("test_id", currentTestId == null ? "" : currentTestId);
        event.addProperty("state", state.name());
        event.add("player", entity(player));
        event.add("vehicle", entity(activeVehicle));
        return event;
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

    private static void ensureSession(Minecraft client, LocalPlayer player) {
        if (writer != null) return;
        try {
            sessionDirectory = FabricLoader.getInstance().getConfigDir().resolve("phaselab-verifier");
            Files.createDirectories(sessionDirectory);
            completedTests = new JsonArray();
            profileIndices.clear();
            testSequence = 0;
            sessionId = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.ROOT)
                .withZone(ZoneOffset.UTC).format(Instant.now());
            sessionJsonl = sessionDirectory.resolve("session-" + sessionId + ".jsonl");
            summaryJson = sessionDirectory.resolve("summary-" + sessionId + ".json");
            writer = Files.newBufferedWriter(sessionJsonl, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);

            JsonObject start = event("SESSION_START", player);
            start.addProperty("mod_version", "5.2.0");
            start.addProperty("minecraft", "1.21.11");
            start.addProperty("server_address", client.getCurrentServer() == null ? "singleplayer" : client.getCurrentServer().ip);
                        start.addProperty("player_name", player.getGameProfile().name());
            start.addProperty("player_uuid", player.getUUID().toString());
            start.addProperty("latency_ms", latency(player));
            append(start);
            writeSummary(client, player);
        } catch (IOException exception) {
            message(player, "Could not create verifier log: " + exception.getMessage());
            closeSession();
        }
    }

    private static void append(JsonObject event) {
        if (writer == null || event == null) return;
        try {
            writer.write(GSON.toJson(event));
            writer.newLine();
            writer.flush();
        } catch (IOException ignored) {
        }
    }

    private static void writeSummary(Minecraft client, LocalPlayer player) {
        if (summaryJson == null) return;
        JsonObject summary = new JsonObject();
        summary.addProperty("session_id", sessionId);
        summary.addProperty("mod_version", "5.2.0");
        summary.addProperty("minecraft", "1.21.11");
        summary.addProperty("server_address", client == null || client.getCurrentServer() == null ? "singleplayer" : client.getCurrentServer().ip);
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
        } catch (IOException ignored) {
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

    private static List<Profile> profiles(VehicleKind kind, Mode mode) {
        if (kind == VehicleKind.BOAT) return mode == Mode.DOWN ? BOAT_DOWN_PROFILES : BOAT_FORWARD_PROFILES;
        return mode == Mode.DOWN ? HORSE_DOWN_PROFILES : HORSE_FORWARD_PROFILES;
    }

    private static VehicleKind classifyVehicle(Entity entity) {
        if (entity == null) return null;
        String type = entity.getType().toString().toLowerCase(Locale.ROOT);
        if (type.contains("boat")) return VehicleKind.BOAT;
        if (type.contains("horse")) return VehicleKind.HORSE;
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
