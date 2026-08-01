package online.coredispatch.mountlab.mixin;

import net.minecraft.client.network.ClientPlayNetworkHandler;
import net.minecraft.network.packet.s2c.play.EntityPassengersSetS2CPacket;
import net.minecraft.network.packet.s2c.play.EntityPositionS2CPacket;
import net.minecraft.network.packet.s2c.play.EntityPositionSyncS2CPacket;
import net.minecraft.network.packet.s2c.play.PlayerPositionLookS2CPacket;
import online.coredispatch.mountlab.PacketProbe;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Observes relevant vanilla packets after normal client processing. Never cancels or alters them. */
@Mixin(ClientPlayNetworkHandler.class)
public abstract class ClientPlayNetworkHandlerMixin {
    @Inject(method = "onEntityPassengersSet", at = @At("TAIL"))
    private void mountlab$passengers(EntityPassengersSetS2CPacket packet, CallbackInfo ci) {
        PacketProbe.passengers(packet.getEntityId(), packet.getPassengerIds());
    }

    @Inject(method = "onPlayerPositionLook", at = @At("TAIL"))
    private void mountlab$playerPosition(PlayerPositionLookS2CPacket packet, CallbackInfo ci) {
        PacketProbe.playerPosition(packet.change(), packet.relatives());
    }

    @Inject(method = "onEntityPositionSync", at = @At("TAIL"))
    private void mountlab$entityPositionSync(EntityPositionSyncS2CPacket packet, CallbackInfo ci) {
        PacketProbe.entityPositionSync(packet.id(), packet.values());
    }

    @Inject(method = "onEntityPosition", at = @At("TAIL"))
    private void mountlab$entityPosition(EntityPositionS2CPacket packet, CallbackInfo ci) {
        PacketProbe.entityPosition(packet.entityId(), packet.change(), packet.relatives());
    }
}
