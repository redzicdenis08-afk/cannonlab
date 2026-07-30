package dev.denis.phaselab.net;

import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.resources.Identifier;

public record LabMessagePayload(String message) implements CustomPacketPayload {
    public static final Identifier ID = Identifier.fromNamespaceAndPath("phaselab", "control");
    public static final Type<LabMessagePayload> TYPE = new Type<>(ID);
    public static final StreamCodec<RegistryFriendlyByteBuf, LabMessagePayload> CODEC = StreamCodec.composite(
        ByteBufCodecs.STRING_UTF8,
        LabMessagePayload::message,
        LabMessagePayload::new
    );

    @Override
    public Type<? extends CustomPacketPayload> type() {
        return TYPE;
    }
}