package dev.denis.phaselab;

import com.mojang.blaze3d.platform.InputConstants;
import dev.denis.phaselab.net.LabMessagePayload;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.Identifier;
import org.lwjgl.glfw.GLFW;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;
import java.util.Base64;

/**
 * Lab-locked active runner. It only automates ordinary key states after a
 * short-lived Ed25519 authorization from the paired PhaseLab server plugin.
 * It never sends custom movement packets or mutates player/vehicle position.
 */
public final class PhaseLabLockedClient implements ClientModInitializer {
    private static final String VERSION = "5.0.0";
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
    private static long clientTick;
    private static Authorization authorization;
    private static PublicKey trustedPublicKey;
    private static String expectedServerId;
    private static String trustError = "not_loaded";

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
        loadTrustFiles();
    }

    private static void tickClient(Minecraft client) {
        clientTick++;
        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            stopLocalKeys(client);
            running = false;
            authorization = null;
            return;
        }

        if (trustedPublicKey == null && clientTick % 100L == 0L) {
            loadTrustFiles();
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
        if (trustedPublicKey == null || expectedServerId == null) {
            message(player, "LOCKED: install server-id.txt and server-public-key.txt in config/phaselab (" + trustError + ").", false);
            return;
        }
        if (!authorizationValid(player)) {
            message(player, "LOCKED: run /phaselab authorize on the paired test server first.", false);
            return;
        }
        if (!player.isPassenger()) {
            message(player, "Mount the test boat/vehicle before starting the active scenario.", false);
            return;
        }

        scenarioTick = 0;
        running = true;
        send("START|" + authorization.serverId() + "|" + authorization.nonce() + "|" + scenario());
        message(player, "RUNNING " + scenario() + " under signed lab authorization. F12 aborts.", false);
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
            send("FINISH|" + authorization.serverId() + "|" + authorization.nonce() + "|" + scenario());
            running = false;
            message(player, "Scenario input complete. Waiting for server verdict.", false);
        }
    }

    private static void abort(Minecraft client, LocalPlayer player, String reason) {
        stopLocalKeys(client);
        if (authorization != null) {
            send("ABORT|" + authorization.serverId() + "|" + authorization.nonce() + "|" + clean(reason));
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
        if (auth == null || trustedPublicKey == null || expectedServerId == null) {
            return false;
        }
        long now = System.currentTimeMillis();
        if (now >= auth.expiresEpochMs() || !expectedServerId.equals(auth.serverId())) {
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
            case "ACK" -> message(player, "Server armed scenario " + value(parts, 3) + ".", false);
            case "RESULT" -> {
                stopLocalKeys(client);
                running = false;
                String verdict = value(parts, 2);
                String detail = value(parts, 3);
                message(player, "SERVER VERDICT: " + verdict + (detail.isBlank() ? "" : " | " + detail), false);
            }
            case "LOCKED", "ERROR" -> {
                stopLocalKeys(client);
                running = false;
                message(player, parts[0] + ": " + value(parts, 1), false);
            }
            default -> {
            }
        }
    }

    private static void handleAuthorization(LocalPlayer player, String[] parts) {
        if (parts.length != 13 || !"1".equals(parts[1])) {
            message(player, "Rejected malformed PhaseLab authorization.", false);
            return;
        }
        if (trustedPublicKey == null || expectedServerId == null) {
            message(player, "Authorization received, but the local server lock is not installed.", false);
            return;
        }

        try {
            String canonical = String.join("|", Arrays.copyOf(parts, 12));
            Signature verifier = Signature.getInstance("Ed25519");
            verifier.initVerify(trustedPublicKey);
            verifier.update(canonical.getBytes(StandardCharsets.UTF_8));
            if (!verifier.verify(Base64.getDecoder().decode(parts[12]))) {
                message(player, "Rejected PhaseLab authorization: invalid signature.", false);
                return;
            }

            String serverId = parts[2];
            String playerUuid = parts[3];
            long expires = Long.parseLong(parts[4]);
            long now = System.currentTimeMillis();
            if (!expectedServerId.equals(serverId)
                || !player.getUUID().toString().equals(playerUuid)
                || expires <= now
                || expires > now + 300_000L) {
                message(player, "Rejected PhaseLab authorization: identity or expiry mismatch.", false);
                return;
            }

            authorization = new Authorization(
                serverId,
                playerUuid,
                expires,
                Integer.parseInt(parts[5]),
                Integer.parseInt(parts[6]),
                Integer.parseInt(parts[7]),
                Integer.parseInt(parts[8]),
                Integer.parseInt(parts[9]),
                Integer.parseInt(parts[10]),
                parts[11]
            );
            send("READY|" + serverId + "|" + parts[11] + "|" + VERSION);
            message(player, "SIGNED LAB AUTH ACTIVE for " + ((expires - now) / 1000L) + "s. F6 scenario, F12 run.", false);
        } catch (Exception exception) {
            message(player, "Rejected PhaseLab authorization: " + exception.getClass().getSimpleName(), false);
        }
    }

    private static void loadTrustFiles() {
        try {
            Path dir = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
            Path serverIdPath = dir.resolve("server-id.txt");
            Path publicKeyPath = dir.resolve("server-public-key.txt");
            if (!Files.isRegularFile(serverIdPath) || !Files.isRegularFile(publicKeyPath)) {
                expectedServerId = null;
                trustedPublicKey = null;
                trustError = "missing_lock_files";
                return;
            }

            expectedServerId = Files.readString(serverIdPath, StandardCharsets.UTF_8).trim();
            String encoded = Files.readString(publicKeyPath, StandardCharsets.UTF_8)
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "")
                .replaceAll("\\s", "");
            byte[] keyBytes = Base64.getDecoder().decode(encoded);
            trustedPublicKey = KeyFactory.getInstance("Ed25519").generatePublic(new X509EncodedKeySpec(keyBytes));
            trustError = "none";
        } catch (Exception exception) {
            expectedServerId = null;
            trustedPublicKey = null;
            trustError = exception.getClass().getSimpleName() + ":" + clean(exception.getMessage());
        }
    }

    private static void send(String message) {
        try {
            ClientPlayNetworking.send(new LabMessagePayload(message));
        } catch (RuntimeException ignored) {
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
        String serverId,
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
