package dev.denis.phaselab.mixin;

import dev.denis.phaselab.PhaseLabClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundOpenScreenPacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleMovePlayer", at = @At("HEAD"))
    private void phaselab$recordServerCorrection(ClientboundPlayerPositionPacket packet, CallbackInfo ci) {
        PhaseLabClient.onServerPositionCorrection();
    }

    @Inject(method = "handleOpenScreen", at = @At("HEAD"))
    private void phaselab$recordServerOpenScreen(ClientboundOpenScreenPacket packet, CallbackInfo ci) {
        PhaseLabClient.onServerOpenScreen();
    }
}
