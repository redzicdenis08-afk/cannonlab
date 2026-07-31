package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ClientboundMoveVehiclePacket;
import net.minecraft.network.protocol.game.ClientboundPlayerPositionPacket;
import net.minecraft.network.protocol.game.ClientboundSetPassengersPacket;
import net.minecraft.network.protocol.game.ServerboundMoveVehiclePacket;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.animal.Pig;
import net.minecraft.world.entity.animal.equine.AbstractHorse;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

/**
 * PhaseLab Persistent Animal 9.0.0
 * Mount once in wilderness. Stream small absolute vehicle packets.
 * Any detach or correction = hard abort. No remount path exists.
 */
public final class BoatPhaseClient implements ClientModInitializer {

    private static final String VERSION = "9.0.0-persistent-animal";
    private static final double STEP = 0.10D;
    private static final int PACE_TICKS = 2;
    private static final double MAX_DISTANCE = 12.0D;
    private static final int ARM_TICKS = 10;

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "persistent")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static boolean ready;
    private static int stateTicks;
    private static int sentPackets;
    private static double sentDistance;
    private static Entity vehicle;
    private static Vec3 startPos;
    private static Vec3 direction;
    private static boolean originalNoPhysics;

    private enum State { IDLE, ARMING, STREAMING }
    private static State state = State.IDLE;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.toggle", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_P, CATEGORY));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.abort", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_O, CATEGORY));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::tick);
    }

    public static void onServerPlayerCorrection(ClientboundPlayerPositionPacket packet) {
        if (active) abort("PLAYER_CORRECTION");
    }

    public static void onServerVehicleCorrection(ClientboundMoveVehiclePacket packet) {
        if (active) abort("VEHICLE_CORRECTION");
    }

    public static void onServerPassengers(ClientboundSetPassengersPacket packet) {
        if (!active || vehicle == null) return;
        Minecraft mc = Minecraft.getInstance();
        LocalPlayer player = mc.player;
        if (player == null) return;
        if (packet.getVehicle() == vehicle.getId()) {
            boolean stillMounted = false;
            for (int id : packet.getPassengers()) {
                if (id == player.getId()) {
                    stillMounted = true;
                    break;
                }
            }
            if (!stillMounted) abort("PASSENGER_DETACH");
        }
    }

    private static void tick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            if (active) abort("DISCONNECTED");
            ready = false;
            return;
        }

        if (!ready) {
            ready = true;
            msg(player, "PhaseLab Persistent " + VERSION + " ready. Mount animal in wilderness, face wall, press P. O aborts.");
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                abort("MANUAL_STOP");
            } else {
                start(client, player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) abort("ABORTED");
        }

        if (!active) return;

        if (controlled(player) != vehicle) {
            abort("MOUNT_LOST");
            return;
        }

        stateTicks++;
        switch (state) {
            case ARMING -> {
                if (stateTicks >= ARM_TICKS) {
                    state = State.STREAMING;
                    stateTicks = 0;
                    action(player, "Streaming...");
                }
            }
            case STREAMING -> stream(player);
            default -> {}
        }
    }

    private static void start(Minecraft client, LocalPlayer player) {
        Entity v = controlled(player);
        if (v == null || !isAnimal(v)) {
            msg(player, "Mount a controlled pig / horse / donkey / mule in wilderness first.");
            return;
        }
        if (!authorize(client, player)) return;

        vehicle = v;
        originalNoPhysics = v.noPhysics;
        startPos = v.position();
        direction = cardinal(player.getLookAngle());
        sentDistance = 0.0D;
        sentPackets = 0;
        stateTicks = 0;
        state = State.ARMING;
        active = true;

        msg(player, String.format(Locale.ROOT,
            "Persistent stream armed. Step %.2f, pace %d, max %.1f. Stay mounted.",
            STEP, PACE_TICKS, MAX_DISTANCE));
    }

    private static void stream(LocalPlayer player) {
        if (stateTicks % PACE_TICKS != 0) return;
        if (sentDistance + 1e-9 >= MAX_DISTANCE) {
            abort("MAX_DISTANCE");
            return;
        }

        double next = Math.min(MAX_DISTANCE, sentDistance + STEP);
        Vec3 target = startPos.add(direction.scale(next));

        boolean prev = vehicle.noPhysics;
        vehicle.noPhysics = true;
        player.connection.send(new ServerboundMoveVehiclePacket(
            target, vehicle.getYRot(), vehicle.getXRot(), true));
        vehicle.noPhysics = prev;

        sentDistance = next;
        sentPackets++;
        action(player, String.format(Locale.ROOT, "%.2f / %.1f  pkts %d", sentDistance, MAX_DISTANCE, sentPackets));
    }

    private static void abort(String reason) {
        if (!active) return;
        if (vehicle != null && !vehicle.isRemoved()) vehicle.noPhysics = originalNoPhysics;
        LocalPlayer player = Minecraft.getInstance().player;
        if (player != null) {
            msg(player, "Stopped: " + reason + " | sent " + String.format(Locale.ROOT, "%.2f", sentDistance));
        }
        active = false;
        state = State.IDLE;
        vehicle = null;
        startPos = null;
        direction = null;
    }

    private static boolean isAnimal(Entity e) {
        return e instanceof AbstractHorse || e instanceof Pig;
    }

    private static Entity controlled(LocalPlayer p) {
        Entity v = p.getVehicle();
        return v != null && v.getControllingPassenger() == p ? v : null;
    }

    private static Vec3 cardinal(Vec3 look) {
        if (Math.abs(look.x) >= Math.abs(look.z))
            return new Vec3(look.x >= 0 ? 1 : -1, 0, 0);
        return new Vec3(0, 0, look.z >= 0 ? 1 : -1);
    }

    private static boolean authorize(Minecraft client, LocalPlayer player) {
        if (client.getCurrentServer() == null) return true;
        String ip = client.getCurrentServer().ip.toLowerCase(Locale.ROOT).trim();
        if (ip.startsWith("localhost") || ip.startsWith("127.0.0.1") || ip.startsWith("[::1]"))
            return true;
        Path dir = FabricLoader.getInstance().getConfigDir().resolve("phaselab-persistent");
        Path file = dir.resolve("authorized-targets.txt");
        try {
            Files.createDirectories(dir);
            if (!Files.exists(file)) {
                Files.writeString(file, "# exact multiplayer address per line\n", StandardCharsets.UTF_8);
            }
            for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
                String t = line.trim().toLowerCase(Locale.ROOT);
                if (!t.isEmpty() && !t.startsWith("#") && t.equals(ip)) return true;
            }
            msg(player, "Not authorized. Add '" + ip + "' to " + file);
            return false;
        } catch (Exception e) {
            msg(player, "Auth check failed: " + e.getMessage());
            return false;
        }
    }

    private static void msg(LocalPlayer p, String t) {
        p.displayClientMessage(Component.literal("[PhaseLab] " + t), false);
    }

    private static void action(LocalPlayer p, String t) {
        p.displayClientMessage(Component.literal("[PhaseLab] " + t), true);
    }
}
