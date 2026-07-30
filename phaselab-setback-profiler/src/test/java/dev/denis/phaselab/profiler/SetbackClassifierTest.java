package dev.denis.phaselab.profiler;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

final class SetbackClassifierTest {
    @Test
    void classifiesPassengerOnlyEject() {
        SetbackClassifier.Result result = SetbackClassifier.classify(new SetbackClassifier.Input(
                true, false, true, true, false, 0.0, 0.0
        ));
        assertEquals(SetbackClassifier.Classification.PASSENGER_ONLY_EJECT, result.classification());
    }

    @Test
    void classifiesTeleportAndVehicleRollback() {
        SetbackClassifier.Result result = SetbackClassifier.classify(new SetbackClassifier.Input(
                true, false, true, true, true, 0.8, 0.7
        ));
        assertEquals(
                SetbackClassifier.Classification.DETACH_PLUS_TELEPORT_AND_VEHICLE_ROLLBACK,
                result.classification()
        );
    }

    @Test
    void classifiesMountedVehicleRollback() {
        SetbackClassifier.Result result = SetbackClassifier.classify(new SetbackClassifier.Input(
                true, true, false, false, false, 0.0, 0.3
        ));
        assertEquals(SetbackClassifier.Classification.VEHICLE_ROLLBACK_MOUNT_RETAINED, result.classification());
    }

    @Test
    void refusesUnarmedEvidence() {
        SetbackClassifier.Result result = SetbackClassifier.classify(new SetbackClassifier.Input(
                false, false, false, false, false, 0.0, 0.0
        ));
        assertEquals(SetbackClassifier.Classification.INSUFFICIENT_EVIDENCE, result.classification());
    }
}
