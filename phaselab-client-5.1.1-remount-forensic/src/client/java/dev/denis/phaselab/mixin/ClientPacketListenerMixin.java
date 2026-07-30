package dev.denis.phaselab.mixin;

import dev.denis.phaselab.BoatPhaseClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ClientboundSetPassengersPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    /**
     * TAIL is intentional: the adaptive client classifies the position after
     * vanilla has applied the server's authoritative correction.
     */
    @Inject(method = "handleMovePlayer", at = @At("TAIL"))
    private void phaselab$afterServerPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrectionApplied();
    }

    @Inject(method = "handleMoveVehicle", at = @At("TAIL"))
    private void phaselab$afterServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrectionApplied();
    }

    @Inject(method = "handleSetEntityPassengersPacket", at = @At("TAIL"))
    private void phaselab$afterServerPassengers(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPassengersApplied(packet);
    }
}
