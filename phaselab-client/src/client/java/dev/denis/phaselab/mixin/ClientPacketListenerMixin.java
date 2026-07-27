package dev.denis.phaselab.mixin;

import dev.denis.phaselab.BoatPhaseClient;
import dev.denis.phaselab.PhaseLabClient;
import dev.denis.phaselab.PhaseTelemetryClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundOpenScreenPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void phaselab$recordServerCorrectionHead(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onCorrectionHead();
        PhaseLabClient.onServerPositionCorrection();
    }

    @Inject(method = "handleMovePlayer", at = @At("TAIL"))
    private void phaselab$recordServerCorrectionTail(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onCorrectionTail();
    }

    @Inject(method = "handleMoveVehicle", at = @At("HEAD"))
    private void phaselab$recordServerVehicleCorrection(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        BoatPhaseClient.onServerVehicleCorrection();
    }

    @Inject(method = "handleOpenScreen", at = @At("HEAD"))
    private void phaselab$recordServerOpenScreen(ClientboundOpenScreenPacket packet, CallbackInfo ci) {
        PhaseLabClient.onServerOpenScreen();
    }
}
