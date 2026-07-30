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
    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void phaselab$beforeServerPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrectionHead(packet);
    }

    @Inject(method = "handleMovePlayer", at = @At("TAIL"))
    private void phaselab$afterServerPlayerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPlayerCorrectionTail(packet);
    }

    @Inject(method = "handleMoveVehicle", at = @At("HEAD"))
    private void phaselab$beforeServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrectionHead(packet);
    }

    @Inject(method = "handleMoveVehicle", at = @At("TAIL"))
    private void phaselab$afterServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrectionTail(packet);
    }

    @Inject(method = "handleSetEntityPassengersPacket", at = @At("HEAD"))
    private void phaselab$beforeServerPassengers(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPassengersHead(packet);
    }

    @Inject(method = "handleSetEntityPassengersPacket", at = @At("TAIL"))
    private void phaselab$afterServerPassengers(ClientboundSetPassengersPacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerPassengersTail(packet);
    }
}
