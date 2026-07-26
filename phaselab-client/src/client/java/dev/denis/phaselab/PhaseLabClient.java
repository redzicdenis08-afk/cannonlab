package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
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

public final class PhaseLabClient implements ClientModInitializer {
    private static final double START_DISTANCE = 0.05D;
    private static final double STEP_DISTANCE = 0.05D;
    private static final double MAX_DISTANCE = 1.60D;
    private static final int SETTLE_TICKS = 3;
    private static final int HOLD_TICKS = 10;
    private static final double ACCEPT_ERROR = 0.12D;
    private static final double CORRECTION_ERROR = 0.35D;

    private enum State {
        IDLE,
        SETTLING,
        HOLDING,
        APPLYING_BEST
    }

    private static State state = State.IDLE;
    private static Vec3 scanOrigin;
    private static Vec3 target;
    private static Vec3 restorePoint;
    private static double directionX;
    private static double directionZ;
    private static double currentDistance;
    private static double bestAcceptedDistance = -1.0D;
    private static int attemptIndex;
    private static int stateTicks;
    private static boolean originalNoPhysics;
    private static boolean manualRestoreAvailable;

    private static boolean f8WasDown;
    private static boolean f9WasDown;
    private static boolean f10WasDown;

    private static BufferedWriter logWriter;
    private static Path logPath;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabClient::onClientTick);
    }

    private static void onClientTick(Minecraft client) {
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            closeLogQuietly();
            state = State.IDLE;
            return;
        }

        var window = client.getWindow();
        boolean f8Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F8);
        boolean f9Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F9);
        boolean f10Down = InputConstants.isKeyDown(window, GLFW.GLFW_KEY_F10);

        if (f8Down && !f8WasDown) {
            if (state == State.IDLE) {
                startScan(player);
            } else {
                message(player, "PhaseLab is already running. F10 aborts.", false);
            }
        }

        if (f9Down && !f9WasDown) {
            if (state == State.IDLE) {
                applyBest(player);
            } else {
                message(player, "Finish or abort the current scan first.", false);
            }
        }

        if (f10Down && !f10WasDown) {
            if (state != State.IDLE || manualRestoreAvailable) {
                restore(player, "Restored test position.");
            }
        }

        f8WasDown = f8Down;
        f9WasDown = f9Down;
        f10WasDown = f10Down;

        switch (state) {
            case SETTLING -> tickSettling(player);
            case HOLDING -> tickHolding(player);
            case APPLYING_BEST -> tickApplyingBest(player);
            case IDLE -> {
            }
        }
    }

    private static void startScan(LocalPlayer player) {
        scanOrigin = player.position();
        restorePoint = scanOrigin;
        originalNoPhysics = player.noPhysics;
        manualRestoreAvailable = false;
        bestAcceptedDistance = -1.0D;
        attemptIndex = 0;
        calculateDirection(player);
        openLog();
        beginAttempt(player);
        message(player, "PhaseLab scan started. F10 aborts.", false);
    }

    private static void calculateDirection(LocalPlayer player) {
        double radians = Math.toRadians(player.getYRot());
        directionX = -Math.sin(radians);
        directionZ = Math.cos(radians);
        double length = Math.sqrt(directionX * directionX + directionZ * directionZ);
        if (length > 0.0D) {
            directionX /= length;
            directionZ /= length;
        }
    }

    private static void beginAttempt(LocalPlayer player) {
        currentDistance = START_DISTANCE + (attemptIndex * STEP_DISTANCE);
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        player.setPos(scanOrigin.x, scanOrigin.y, scanOrigin.z);
        stateTicks = 0;
        state = State.SETTLING;
        message(player, String.format(Locale.ROOT, "Testing %.2f blocks...", currentDistance), true);
    }

    private static void tickSettling(LocalPlayer player) {
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        stateTicks++;
        if (stateTicks < SETTLE_TICKS) {
            return;
        }

        target = new Vec3(
            scanOrigin.x + directionX * currentDistance,
            scanOrigin.y,
            scanOrigin.z + directionZ * currentDistance
        );
        player.setPos(target.x, target.y, target.z);
        player.setDeltaMovement(Vec3.ZERO);
        stateTicks = 0;
        state = State.HOLDING;
    }

    private static void tickHolding(LocalPlayer player) {
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        stateTicks++;

        Vec3 current = player.position();
        double error = current.distanceTo(target);

        if (error > CORRECTION_ERROR) {
            finishAttempt(player, "REJECTED_CORRECTION", error);
            return;
        }

        if (stateTicks >= HOLD_TICKS) {
            String result = error <= ACCEPT_ERROR ? "ACCEPTED" : "ADJUSTED";
            if ("ACCEPTED".equals(result)) {
                bestAcceptedDistance = Math.max(bestAcceptedDistance, currentDistance);
            }
            finishAttempt(player, result, error);
        }
    }

    private static void finishAttempt(LocalPlayer player, String result, double error) {
        writeLog(result, player.position(), error);
        attemptIndex++;

        double nextDistance = START_DISTANCE + (attemptIndex * STEP_DISTANCE);
        if (nextDistance <= MAX_DISTANCE + 0.0001D) {
            beginAttempt(player);
            return;
        }

        player.setPos(scanOrigin.x, scanOrigin.y, scanOrigin.z);
        player.setDeltaMovement(Vec3.ZERO);
        player.noPhysics = originalNoPhysics;
        state = State.IDLE;
        closeLogQuietly();

        if (bestAcceptedDistance > 0.0D) {
            message(player, String.format(Locale.ROOT,
                "Scan done. Largest accepted offset: %.2f. Press F9 to retry it.", bestAcceptedDistance), false);
        } else {
            message(player, "Scan done. No offset survived the server correction window.", false);
        }

        if (logPath != null) {
            message(player, "Log: " + logPath.toAbsolutePath(), false);
        }
    }

    private static void applyBest(LocalPlayer player) {
        if (bestAcceptedDistance <= 0.0D) {
            message(player, "Run an F8 scan first. No accepted offset is stored.", false);
            return;
        }

        restorePoint = player.position();
        originalNoPhysics = player.noPhysics;
        manualRestoreAvailable = true;
        calculateDirection(player);
        target = new Vec3(
            restorePoint.x + directionX * bestAcceptedDistance,
            restorePoint.y,
            restorePoint.z + directionZ * bestAcceptedDistance
        );
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        player.setPos(target.x, target.y, target.z);
        stateTicks = 0;
        state = State.APPLYING_BEST;
        message(player, String.format(Locale.ROOT,
            "Retrying %.2f blocks. F10 restores.", bestAcceptedDistance), false);
    }

    private static void tickApplyingBest(LocalPlayer player) {
        player.noPhysics = true;
        player.setDeltaMovement(Vec3.ZERO);
        stateTicks++;

        double error = player.position().distanceTo(target);
        if (error > CORRECTION_ERROR) {
            restore(player, "Best offset was corrected by the server.");
            return;
        }

        if (stateTicks >= HOLD_TICKS + 2) {
            player.noPhysics = originalNoPhysics;
            state = State.IDLE;
            message(player, "Offset held through the test window. F10 returns to the start.", false);
        }
    }

    private static void restore(LocalPlayer player, String text) {
        if (restorePoint != null) {
            player.setPos(restorePoint.x, restorePoint.y, restorePoint.z);
            player.setDeltaMovement(Vec3.ZERO);
        }
        player.noPhysics = originalNoPhysics;
        state = State.IDLE;
        manualRestoreAvailable = false;
        closeLogQuietly();
        message(player, text, false);
    }

    private static void openLog() {
        closeLogQuietly();
        try {
            Path directory = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Files.createDirectories(directory);
            String fileName = "scan-" + Instant.now().toString().replace(':', '-') + ".csv";
            logPath = directory.resolve(fileName);
            logWriter = Files.newBufferedWriter(
                logPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE_NEW,
                StandardOpenOption.WRITE
            );
            logWriter.write("distance,target_x,target_y,target_z,final_x,final_y,final_z,error,result\n");
            logWriter.flush();
        } catch (IOException exception) {
            logWriter = null;
            logPath = null;
        }
    }

    private static void writeLog(String result, Vec3 finalPosition, double error) {
        if (logWriter == null || target == null) {
            return;
        }
        try {
            logWriter.write(String.format(Locale.ROOT,
                "%.2f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%s%n",
                currentDistance,
                target.x, target.y, target.z,
                finalPosition.x, finalPosition.y, finalPosition.z,
                error,
                result
            ));
            logWriter.flush();
        } catch (IOException ignored) {
        }
    }

    private static void closeLogQuietly() {
        if (logWriter == null) {
            return;
        }
        try {
            logWriter.close();
        } catch (IOException ignored) {
        } finally {
            logWriter = null;
        }
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }
}
