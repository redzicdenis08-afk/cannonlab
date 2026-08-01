package online.coredispatch.mountlab;

import net.minecraft.entity.EntityPosition;
import net.minecraft.util.math.Vec3d;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;

/** Read-only packet timeline recorder. It never cancels or modifies packets. */
public final class PacketProbe {
    private record Observation(long nanoTime, String text) { }

    private static final ConcurrentLinkedQueue<Observation> QUEUE = new ConcurrentLinkedQueue<>();
    private static volatile boolean enabled;
    private static volatile int watchedVehicleId = -1;
    private static volatile int watchedPlayerId = -1;

    private PacketProbe() { }

    public static void start(int vehicleId, int playerId) {
        QUEUE.clear();
        watchedVehicleId = vehicleId;
        watchedPlayerId = playerId;
        enabled = true;
    }

    public static void stop() {
        enabled = false;
        watchedVehicleId = -1;
        watchedPlayerId = -1;
        QUEUE.clear();
    }

    public static void passengers(int entityId, int[] passengerIds) {
        if (!enabled) return;
        boolean relevant = entityId == watchedVehicleId;
        StringBuilder ids = new StringBuilder();
        for (int i = 0; i < passengerIds.length; i++) {
            if (i > 0) ids.append('|');
            ids.append(passengerIds[i]);
            if (passengerIds[i] == watchedPlayerId) relevant = true;
        }
        if (relevant) record("PASSENGERS entity=" + entityId + " ids=" + ids);
    }

    public static void playerPosition(EntityPosition change, Object relatives) {
        if (!enabled) return;
        Vec3d pos = change.position();
        record("PLAYER_POSITION x=" + compact(pos.x) + " y=" + compact(pos.y) + " z=" + compact(pos.z)
            + " flags=" + sanitize(String.valueOf(relatives)));
    }

    public static void entityPositionSync(int entityId, EntityPosition values) {
        if (!enabled || entityId != watchedVehicleId) return;
        Vec3d pos = values.position();
        record("VEHICLE_POSITION_SYNC id=" + entityId + " x=" + compact(pos.x)
            + " y=" + compact(pos.y) + " z=" + compact(pos.z));
    }

    public static void entityPosition(int entityId, EntityPosition change, Object relatives) {
        if (!enabled || entityId != watchedVehicleId) return;
        Vec3d pos = change.position();
        record("VEHICLE_POSITION id=" + entityId + " x=" + compact(pos.x)
            + " y=" + compact(pos.y) + " z=" + compact(pos.z)
            + " flags=" + sanitize(String.valueOf(relatives)));
    }

    public static String drainEncoded() {
        List<String> events = new ArrayList<>();
        Observation observation;
        while ((observation = QUEUE.poll()) != null) {
            events.add(observation.text());
        }
        return String.join(";", events);
    }

    private static void record(String text) {
        QUEUE.add(new Observation(System.nanoTime(), sanitize(text)));
    }

    private static String sanitize(String text) {
        return text.replace(',', '|').replace('\n', ' ').replace('\r', ' ');
    }

    private static String compact(double value) {
        return String.format(java.util.Locale.ROOT, "%.5f", value);
    }
}
