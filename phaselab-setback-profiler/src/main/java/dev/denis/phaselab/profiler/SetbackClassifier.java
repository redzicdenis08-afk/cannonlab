package dev.denis.phaselab.profiler;

import java.util.Locale;

/**
 * Conservative state-shape classifier. It deliberately describes only what
 * the server observed and never attributes a result to a specific plugin.
 */
public final class SetbackClassifier {
    private static final double MATERIAL_DISTANCE = 0.05D;

    private SetbackClassifier() {
    }

    public enum Classification {
        NO_AUTHORITATIVE_CHANGE,
        VEHICLE_ROLLBACK_MOUNT_RETAINED,
        DETACH_PLUS_TELEPORT_AND_VEHICLE_ROLLBACK,
        DETACH_PLUS_TELEPORT,
        DETACH_PLUS_VEHICLE_ROLLBACK,
        PASSENGER_ONLY_EJECT,
        MOUNT_STATE_LOST_WITHOUT_EVENT,
        INSUFFICIENT_EVIDENCE
    }

    public record Input(
            boolean wasMounted,
            boolean nowMounted,
            boolean vehicleExitObserved,
            boolean dismountObserved,
            boolean teleportObserved,
            double playerDistance,
            double vehicleDistance
    ) {
        public Input {
            playerDistance = sanitizeDistance(playerDistance);
            vehicleDistance = sanitizeDistance(vehicleDistance);
        }
    }

    public record Result(Classification classification, String explanation) {
    }

    public static Result classify(Input input) {
        if (!input.wasMounted()) {
            return new Result(
                    Classification.INSUFFICIENT_EVIDENCE,
                    "No mounted baseline existed before the observation window."
            );
        }

        boolean playerMoved = input.playerDistance() >= MATERIAL_DISTANCE;
        boolean vehicleMoved = input.vehicleDistance() >= MATERIAL_DISTANCE;
        boolean detachEvent = input.vehicleExitObserved() || input.dismountObserved();

        if (input.nowMounted()) {
            if (vehicleMoved) {
                return new Result(
                        Classification.VEHICLE_ROLLBACK_MOUNT_RETAINED,
                        distanceText("Mount remained authoritative while the vehicle position changed", input)
                );
            }
            return new Result(
                    Classification.NO_AUTHORITATIVE_CHANGE,
                    "Mount remained authoritative and no material server-side displacement was observed."
            );
        }

        if (input.teleportObserved() && vehicleMoved) {
            return new Result(
                    Classification.DETACH_PLUS_TELEPORT_AND_VEHICLE_ROLLBACK,
                    distanceText("Passenger detached with a player teleport and vehicle displacement", input)
            );
        }
        if (input.teleportObserved()) {
            return new Result(
                    Classification.DETACH_PLUS_TELEPORT,
                    distanceText("Passenger detached with a player teleport", input)
            );
        }
        if (vehicleMoved) {
            return new Result(
                    Classification.DETACH_PLUS_VEHICLE_ROLLBACK,
                    distanceText("Passenger detached with vehicle displacement", input)
            );
        }
        if (detachEvent) {
            return new Result(
                    Classification.PASSENGER_ONLY_EJECT,
                    distanceText("Server emitted a dismount/vehicle-exit event without material displacement", input)
            );
        }
        if (playerMoved) {
            return new Result(
                    Classification.MOUNT_STATE_LOST_WITHOUT_EVENT,
                    distanceText("Mount state disappeared and the player moved, but no detach event was observed", input)
            );
        }
        return new Result(
                Classification.MOUNT_STATE_LOST_WITHOUT_EVENT,
                "Mount state disappeared without a matching server event or material displacement."
        );
    }

    private static String distanceText(String prefix, Input input) {
        return String.format(
                Locale.ROOT,
                "%s (player=%.4f, vehicle=%.4f blocks).",
                prefix,
                input.playerDistance(),
                input.vehicleDistance()
        );
    }

    private static double sanitizeDistance(double distance) {
        if (!Double.isFinite(distance) || distance < 0.0D) {
            return 0.0D;
        }
        return distance;
    }
}
