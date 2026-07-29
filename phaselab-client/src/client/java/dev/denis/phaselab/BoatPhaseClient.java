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
 * Bounded vehicle-movement verifier for servers the user owns or is authorized
 * to test. It performs one finite packet attempt, stops on any player/vehicle
 * correction or dismount, and never treats client-only movement as success.
 */
public final class BoatPhaseClient implements ClientModInitializer {
    private static final double STEP = 0.25D;
    private static final double BOAT_SEGMENT_LENGTH = 19.0D;
    private static final double HORSE_SEGMENT_LENGTH = 10.0D;
    private static final int SETTLE_TICKS = 20;


    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "boat_phase")
    );

    private static KeyMapping toggleKey;
    private static KeyMapping abortKey;

    private static boolean active;
    private static Vec3 direction;
    private static double travelled;
    private static boolean originalVehicleNoPhysics;
    private static boolean originalVehicleNoGravity;
    private static boolean readyMessageShown;
    private static Entity activeVehicle;
    private static int sentPackets;
    private static int activeTicks;
    private static int segmentsCompleted;
    private static int packetsPerSegment;
    private static int settleTicksRemaining;
    private static double segmentLength;
    private static String vehicleLabel;
    private static BufferedWriter logWriter;

    @Override
    public void onInitializeClient() {
        toggleKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_toggle",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_P,
            CATEGORY
        ));
        abortKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.boat_abort",
            InputConstants.Type.KEYSYM,
            GLFW.GLFW_KEY_O,
            CATEGORY
        ));
        ClientTickEvents.END_CLIENT_TICK.register(BoatPhaseClient::onClientTick);
    }

    /** Called by the packet-listener mixin for a real server player correction. */
    public static void onServerPlayerCorrection() {
        if (!active) {
            return;
        }
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_PLAYER_SETBACK", player, null);
        stop(player, "REJECTED: the server corrected your player position.", true);
    }

    /** Called by the packet-listener mixin for a real server vehicle correction. */
    public static void onServerVehicleCorrection() {
        if (!active) {
            return;
        }
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_VEHICLE_SETBACK", player, null);
        stop(player, "REJECTED: the server corrected the vehicle position.", true);
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            readyMessageShown = false;
            stop(null, null, false);
            return;
        }

        if (!readyMessageShown) {
            readyMessageShown = true;
            message(player, "Verifier loaded. Mount one boat/horse, face the test wall, press P once. No auto-remount or fake interior claims.");
        }

        while (toggleKey.consumeClick()) {
            if (active) {
                stop(player, "Vehicle phase stopped.", false);
            } else {
                start(player);
            }
        }
        while (abortKey.consumeClick()) {
            if (active) {
                stop(player, "Vehicle phase aborted.", false);
            }
        }

        if (!active) {
            return;
        }

        Entity vehicle = controlledVehicle(player);
        if (vehicle == null || vehicle != activeVehicle) {
            stop(player, "DISMOUNTED: the server removed or changed your controlled vehicle.", true);
            return;
        }

        if (settleTicksRemaining > 0) {
            settleTicksRemaining--;
            activeTicks++;
            if (settleTicksRemaining == 0) {
                stop(player,
                    "UNVERIFIED: no correction arrived during the settle window. Check server-side player and vehicle coordinates before counting this as a phase.",
                    false
                );
            } else {
                actionbar(player, String.format(Locale.ROOT,
                    "Waiting for delayed server verdict... %d/%d",
                    SETTLE_TICKS - settleTicksRemaining,
                    SETTLE_TICKS
                ));
            }
            return;
        }

        log("ATTEMPT_START", player, vehicle.position());
        for (int packetIndex = 0; packetIndex < packetsPerSegment; packetIndex++) {
            if (controlledVehicle(player) != activeVehicle) {
                stop(player, "DISMOUNTED during packet segment.", true);
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
            log("SEND_0_25", player, next);
        }

        segmentsCompleted = 1;
        settleTicksRemaining = SETTLE_TICKS;
        activeTicks++;
        log("ATTEMPT_SENT", player, vehicle.position());
        actionbar(player, String.format(Locale.ROOT,
            "%s attempt sent: %.1f blocks / %d packets. Waiting for server verdict.",
            vehicleLabel,
            travelled,
            sentPackets
        ));
    }

    private static void start(LocalPlayer player) {
        Entity vehicle = controlledVehicle(player);
        if (vehicle == null) {
            message(player, "Mount and control a boat or saddled horse first, then press P.");
            return;
        }
        if (!isBoat(vehicle) && !isHorse(vehicle)) {
            message(player, "This build is verified for boats and horses only.");
            return;
        }

        boolean horse = isHorse(vehicle);
        segmentLength = horse ? HORSE_SEGMENT_LENGTH : BOAT_SEGMENT_LENGTH;
        packetsPerSegment = (int) Math.round(segmentLength / STEP);
        vehicleLabel = horse ? "Horse" : "Boat";

        int cardinal = Math.floorMod((int) Math.round(player.getYRot() / 90.0D), 4);
        direction = switch (cardinal) {
            case 0 -> new Vec3(0.0D, 0.0D, 1.0D);   // South
            case 1 -> new Vec3(-1.0D, 0.0D, 0.0D);  // West
            case 2 -> new Vec3(0.0D, 0.0D, -1.0D);  // North
            default -> new Vec3(1.0D, 0.0D, 0.0D);  // East
        };

        active = true;
        travelled = 0.0D;
        sentPackets = 0;
        activeTicks = 0;
        segmentsCompleted = 0;
        settleTicksRemaining = 0;
        originalVehicleNoPhysics = vehicle.noPhysics;
        originalVehicleNoGravity = vehicle.isNoGravity();
        activeVehicle = vehicle;
        vehicle.noPhysics = true;
        openLog();
        log("START", player, vehicle.position());
        message(player, String.format(Locale.ROOT,
            "%s verifier started toward %s. One bounded attempt only; P/O abort.",
            vehicleLabel,
            directionLabel(direction)
        ));
    }

    private static String directionLabel(Vec3 vector) {
        double degrees = Math.toDegrees(Math.atan2(-vector.x, vector.z));
        if (degrees < 0.0D) {
            degrees += 360.0D;
        }
        String[] labels = {"S", "SW", "W", "NW", "N", "NE", "E", "SE"};
        int index = (int) Math.round(degrees / 45.0D) & 7;
        return labels[index];
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

    private static boolean isHorse(Entity vehicle) {
        return vehicle.getType().toString().toLowerCase(Locale.ROOT).contains("horse");
    }

    private static void stop(LocalPlayer player, String reason, boolean setback) {
        if (!active && logWriter == null) {
            return;
        }

        if (activeVehicle != null) {
            activeVehicle.noPhysics = originalVehicleNoPhysics;
            activeVehicle.setNoGravity(originalVehicleNoGravity);
            activeVehicle.setDeltaMovement(Vec3.ZERO);
        }

        if (player != null) {
            Entity vehicle = controlledVehicle(player);
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
        segmentsCompleted = 0;
        settleTicksRemaining = 0;
        activeVehicle = null;
        closeLog();
    }

    private static void openLog() {
        closeLog();
        try {
            Path directory = Minecraft.getInstance().gameDirectory.toPath()
                .resolve("config")
                .resolve("phaselab");
            Files.createDirectories(directory);
            Path logPath = directory.resolve("vehicle-verifier-v4.7-" + Instant.now().toString().replace(':', '-') + ".csv");
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

    private static void actionbar(LocalPlayer player, String text) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), true);
    }
}
