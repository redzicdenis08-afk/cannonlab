package dev.denis.phaselab.mixin;

import dev.denis.phaselab.PhaseTelemetryClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundOpenScreenPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Passive hooks for inbound server evidence only. */
@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void phaselab$recordPlayerCorrectionHead(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onPlayerCorrectionHead();
    }

    @Inject(method = "handleMovePlayer", at = @At("TAIL"))
    private void phaselab$recordPlayerCorrectionTail(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onPlayerCorrectionTail();
    }

    @Inject(method = "handleMoveVehicle", at = @At("HEAD"))
    private void phaselab$recordVehicleCorrectionHead(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onVehicleCorrectionHead();
    }

    @Inject(method = "handleMoveVehicle", at = @At("TAIL"))
    private void phaselab$recordVehicleCorrectionTail(ClientboundMoveVehiclePacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onVehicleCorrectionTail();
    }

    @Inject(method = "handleOpenScreen", at = @At("HEAD"))
    private void phaselab$recordServerOpenScreen(ClientboundOpenScreenPacket packet, CallbackInfo ci) {
        PhaseTelemetryClient.onServerOpenScreen();
    }
}
