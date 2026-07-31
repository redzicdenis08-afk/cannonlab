package dev.denis.phaselab.mixin;

import dev.denis.phaselab.PurpleHandoffClient;
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
    @Inject(method = "method_11157", at = @At("TAIL"), remap = false)
    private void phaselab$afterPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PurpleHandoffClient.onServerPlayerCorrectionApplied();
    }

    @Inject(method = "method_11134", at = @At("TAIL"), remap = false)
    private void phaselab$afterVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        PurpleHandoffClient.onServerVehicleCorrectionApplied();
    }

    @Inject(method = "method_11080", at = @At("TAIL"), remap = false)
    private void phaselab$afterPassengerGraph(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        PurpleHandoffClient.onServerPassengersApplied(packet);
    }
}
