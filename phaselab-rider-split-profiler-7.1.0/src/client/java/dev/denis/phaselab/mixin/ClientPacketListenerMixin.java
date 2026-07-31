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
     * TAIL is intentional: the client classifies state after vanilla applies the
     * authoritative packet. Intermediary names are literal because the release
     * jar is produced without a Mixin refmap; this keeps startup deterministic
     * on Minecraft 1.21.11.
     */
    @Inject(method = "method_11157", at = @At("TAIL"), remap = false)
    private void phaselab$afterServerPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrectionApplied();
    }

    @Inject(method = "method_11134", at = @At("TAIL"), remap = false)
    private void phaselab$afterServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrectionApplied();
    }

    @Inject(method = "method_11080", at = @At("TAIL"), remap = false)
    private void phaselab$afterServerPassengerGraph(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPassengersApplied(packet);
    }
}
