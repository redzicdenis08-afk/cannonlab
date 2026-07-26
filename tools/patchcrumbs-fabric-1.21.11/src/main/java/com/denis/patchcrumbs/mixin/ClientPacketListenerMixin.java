package com.denis.patchcrumbs.mixin;

import com.denis.patchcrumbs.PatchcrumbsClient;
import net.minecraft.client.multiplayer.ClientPacketListener;
import net.minecraft.network.protocol.game.ClientboundExplodePacket;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(ClientPacketListener.class)
public abstract class ClientPacketListenerMixin {
    @Inject(method = "handleExplosion", at = @At("HEAD"))
    private void denisPatchcrumbs$captureExplosion(ClientboundExplodePacket packet, CallbackInfo ci) {
        PatchcrumbsClient.recordExplosion(packet.center(), packet.radius(), packet.blockCount());
    }
}
