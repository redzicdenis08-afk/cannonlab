package dev.denis.phaselab;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.world.phys.Vec3;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Locale;

/**
 * Independent telemetry companion for PhaseLab.
 *
 * It measures large local probe snaps and then records whether a real server
 * position-correction packet follows. This makes the visible "inside for a
 * millisecond" effect distinguishable from PhaseLab's own local restore.
 */
public final class PhaseTelemetryClient implements ClientModInitializer {
    private static final double SNAP_THRESHOLD = 0.45D;
    private static final long CORRELATION_WINDOW_NANOS = 10_000_000_000L;

    private static Vec3 lastTickPosition;
    private static Vec3 lastSnapFrom;
    private static Vec3 lastSnapTo;
    private static long lastSnapNanos;

    private static boolean correctionPending;
    private static Vec3 correctionBefore;
    private static long correctionHeadNanos;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(PhaseTelemetryClient::onClientTick);
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            lastTickPosition = null;
            lastSnapFrom = null;
            lastSnapTo = null;
            lastSnapNanos = 0L;
            correctionPending = false;
            return;
        }

        Vec3 current = player.position();
        if (lastTickPosition != null && player.noPhysics) {
            double distance = current.distanceTo(lastTickPosition);
            if (distance >= SNAP_THRESHOLD) {
                lastSnapFrom = lastTickPosition;
                lastSnapTo = current;
                lastSnapNanos = System.nanoTime();
                append("LOCAL_PROBE_SNAP", 0.0D, 0.0D, lastSnapFrom, lastSnapTo, current);
            }
        }
        lastTickPosition = current;
    }

    public static void onCorrectionHead() {
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        correctionPending = true;
        correctionHeadNanos = System.nanoTime();
        correctionBefore = player == null ? null : player.position();
    }

    public static void onCorrectionTail() {
        if (!correctionPending) {
            return;
        }
        correctionPending = false;

        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        if (player == null) {
            return;
        }

        long now = System.nanoTime();
        Vec3 corrected = player.position();
        double sinceSnapMs = lastSnapNanos == 0L
            ? -1.0D
            : (now - lastSnapNanos) / 1_000_000.0D;
        double handlerMs = (now - correctionHeadNanos) / 1_000_000.0D;
        boolean correlated = lastSnapNanos != 0L && now - lastSnapNanos <= CORRELATION_WINDOW_NANOS;

        if (correlated) {
            String speed = sinceSnapMs < 250.0D ? "FAST" : sinceSnapMs < 1_000.0D ? "NORMAL" : "DELAYED";
            player.displayClientMessage(Component.literal(String.format(Locale.ROOT,
                "[PhaseLab] SERVER SETBACK %s after %.1f ms -> %.3f %.3f %.3f",
                speed,
                sinceSnapMs,
                corrected.x,
                corrected.y,
                corrected.z
            )), false);
        }

        append(
            correlated ? "SERVER_SETBACK_CORRELATED" : "SERVER_POSITION_PACKET_UNCORRELATED",
            sinceSnapMs,
            handlerMs,
            lastSnapFrom,
            lastSnapTo,
            corrected
        );
    }

    private static void append(
        String event,
        double sinceSnapMs,
        double handlerMs,
        Vec3 snapFrom,
        Vec3 snapTo,
        Vec3 finalPosition
    ) {
        try {
            Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Files.createDirectories(directory);
            Path path = directory.resolve("telemetry-v3.1.csv");
            boolean createHeader = !Files.exists(path) || Files.size(path) == 0L;

            try (var writer = Files.newBufferedWriter(
                path,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.APPEND
            )) {
                if (createHeader) {
                    writer.write("timestamp,event,since_snap_ms,handler_ms,snap_from_x,snap_from_y,snap_from_z,snap_to_x,snap_to_y,snap_to_z,final_x,final_y,final_z\n");
                }
                writer.write(String.format(Locale.ROOT,
                    "%s,%s,%.3f,%.3f,%s,%s,%s%n",
                    Instant.now(),
                    event,
                    sinceSnapMs,
                    handlerMs,
                    vectorCsv(snapFrom),
                    vectorCsv(snapTo),
                    vectorCsv(finalPosition)
                ));
            }
        } catch (IOException ignored) {
        }
    }

    private static String vectorCsv(Vec3 vector) {
        if (vector == null) {
            return ",,";
        }
        return String.format(Locale.ROOT, "%.6f,%.6f,%.6f", vector.x, vector.y, vector.z);
    }
}
