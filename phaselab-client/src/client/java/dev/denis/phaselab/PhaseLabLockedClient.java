package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import dev.denis.phaselab.net.LabMessagePayload;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import org.lwjgl.glfw.GLFW;

/**
 * Bounded active runner for the paired PhaseLab server plugin.
 *
 * The client only automates ordinary movement key states. It never mutates
 * player/vehicle position and never sends custom movement packets. Active mode
 * remains unavailable until the server grants a short-lived, player-bound,
 * region-bound authorization through the PhaseLab control channel.
 */
public final class PhaseLabLockedClient implements ClientModInitializer {
    private static final String VERSION = "5.1.0";
    private static final String[] SCENARIOS = {
        "PRESS_FORWARD",
        "PULSE_FORWARD",
        "DISMOUNT_EDGE",
        "BRAKE_RELEASE"
    };

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "lab_runner")
    );

    private static KeyMapping scenarioKey;
    private static KeyMapping runKey;
    private static int scenarioIndex;
    private static boolean running;
    private static int scenarioTick;
    private static Authorization authorization;
    private static Object lastConnection;

    @Override
    public void onInitializeClient() {
        PayloadTypeRegistry.playS2C().register(LabMessagePayload.TYPE, LabMessagePayload.CODEC);
        PayloadTypeRegistry.playC2S().register(LabMessagePayload.TYPE, LabMessagePayload.CODEC);
        ClientPlayNetworking.registerGlobalReceiver(LabMessagePayload.TYPE, (payload, context) ->
            context.client().execute(() -> handleServerMessage(context.client(), payload.message()))
        );

        scenarioKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.active_scenario", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_F6, CATEGORY
        ));
        runKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
            "key.phaselab.active_run", InputConstants.Type.KEYSYM, GLFW.GLFW_KEY_F12, CATEGORY
        ));

        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabLockedClient::tickClient);
    }

    private static void tickClient(Minecraft client) {
        Object connection = client.getConnection();
        if (connection != lastConnection) {
            stopLocalKeys(client);
            running = false;
            authorization = null;
            lastConnection = connection;
        }

        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            stopLocalKeys(client);
            running = false;
            authorization = null;
            return;
        }

        while (scenarioKey.consumeClick()) {
            if (running) {
                message(player, "Abort the current scenario with F12 before changing it.", false);
            } else {
                scenarioIndex = (scenarioIndex + 1) % SCENARIOS.length;
                message(player, "Active scenario: " + scenario(), true);
            }
        }

        while (runKey.consumeClick()) {
            if (running) {
                abort(client, player, "manual_abort");
            } else {
                start(player);
            }
        }

        if (!running) {
            return;
        }
        if (!authorizationValid(player)) {
            abort(client, player, "authorization_expired_or_region_left");
            return;
        }
        runScenario(client, player);
    }

    private static void start(LocalPlayer player) {
        if (!authorizationValid(player)) {
            message(player, "Run /phaselab quickstart on the test server first.", false);
            return;
        }
        if (!player.isPassenger()) {
            message(player, "Mount the test boat/vehicle before pressing F12.", false);
            return;
        }

        String command = "START|" + authorization.nonce() + "|" + scenario();
        if (!send(command)) {
            message(player, "PhaseLab server plugin was not detected on this connection.", false);
            return;
        }

        scenarioTick = 0;
        running = true;
        message(player, "RUNNING " + scenario() + ". F12 aborts.", false);
    }

    private static void runScenario(Minecraft client, LocalPlayer player) {
        scenarioTick++;
        boolean finish = false;

        switch (scenario()) {
            case "PRESS_FORWARD" -> {
                client.options.keyUp.setDown(scenarioTick <= 160);
                client.options.keyShift.setDown(false);
                finish = scenarioTick >= 180;
            }
            case "PULSE_FORWARD" -> {
                client.options.keyUp.setDown(scenarioTick <= 180 && scenarioTick % 12 < 9);
                client.options.keyShift.setDown(false);
                finish = scenarioTick >= 200;
            }
            case "DISMOUNT_EDGE" -> {
                client.options.keyUp.setDown(scenarioTick <= 80);
                client.options.keyShift.setDown(scenarioTick == 12 || scenarioTick == 13);
                finish = scenarioTick >= 100;
            }
            case "BRAKE_RELEASE" -> {
                client.options.keyUp.setDown(scenarioTick <= 80);
                client.options.keyShift.setDown(false);
                finish = scenarioTick >= 130;
            }
            default -> finish = true;
        }

        if (finish) {
            stopLocalKeys(client);
            send("FINISH|" + authorization.nonce() + "|" + scenario());
            running = false;
            scenarioTick = 0;
            message(player, "Scenario input complete. Waiting for server verdict.", false);
        }
    }

    private static void abort(Minecraft client, LocalPlayer player, String reason) {
        stopLocalKeys(client);
        Authorization auth = authorization;
        if (auth != null) {
            send("ABORT|" + auth.nonce() + "|" + clean(reason));
        }
        running = false;
        scenarioTick = 0;
        message(player, "Active scenario aborted: " + reason, false);
    }

    private static void stopLocalKeys(Minecraft client) {
        client.options.keyUp.setDown(false);
        client.options.keyShift.setDown(false);
    }

    private static boolean authorizationValid(LocalPlayer player) {
        Authorization auth = authorization;
        if (auth == null || System.currentTimeMillis() >= auth.expiresEpochMs()) {
            return false;
        }
        if (!player.getUUID().toString().equals(auth.playerUuid())) {
            return false;
        }
        int x = player.blockPosition().getX();
        int y = player.blockPosition().getY();
        int z = player.blockPosition().getZ();
        return x >= auth.minX() && x <= auth.maxX()
            && y >= auth.minY() && y <= auth.maxY()
            && z >= auth.minZ() && z <= auth.maxZ();
    }

    private static void handleServerMessage(Minecraft client, String raw) {
        LocalPlayer player = client.player;
        if (player == null || raw == null || raw.isBlank()) {
            return;
        }

        String[] parts = raw.split("\\|", -1);
        switch (parts[0]) {
            case "AUTH" -> handleAuthorization(player, parts);
            case "ACK" -> message(player, "Server armed " + value(parts, 3) + ".", false);
            case "RESULT" -> {
                stopLocalKeys(client);
                running = false;
                scenarioTick = 0;
                String verdict = value(parts, 2);
                String detail = value(parts, 3);
                message(player, "SERVER VERDICT: " + verdict + (detail.isBlank() ? "" : " | " + detail), false);
            }
            case "LOCKED", "ERROR" -> {
                stopLocalKeys(client);
                running = false;
                scenarioTick = 0;
                message(player, parts[0] + ": " + value(parts, 1), false);
            }
            default -> {
            }
        }
    }

    private static void handleAuthorization(LocalPlayer player, String[] parts) {
        if (parts.length != 11 || !"1".equals(parts[1])) {
            message(player, "Rejected malformed PhaseLab authorization.", false);
            return;
        }

        try {
            String playerUuid = parts[2];
            long expires = Long.parseLong(parts[3]);
            int minX = Integer.parseInt(parts[4]);
            int minY = Integer.parseInt(parts[5]);
            int minZ = Integer.parseInt(parts[6]);
            int maxX = Integer.parseInt(parts[7]);
            int maxY = Integer.parseInt(parts[8]);
            int maxZ = Integer.parseInt(parts[9]);
            String nonce = parts[10];
            long now = System.currentTimeMillis();

            boolean saneRegion = minX <= maxX && minY <= maxY && minZ <= maxZ
                && maxX - minX <= 128
                && maxY - minY <= 96
                && maxZ - minZ <= 128;
            if (!player.getUUID().toString().equals(playerUuid)
                || expires <= now
                || expires > now + 1_900_000L
                || !saneRegion
                || nonce.length() < 16
                || nonce.length() > 64) {
                message(player, "Rejected PhaseLab authorization: invalid identity, expiry, or region.", false);
                return;
            }

            authorization = new Authorization(
                playerUuid,
                expires,
                minX,
                minY,
                minZ,
                maxX,
                maxY,
                maxZ,
                nonce
            );
            send("READY|" + nonce + "|" + VERSION);
            message(player, "PHASELAB READY for " + ((expires - now) / 1000L) + "s. F6 selects, F12 runs.", false);
        } catch (RuntimeException exception) {
            message(player, "Rejected PhaseLab authorization: " + exception.getClass().getSimpleName(), false);
        }
    }

    private static boolean send(String message) {
        try {
            ClientPlayNetworking.send(new LabMessagePayload(message));
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private static String scenario() {
        return SCENARIOS[scenarioIndex];
    }

    private static String value(String[] parts, int index) {
        return index >= 0 && index < parts.length ? parts[index] : "";
    }

    private static String clean(String value) {
        return value == null ? "" : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
    }

    private record Authorization(
        String playerUuid,
        long expiresEpochMs,
        int minX,
        int minY,
        int minZ,
        int maxX,
        int maxY,
        int maxZ,
        String nonce
    ) {
    }
}
