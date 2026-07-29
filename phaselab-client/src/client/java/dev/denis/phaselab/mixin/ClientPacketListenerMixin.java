package dev.denis.phaselab.mixin;

import dev.denis.phaselab.BoatPhaseClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void phaselab$recordServerPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrection();
    }

    @Inject(method = "handleMoveVehicle", at = @At("HEAD"))
    private void phaselab$recordServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrection();
    }
}
