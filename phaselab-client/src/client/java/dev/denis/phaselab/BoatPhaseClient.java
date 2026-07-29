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
    private static final double BOAT_SEGMENT_LENGTH = 19.0D;
    private static final double HORSE_SEGMENT_LENGTH = 10.0D;
    private static final int SEGMENT_PAUSE_TICKS = 2;
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
    private static boolean originalVehicleNoGravity;
    private static double lockedY;
    private static boolean readyMessageShown;
    private static Entity activeVehicle;
    private static int sentPackets;
    private static int activeTicks;
    private static int segmentsCompleted;
    private static int pauseTicksRemaining;
    private static int packetsPerSegment;
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

    /** Called by the packet-listener mixin for a real server vehicle correction. */
    public static void onServerVehicleCorrection() {
        if (!active) {
            return;
        }
        LocalPlayer player = Minecraft.getInstance().player;
        log("SERVER_VEHICLE_SETBACK", player, null);
        stop(player, "Server corrected the vehicle. Phase stopped.", true);
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
            message(player, "Loaded. Mount a boat or horse, look where you want to go, press P. Press O to abort.");
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
        if (vehicle == null) {
            stop(player, "You are no longer controlling a vehicle.", true);
            return;
        }

        if (pauseTicksRemaining > 0) {
            holdHeight(player, vehicle);
            pauseTicksRemaining--;
            activeTicks++;
            return;
        }

        if (travelled + STEP > MAX_DISTANCE) {
            stop(player, String.format(Locale.ROOT, "Safety limit reached at %.1f blocks.", travelled), false);
            return;
        }

        int packetsThisSegment = Math.min(
            packetsPerSegment,
            (int) Math.floor((MAX_DISTANCE - travelled) / STEP)
        );
        if (packetsThisSegment <= 0) {
            stop(player, String.format(Locale.ROOT, "Safety limit reached at %.1f blocks.", travelled), false);
            return;
        }

        log("SEGMENT_START", player, vehicle.position());
        for (int packetIndex = 0; packetIndex < packetsThisSegment; packetIndex++) {
            Vec3 current = vehicle.position();
            Vec3 next = new Vec3(
                current.x + direction.x * STEP,
                lockedY,
                current.z + direction.z * STEP
            );
            vehicle.noPhysics = true;
            vehicle.setNoGravity(true);
            vehicle.setDeltaMovement(Vec3.ZERO);
            player.setDeltaMovement(Vec3.ZERO);
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

        segmentsCompleted++;
        pauseTicksRemaining = SEGMENT_PAUSE_TICKS;
        activeTicks++;
        log("SEGMENT_END", player, vehicle.position());
        actionbar(player, String.format(Locale.ROOT,
            "%s segment %d | %.1f blocks | P stop | O abort",
            vehicleLabel,
            segmentsCompleted,
            travelled
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
        pauseTicksRemaining = 0;
        originalVehicleNoPhysics = vehicle.noPhysics;
        originalVehicleNoGravity = vehicle.isNoGravity();
        lockedY = vehicle.getY();
        activeVehicle = vehicle;
        vehicle.noPhysics = true;
        vehicle.setNoGravity(true);
        vehicle.setDeltaMovement(Vec3.ZERO);
        player.setDeltaMovement(Vec3.ZERO);
        openLog();
        log("START", player, vehicle.position());
        message(player, String.format(Locale.ROOT,
            "%s started toward %s. Nearest cardinal locked. P stops; O aborts.",
            vehicleLabel,
            directionLabel(direction)
        ));
    }

    private static void holdHeight(LocalPlayer player, Entity vehicle) {
        Vec3 current = vehicle.position();
        vehicle.noPhysics = true;
        vehicle.setNoGravity(true);
        vehicle.setDeltaMovement(Vec3.ZERO);
        player.setDeltaMovement(Vec3.ZERO);
        vehicle.setPos(current.x, lockedY, current.z);
        player.setPos(current.x, lockedY, current.z);
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
        pauseTicksRemaining = 0;
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

    private static void actionbar(LocalPlayer player, String text) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), true);
    }
}
