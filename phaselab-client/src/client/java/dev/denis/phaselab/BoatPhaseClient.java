package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.network.protocol.game.ServerboundMoveVehiclePacket;
import net.minecraft.resources.Identifier;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;
import org.lwjgl.glfw.GLFW;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Locale;

/**
 * Exact-Sakura vehicle-movement phase prototype.
 *
 * The server lab established that one large vehicle jump and 0.50-block steps
 * are corrected, while horizontal 0.25-block steps are accepted through
 * collision. This entrypoint implements only that verified packet grammar and
 * stops immediately on a real server vehicle setback.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final double STEP = 0.25D;
    private static final double MAX_DISTANCE = 512.0D;

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "boat_phase")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static Vec3 direction;
    private static double travelled;
    private static boolean originalVehicleNoPhysics;
    private static int sentPackets;
    private static int activeTicks;
    private static BufferedWriter logWriter;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_toggle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_F11,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_F12,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    /** Called by the packet-listener mixin for a real server vehicle correction. */
    public static void onServerVehicleCorrection() {
        if (!active) {
            return;
        }
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_VEHICLE_SETBACK", player, null);
        stop(player, "Server corrected the boat. Phase stopped.", true);
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            stop(null, null, false);
            return;
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                stop(player, "Boat phase stopped.", false);
            } else {
                start(player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) {
                stop(player, "Boat phase aborted.", false);
            }
        }

        if (!active) {
            return;
        }

        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            stop(player, "You are no longer controlling a vehicle.", true);
            return;
        }

        if (travelled + STEP > MAX_DISTANCE) {
            stop(player, String.format(Locale.ROOT, "Safety limit reached at %.1f blocks.", travelled), false);
            return;
        }

        Vec3 next = vehicle.position().add(direction.scale(STEP));
        vehicle.noPhysics = true;
        vehicle.setPos(next.x, next.y, next.z);
        player.setPos(next.x, next.y, next.z);
        player.connection.send(new ServerboundMoveVehiclePacket(
            next,
            vehicle.getYRot(),
            vehicle.getXRot(),
            vehicle.onGround()
        ));

        travelled += STEP;
        sentPackets++;
        activeTicks++;
        log("SEND_0_25", player, next);

        if (activeTicks % 20 == 0) {
            message(player, String.format(Locale.ROOT,
                "Boat phase active: %.1f blocks | %d packets | F11 stop | F12 abort",
                travelled,
                sentPackets
            ));
        }
    }

    private static void start(LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            message(player, "Mount and control a boat first, then press F11.");
            return;
        }
        if (!isBoat(vehicle)) {
            message(player, "This build is verified for boats only.");
            return;
        }

        double radians = Math.toRadians(player.getYRot());
        direction = new Vec3(-Math.sin(radians), 0.0D, Math.cos(radians)).normalize();
        if (!Double.isFinite(direction.x) || !Double.isFinite(direction.z)) {
            message(player, "Could not calculate a horizontal direction.");
            return;
        }

        active = true;
        travelled = 0.0D;
        sentPackets = 0;
        activeTicks = 0;
        originalVehicleNoPhysics = vehicle.noPhysics;
        vehicle.noPhysics = true;
        openLog();
        log("START", player, vehicle.position());
        message(player, "Boat phase started in your look direction. F11 stops; F12 aborts.");
    }

    private static Entity controlledVehicle(LocalPlayer player) {
        Entity vehicle = player.getRootVehicle();
        if (vehicle == player || vehicle.getControllingPassenger() != player) {
            return null;
        }
        return vehicle;
    }

    private static boolean isBoat(Entity vehicle) {
        return vehicle.getType().toString().toLowerCase(Locale.ROOT).contains("boat");
    }

    private static void stop(LocalPlayer player, String reason, boolean setback) {
        if (!active && logWriter == null) {
            return;
        }

        if (player != null) {
            Entity vehicle = controlledVehicle(player);
            if (vehicle != null) {
                vehicle.noPhysics = originalVehicleNoPhysics;
            }
            log(setback ? "STOP_SETBACK" : "STOP", player, vehicle == null ? null : vehicle.position());
            if (reason != null) {
                message(player, reason + String.format(Locale.ROOT,
                    " Travelled %.2f blocks with %d packets.", travelled, sentPackets));
            }
        }

        active = false;
        direction = null;
        travelled = 0.0D;
        sentPackets = 0;
        activeTicks = 0;
        closeLog();
    }

    private static void openLog() {
        closeLog();
        try {
            Path directory = Minecraft.getInstance().gameDirectory.toPath()
                .resolve("config")
                .resolve("phaselab");
            Files.createDirectories(directory);
            Path logPath = directory.resolve("boat-phase-v4-" + Instant.now().toString().replace(':', '-') + ".csv");
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write("time,event,player_x,player_y,player_z,target_x,target_y,target_z,travelled,packets\n");
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
        }
    }

    private static void log(String event, LocalPlayer player, Vec3 target) {
        if (logWriter == null) {
            return;
        }
        Vec3 position = player == null ? Vec3.ZERO : player.position();
        Vec3 loggedTarget = target == null ? Vec3.ZERO : target;
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%s,%s,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.3f,%d%n",
                Instant.now(),
                event,
                position.x, position.y, position.z,
                loggedTarget.x, loggedTarget.y, loggedTarget.z,
                travelled,
                sentPackets
            ));
            logWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private static void closeLog() {
        if (logWriter != null) {
            try {
                logWriter.close();
            } catch (IOException ignored) {
            }
        }
        logWriter = null;
    }

    private static void message(LocalPlayer player, String text) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), false);
    }
}
