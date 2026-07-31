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
import java.util.Set;
import java.util.UUID;

/**
 * Loopback-only player-side reproducer for the verified PhaseLab one-plane
 * vehicle validation differential. It is intentionally bounded, fixed-profile,
 * non-adaptive, and hard-locked to the isolated PhaseLab runtimes.
 */
public final class PurpleHandoffClient implements ClientModInitializer {
    private static final String VERSION = "8.0.0-purple-handoff";
    private static final String CONFIG_DIRECTORY = "phaselab-purple-handoff";
    private static final Set<String> ALLOWED = Set.of(
        "127.0.0.1:25568", "localhost:25568", "[::1]:25568", "::1:25568",
        "127.0.0.1:25569", "localhost:25569", "[::1]:25569", "::1:25569"
    );
    private static final int ARM_TICKS = 10;
    private static final int OBSERVE_TICKS = 40;
    private static final double STEP = 0.25D;
    private static final double TOTAL = 2.15D;

    private enum State { ARMING, SENDING, OBSERVING }
    private enum Verdict {
        LAB_REPRODUCED_CANDIDATE,
        GUARD_BLOCKED,
        STACK_DETACHED,
        CORRECTED_OR_PARTIAL,
        NO_RESULT
    }

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "purple_handoff")
    );

    private static KeyMapping runKey;
    private static KeyMapping abortKey;
    private static boolean readyShown;
    private static boolean active;
    private static State state;
    private static int ticksRemaining;
    private static long clientTick;
    private static long runStartNanos;

    private static Entity vehicle;
    private static UUID vehicleUuid;
    private static int vehicleId = -1;
    private static Vec3 direction;
    private static Vec3 playerStart;
    private static Vec3 vehicleStart;
    private static Vec3 lastTarget;
    private static double sentDistance;
    private static int packetsSent;
    private static int playerCorrections;
    private static int vehicleCorrections;
    private static int detaches;
    private static int attaches;
    private static long firstCorrectionNanos;
    private static long firstDetachNanos;
    private static long firstAttachNanos;

    private static BufferedWriter csv;
    private static Path csvPath;

    @Override
    public void onInitializeClient() {
        runKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.purple_run",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.purple_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(PurpleHandoffClient::tick);
    }

    public static void onServerPlayerCorrectionApplied() {
        if (!active) return;
        playerCorrections++;
        if (firstCorrectionNanos == 0L) firstCorrectionNanos = System.nanoTime();
        Minecraft mc = Minecraft.getInstance();
        log("SERVER_PLAYER_CORRECTION", mc.player);
    }

    public static void onServerVehicleCorrectionApplied() {
        if (!active) return;
        vehicleCorrections++;
        if (firstCorrectionNanos == 0L) firstCorrectionNanos = System.nanoTime();
        Minecraft mc = Minecraft.getInstance();
        recoverVehicle(mc, mc.player);
        log("SERVER_VEHICLE_CORRECTION", mc.player);
    }

    public static void onServerPassengersApplied(ClientboundSetPassengersPacket packet) {
        if (!active) return;
        Minecraft mc = Minecraft.getInstance();
        LocalPlayer player = mc.player;
        if (player == null) return;
        int tracked = vehicle == null ? vehicleId : vehicle.getId();
        if (packet.getVehicle() != tracked) return;

        boolean contains = false;
        for (int id : packet.getPassengers()) {
            if (id == player.getId()) {
                contains = true;
                break;
            }
        }
        if (contains) {
            attaches++;
            if (firstAttachNanos == 0L) firstAttachNanos = System.nanoTime();
            recoverVehicle(mc, player);
            log("SERVER_PASSENGER_ATTACH", player);
        } else {
            detaches++;
            if (firstDetachNanos == 0L) firstDetachNanos = System.nanoTime();
            log("SERVER_PASSENGER_DETACH", player);
            if (state != State.OBSERVING) beginObservation(player, "Server detached the rider. Capturing final state.");
        }
    }

    private static void tick(Minecraft mc) {
        LocalPlayer player = mc.player;
        if (player == null || mc.level == null) {
            readyShown = false;
            if (active || csv != null) stop(null, "WORLD_LEFT");
            return;
        }
        clientTick++;

        if (!readyShown) {
            readyShown = true;
            message(player, "Purple Handoff " + VERSION + " loaded. P runs the fixed loopback reproducer; O aborts.");
            message(player, "Hard lock: 127.0.0.1 ports 25568 and 25569 only.");
        }

        while (runKey.consumeClick()) {
            if (active) stop(player, "STOPPED_MANUALLY");
            else start(mc, player);
        }
        while (abortKey.consumeClick()) {
            if (active) stop(player, "EMERGENCY_ABORT");
        }
        if (!active) return;
        if (!isAllowed(mc)) {
            stop(player, "ENDPOINT_LOCK_CHANGED");
            return;
        }

        recoverVehicle(mc, player);
        switch (state) {
            case ARMING -> tickArming(player);
            case SENDING -> tickSending(player);
            case OBSERVING -> tickObserving(player);
        }
    }

    private static void start(Minecraft mc, LocalPlayer player) {
        if (!isAllowed(mc)) {
            message(player, "Rejected endpoint " + serverAddress(mc) + ". This build only runs on loopback 25568/25569.");
            return;
        }
        Entity mounted = controlledVehicle(player);
        if (mounted == null || !isBoatOrRaft(mounted)) {
            message(player, "Mount and control a boat or raft first.");
            return;
        }

        active = true;
        state = State.ARMING;
        ticksRemaining = ARM_TICKS;
        runStartNanos = System.nanoTime();
        vehicle = mounted;
        vehicleUuid = mounted.getUUID();
        vehicleId = mounted.getId();
        direction = nearestCardinal(player.getYRot());
        playerStart = player.position();
        vehicleStart = mounted.position();
        lastTarget = vehicleStart;
        sentDistance = 0.0D;
        packetsSent = 0;
        playerCorrections = 0;
        vehicleCorrections = 0;
        detaches = 0;
        attaches = 0;
        firstCorrectionNanos = 0L;
        firstDetachNanos = 0L;
        firstAttachNanos = 0L;
        openLog(mc);
        log("START", player);
        message(player, "Fixed profile armed: 0.25 blocks per tick, 2.15 total, no remount loop, no adaptation.");
    }

    private static void tickArming(LocalPlayer player) {
        if (controlledVehicle(player) != vehicle) {
            stop(player, "MOUNT_UNSTABLE_DURING_ARMING");
            return;
        }
        ticksRemaining--;
        actionbar(player, "Stable mount " + (ARM_TICKS - Math.max(0, ticksRemaining)) + "/" + ARM_TICKS);
        if (ticksRemaining <= 0) {
            state = State.SENDING;
            log("ARMING_COMPLETE", player);
        }
    }

    private static void tickSending(LocalPlayer player) {
        if (vehicle == null || controlledVehicle(player) != vehicle) {
            beginObservation(player, "Mount separated before the fixed packet sequence completed.");
            return;
        }
        double remaining = TOTAL - sentDistance;
        if (remaining <= 1.0E-9D) {
            beginObservation(player, "Fixed packet sequence completed. Observing for two seconds.");
            return;
        }
        double delta = Math.min(STEP, remaining);
        Vec3 target = vehicleStart.add(direction.scale(sentDistance + delta));
        player.connection.send(new ServerboundMoveVehiclePacket(
            target,
            vehicle.getYRot(),
            vehicle.getXRot(),
            vehicle.onGround()
        ));
        lastTarget = target;
        sentDistance += delta;
        packetsSent++;
        log("SEND_VEHICLE_STEP", player);
        actionbar(player, "Packet " + packetsSent + " | sent " + fmt(sentDistance) + "/" + fmt(TOTAL));
        if (sentDistance >= TOTAL - 1.0E-9D) {
            beginObservation(player, "Fixed packet sequence completed. Observing for two seconds.");
        }
    }

    private static void beginObservation(LocalPlayer player, String reason) {
        if (state == State.OBSERVING) return;
        state = State.OBSERVING;
        ticksRemaining = OBSERVE_TICKS;
        log("OBSERVATION_BEGIN", player);
        message(player, reason);
    }

    private static void tickObserving(LocalPlayer player) {
        ticksRemaining--;
        double pp = projected(playerStart, player.position(), direction);
        double vp = projected(vehicleStart, vehiclePosition(), direction);
        boolean mounted = controlledVehicle(player) == vehicle;
        actionbar(player, "Observe " + (OBSERVE_TICKS - Math.max(0, ticksRemaining)) + "/" + OBSERVE_TICKS
            + " | player " + fmt(pp) + " | vehicle " + fmt(vp) + " | mounted " + mounted);
        log("OBSERVE", player);
        if (ticksRemaining <= 0) finish(player);
    }

    private static void finish(LocalPlayer player) {
        double pp = projected(playerStart, player.position(), direction);
        double vp = projected(vehicleStart, vehiclePosition(), direction);
        boolean mounted = controlledVehicle(player) == vehicle;
        Verdict verdict;
        if (mounted && pp >= 1.90D && vp >= 1.90D && detaches == 0 && playerCorrections + vehicleCorrections == 0) {
            verdict = Verdict.LAB_REPRODUCED_CANDIDATE;
        } else if (detaches > 0) {
            verdict = Verdict.STACK_DETACHED;
        } else if (pp < 0.55D && vp < 0.55D) {
            verdict = Verdict.GUARD_BLOCKED;
        } else if (playerCorrections + vehicleCorrections > 0 || pp > 0.05D || vp > 0.05D) {
            verdict = Verdict.CORRECTED_OR_PARTIAL;
        } else {
            verdict = Verdict.NO_RESULT;
        }
        log("VERDICT_" + verdict, player);
        writeSummary(player, verdict, pp, vp, mounted);
        message(player, "Verdict " + verdict + " | player " + fmt(pp) + " | vehicle " + fmt(vp)
            + " | mounted " + mounted + " | corrections " + (playerCorrections + vehicleCorrections)
            + " | detach/attach " + detaches + "/" + attaches + ".");
        stop(player, "RUN_COMPLETE");
    }

    private static boolean isAllowed(Minecraft mc) {
        return ALLOWED.contains(normalize(serverAddress(mc)));
    }

    private static String serverAddress(Minecraft mc) {
        ServerData data = mc == null ? null : mc.getCurrentServer();
        return data == null || data.ip == null ? "" : data.ip;
    }

    private static String normalize(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }

    private static boolean isBoatOrRaft(Entity entity) {
        String type = entity.getType().toString().toLowerCase(Locale.ROOT);
        return type.contains("boat") || type.contains("raft");
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        if (player == null) return null;
        Entity root = player.getRootVehicle();
        if (root == player || root.getControllingPassenger() != player) return null;
        return root;
    }

    private static boolean recoverVehicle(Minecraft mc, LocalPlayer player) {
        if (player == null) return false;
        Entity controlled = controlledVehicle(player);
        if (sameVehicle(controlled)) {
            vehicle = controlled;
            vehicleId = controlled.getId();
            return true;
        }
        if (mc != null && mc.level != null && vehicleId >= 0) {
            Entity byId = mc.level.getEntity(vehicleId);
            if (sameVehicle(byId)) {
                vehicle = byId;
                return true;
            }
        }
        return vehicle != null && !vehicle.isRemoved();
    }

    private static boolean sameVehicle(Entity candidate) {
        return candidate != null && !candidate.isRemoved() && vehicleUuid != null && vehicleUuid.equals(candidate.getUUID());
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

    private static Vec3 vehiclePosition() {
        return vehicle == null ? null : vehicle.position();
    }

    private static double projected(Vec3 start, Vec3 current, Vec3 vector) {
        if (start == null || current == null || vector == null) return 0.0D;
        return current.subtract(start).dot(vector.normalize());
    }

    private static void openLog(Minecraft mc) {
        closeLog();
        try {
            Path dir = mc.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY).resolve("logs");
            Files.createDirectories(dir);
            String stamp = Instant.now().toString().replace(':', '-');
            csvPath = dir.resolve("purple-" + stamp + ".csv");
            csv = Files.newBufferedWriter(csvPath, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            csv.write("time,nano_ms,tick,event,state,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,last_target_x,last_target_y,last_target_z,sent_distance,packets,player_corrections,vehicle_corrections,detaches,attaches,mounted\n");
            csv.flush();
        } catch (IOException ignored) {
            csv = null;
            csvPath = null;
        }
    }

    private static void log(String event, LocalPlayer player) {
        if (csv == null) return;
        Vec3 p = player == null ? Vec3.ZERO : player.position();
        Vec3 v = vehiclePosition() == null ? Vec3.ZERO : vehiclePosition();
        Vec3 t = lastTarget == null ? Vec3.ZERO : lastTarget;
        boolean mounted = player != null && controlledVehicle(player) == vehicle;
        double ms = (System.nanoTime() - runStartNanos) / 1_000_000.0D;
        try {
            csv.write(String.format(Locale.ROOT,
                "%s,%.3f,%d,%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%d,%d,%d,%d,%d,%s%n",
                Instant.now(), ms, clientTick, event, state == null ? "NONE" : state,
                p.x, p.y, p.z, v.x, v.y, v.z, t.x, t.y, t.z, sentDistance,
                packetsSent, playerCorrections, vehicleCorrections, detaches, attaches, mounted));
            csv.flush();
        } catch (IOException ignored) {
        }
    }

    private static void writeSummary(LocalPlayer player, Verdict verdict, double pp, double vp, boolean mounted) {
        try {
            Minecraft mc = Minecraft.getInstance();
            Path dir = mc.gameDirectory.toPath().resolve("config").resolve(CONFIG_DIRECTORY).resolve("logs");
            Files.createDirectories(dir);
            String base = csvPath == null ? "purple-" + Instant.now().toString().replace(':', '-')
                : csvPath.getFileName().toString().replace(".csv", "");
            Path out = dir.resolve(base + "-summary.json");
            String json = "{\n"
                + "  \"version\": \"" + VERSION + "\",\n"
                + "  \"endpoint\": \"" + escape(serverAddress(mc)) + "\",\n"
                + "  \"profile\": \"vehicle-0.25x8-plus-0.15\",\n"
                + "  \"verdict\": \"" + verdict + "\",\n"
                + "  \"sentDistance\": " + fmt(sentDistance) + ",\n"
                + "  \"packetsSent\": " + packetsSent + ",\n"
                + "  \"playerProgress\": " + fmt(pp) + ",\n"
                + "  \"vehicleProgress\": " + fmt(vp) + ",\n"
                + "  \"mounted\": " + mounted + ",\n"
                + "  \"playerCorrections\": " + playerCorrections + ",\n"
                + "  \"vehicleCorrections\": " + vehicleCorrections + ",\n"
                + "  \"detaches\": " + detaches + ",\n"
                + "  \"attaches\": " + attaches + ",\n"
                + "  \"sendToFirstCorrectionMs\": " + elapsed(firstCorrectionNanos) + ",\n"
                + "  \"sendToFirstDetachMs\": " + elapsed(firstDetachNanos) + ",\n"
                + "  \"sendToFirstAttachMs\": " + elapsed(firstAttachNanos) + ",\n"
                + "  \"csv\": \"" + escape(csvPath == null ? "" : csvPath.toString()) + "\"\n"
                + "}\n";
            Files.writeString(out, json, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);
        } catch (IOException ignored) {
        }
    }

    private static String elapsed(long nanos) {
        if (nanos <= 0L) return "-1.000";
        return fmt((nanos - runStartNanos) / 1_000_000.0D);
    }

    private static void stop(LocalPlayer player, String reason) {
        if (player != null && csv != null) log("STOP_" + reason, player);
        active = false;
        state = null;
        ticksRemaining = 0;
        vehicle = null;
        vehicleUuid = null;
        vehicleId = -1;
        direction = null;
        playerStart = null;
        vehicleStart = null;
        lastTarget = null;
        sentDistance = 0.0D;
        closeLog();
    }

    private static void closeLog() {
        if (csv != null) {
            try { csv.close(); } catch (IOException ignored) {}
        }
        csv = null;
        csvPath = null;
    }

    private static String fmt(double value) {
        return String.format(Locale.ROOT, "%.3f", value);
    }

    private static String escape(String value) {
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private static void message(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab] " + text), false);
    }

    private static void actionbar(LocalPlayer player, String text) {
        if (player != null) player.displayClientMessage(Component.literal("[PhaseLab] " + text), true);
    }
}
