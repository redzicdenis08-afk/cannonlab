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
public class ClientPacketListenerMixin {

    @Inject(method = "handleMoveVehicle", at = @At("HEAD"))
    private void onVehicle(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrection(packet);
    }

    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void onPlayer(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrection(packet);
    }

    @Inject(method = "handleSetPassengers", at = @At("HEAD"))
    private void onPassengers(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPassengers(packet);
    }
}
