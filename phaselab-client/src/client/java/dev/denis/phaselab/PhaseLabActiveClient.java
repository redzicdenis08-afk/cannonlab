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

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * Authorized active PhaseLab campaign client.
 *
 * The client only automates ordinary key states. It cannot arm itself: the
 * paired server plugin must issue a short-lived player/region-bound session.
 * Every case is judged and rolled back by the server before the next case.
 */
public final class PhaseLabActiveClient implements ClientModInitializer {
    private static final String VERSION = "6.0.0";
    private static final int CASE_RUNTIME_CAP = 220;
    private static final int BETWEEN_CASE_TICKS = 24;
    private static final DateTimeFormatter FILE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss");

    private static final List<CaseSpec> QUICK_CASES = List.of(
        new CaseSpec("Q01_FORWARD_SHORT", "PRESS_FORWARD", 90, 0, 0),
        new CaseSpec("Q02_FORWARD_LONG", "PRESS_FORWARD", 170, 0, 0),
        new CaseSpec("Q03_PULSE_MEDIUM", "PULSE_FORWARD", 190, 12, 9),
        new CaseSpec("Q04_LEFT_PRESSURE", "FORWARD_LEFT", 170, 0, 0),
        new CaseSpec("Q05_RIGHT_PRESSURE", "FORWARD_RIGHT", 170, 0, 0),
        new CaseSpec("Q06_BRAKE_RELEASE", "BRAKE_RELEASE", 140, 72, 26)
    );

    private static final List<CaseSpec> DEEP_CASES = List.of(
        new CaseSpec("D01_FORWARD_60", "PRESS_FORWARD", 80, 0, 0),
        new CaseSpec("D02_FORWARD_100", "PRESS_FORWARD", 120, 0, 0),
        new CaseSpec("D03_FORWARD_160", "PRESS_FORWARD", 180, 0, 0),
        new CaseSpec("D04_PULSE_FAST", "PULSE_FORWARD", 190, 8, 6),
        new CaseSpec("D05_PULSE_MEDIUM", "PULSE_FORWARD", 200, 12, 9),
        new CaseSpec("D06_PULSE_SLOW", "PULSE_FORWARD", 210, 18, 12),
        new CaseSpec("D07_FORWARD_LEFT", "FORWARD_LEFT", 180, 0, 0),
        new CaseSpec("D08_FORWARD_RIGHT", "FORWARD_RIGHT", 180, 0, 0),
        new CaseSpec("D09_BRAKE_EARLY", "BRAKE_RELEASE", 135, 55, 22),
        new CaseSpec("D10_BRAKE_LATE", "BRAKE_RELEASE", 155, 85, 28),
        new CaseSpec("D11_OSCILLATE_FAST", "FORWARD_BACK_PULSE", 190, 8, 0),
        new CaseSpec("D12_OSCILLATE_SLOW", "FORWARD_BACK_PULSE", 205, 14, 0),
        new CaseSpec("D13_DISMOUNT_EARLY", "DISMOUNT_EDGE", 125, 34, 0),
        new CaseSpec("D14_DISMOUNT_MIDDLE", "DISMOUNT_EDGE", 145, 58, 0),
        new CaseSpec("D15_DISMOUNT_LATE", "DISMOUNT_EDGE", 170, 82, 0),
        new CaseSpec("D16_IDLE_CONTROL", "IDLE_CONTROL", 100, 0, 0)
    );

    private static final KeyMapping.Category CATEGORY = KeyMapping.Category.register(
        Identifier.fromNamespaceAndPath("phaselab", "authorized_campaign")
    );

    private static KeyMapping modeKey;
    private static KeyMapping runKey;
    private static CampaignMode mode = CampaignMode.DEEP;
    private static Authorization authorization;
    private static Object lastConnection;

    private static boolean campaignRunning;
    private static boolean caseRunning;
    private static boolean waitingForAck;
    private static boolean waitingForResult;
    private static int cooldownTicks;
    private static int caseTick;
    private static int caseIndex;
    private static String campaignId;
    private static CaseSpec currentCase;
    private static CaseSpec lastWinningCase;
    private static List<CaseSpec> campaignCases = List.of();

    private static final BufferedWriter[] WRITERS = new BufferedWriter[2];
    private static final Path[] OUTPUT_PATHS = new Path[2];
    private static Path summaryPath;

    @Override
    public void onInitializeClient() {
        PayloadTypeRegistry.playS2C().register(LabMessagePayload.TYPE, LabMessagePayload.CODEC);
        PayloadTypeRegistry.playC2S().register(LabMessagePayload.TYPE, LabMessagePayload.CODEC);
        ClientPlayNetworking.registerGlobalReceiver(LabMessagePayload.TYPE, (payload, context) ->
            context.client().execute(() -> handleServerMessage(context.client(), payload.message()))
        );

        modeKey = register("key.phaselab.active_scenario", GLFW.GLFW_KEY_F6);
        runKey = register("key.phaselab.active_run", GLFW.GLFW_KEY_F12);
        ClientTickEvents.END_CLIENT_TICK.register(PhaseLabActiveClient::tickClient);
    }

    private static KeyMapping register(String key, int code) {
        return KeyBindingHelper.registerKeyBinding(new KeyMapping(
            key, InputConstants.Type.KEYSYM, code, CATEGORY
        ));
    }

    private static void tickClient(Minecraft client) {
        Object connection = client.getConnection();
        if (connection != lastConnection) {
            abortLocal(client, "connection_changed", false);
            authorization = null;
            lastConnection = connection;
        }

        LocalPlayer player = client.player;
        if (player == null || client.level == null) {
            abortLocal(client, "world_unavailable", false);
            authorization = null;
            return;
        }

        while (modeKey.consumeClick()) {
            if (campaignRunning) {
                message(player, "Abort the campaign with F12 before changing mode.", false);
            } else {
                mode = mode.next();
                message(player, "Campaign mode: " + mode, true);
            }
        }

        while (runKey.consumeClick()) {
            if (campaignRunning) {
                abortCampaign(client, player, "manual_abort");
            } else {
                startCampaign(client, player);
            }
        }

        if (!campaignRunning) {
            return;
        }
        if (!authorizationValid(player)) {
            abortCampaign(client, player, "authorization_expired_or_region_left");
            return;
        }

        if (cooldownTicks > 0) {
            cooldownTicks--;
            if (cooldownTicks == 0 && !waitingForAck && !waitingForResult && !caseRunning) {
                startNextCase(client, player);
            }
            return;
        }

        if (caseRunning) {
            tickCase(client, player);
        }
    }

    private static void startCampaign(Minecraft client, LocalPlayer player) {
        if (!authorizationValid(player)) {
            message(player, "Mount the lab boat, face the wall, then run /phaselab quickstart.", false);
            return;
        }
        if (!player.isPassenger()) {
            message(player, "Mount the authorized lab vehicle before pressing F12.", false);
            return;
        }

        campaignCases = switch (mode) {
            case QUICK -> QUICK_CASES;
            case DEEP -> DEEP_CASES;
            case REPLAY -> lastWinningCase == null ? List.of() : List.of(lastWinningCase);
        };
        if (campaignCases.isEmpty()) {
            message(player, "No reproduced case exists to replay yet. Use QUICK or DEEP.", false);
            return;
        }

        campaignId = FILE_TIME.format(LocalDateTime.now()) + "-" + UUID.randomUUID().toString().substring(0, 8);
        if (!openOutputs(player)) {
            return;
        }

        campaignRunning = true;
        caseRunning = false;
        waitingForAck = false;
        waitingForResult = false;
        caseIndex = 0;
        caseTick = 0;
        cooldownTicks = 0;
        write("CAMPAIGN_START", "", "", "mode=" + mode + ";cases=" + campaignCases.size());
        message(player, "ACTIVE CAMPAIGN " + mode + " started with " + campaignCases.size() + " cases. F12 aborts.", false);
        startNextCase(client, player);
    }

    private static void startNextCase(Minecraft client, LocalPlayer player) {
        stopKeys(client);
        if (!campaignRunning) {
            return;
        }
        if (caseIndex >= campaignCases.size()) {
            finishCampaign(player, "NO_REPRODUCTION", "all_cases_completed");
            return;
        }
        if (!player.isPassenger()) {
            cooldownTicks = 10;
            message(player, "Waiting for server rollback/remount before case " + (caseIndex + 1) + ".", true);
            return;
        }

        currentCase = campaignCases.get(caseIndex);
        caseTick = 0;
        waitingForAck = true;
        waitingForResult = false;
        caseRunning = false;
        write("CASE_REQUEST", currentCase.id(), "", "family=" + currentCase.family());
        boolean sent = send("START|" + authorization.nonce() + "|" + currentCase.id() + "|" + currentCase.family());
        if (!sent) {
            abortCampaign(client, player, "server_channel_unavailable");
        }
    }

    private static void tickCase(Minecraft client, LocalPlayer player) {
        caseTick++;
        applyCase(client, currentCase, caseTick);

        if (!player.isPassenger() && !"DISMOUNT_EDGE".equals(currentCase.family())) {
            write("CLIENT_DISMOUNT", currentCase.id(), "", "tick=" + caseTick);
        }

        if (caseTick >= Math.min(CASE_RUNTIME_CAP, currentCase.durationTicks())) {
            stopKeys(client);
            caseRunning = false;
            waitingForResult = true;
            write("CASE_INPUT_DONE", currentCase.id(), "", "ticks=" + caseTick);
            send("FINISH|" + authorization.nonce() + "|" + currentCase.id());
        }
    }

    private static void applyCase(Minecraft client, CaseSpec spec, int tick) {
        stopKeys(client);
        switch (spec.family()) {
            case "PRESS_FORWARD" -> client.options.keyUp.setDown(tick <= spec.durationTicks() - 20);
            case "PULSE_FORWARD" -> {
                int period = Math.max(4, spec.paramA());
                int onTicks = Math.max(2, Math.min(period - 1, spec.paramB()));
                client.options.keyUp.setDown(tick <= spec.durationTicks() - 20 && tick % period < onTicks);
            }
            case "FORWARD_LEFT" -> {
                client.options.keyUp.setDown(tick <= spec.durationTicks() - 20);
                client.options.keyLeft.setDown(tick <= spec.durationTicks() - 20);
            }
            case "FORWARD_RIGHT" -> {
                client.options.keyUp.setDown(tick <= spec.durationTicks() - 20);
                client.options.keyRight.setDown(tick <= spec.durationTicks() - 20);
            }
            case "BRAKE_RELEASE" -> {
                int forwardUntil = Math.max(20, spec.paramA());
                int brakeTicks = Math.max(5, spec.paramB());
                client.options.keyUp.setDown(tick <= forwardUntil);
                client.options.keyDown.setDown(tick > forwardUntil && tick <= forwardUntil + brakeTicks);
            }
            case "FORWARD_BACK_PULSE" -> {
                int period = Math.max(6, spec.paramA());
                boolean forward = (tick / period) % 2 == 0;
                client.options.keyUp.setDown(tick <= spec.durationTicks() - 20 && forward);
                client.options.keyDown.setDown(tick <= spec.durationTicks() - 20 && !forward);
            }
            case "DISMOUNT_EDGE" -> {
                client.options.keyUp.setDown(tick <= spec.durationTicks() - 25);
                int dismountTick = Math.max(10, spec.paramA());
                client.options.keyShift.setDown(tick == dismountTick || tick == dismountTick + 1);
            }
            case "IDLE_CONTROL" -> {
            }
            default -> {
            }
        }
    }

    private static void handleServerMessage(Minecraft client, String raw) {
        LocalPlayer player = client.player;
        if (player == null || raw == null || raw.isBlank()) {
            return;
        }
        String[] parts = raw.split("\\|", -1);
        switch (value(parts, 0)) {
            case "AUTH" -> handleAuthorization(player, parts);
            case "ACK" -> handleAck(player, parts);
            case "RESULT" -> handleResult(client, player, parts);
            case "LOCKED", "ERROR" -> abortCampaign(client, player, value(parts, 0) + ":" + value(parts, 1));
            default -> {
            }
        }
    }

    private static void handleAuthorization(LocalPlayer player, String[] parts) {
        if (parts.length != 13 || !"2".equals(parts[1])) {
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
            String axis = parts[11];
            double barrier = Double.parseDouble(parts[12]);
            long now = System.currentTimeMillis();

            boolean saneRegion = minX <= maxX && minY <= maxY && minZ <= maxZ
                && maxX - minX <= 96 && maxY - minY <= 64 && maxZ - minZ <= 96;
            if (!player.getUUID().toString().equals(playerUuid)
                || expires <= now || expires > now + 1_900_000L
                || !saneRegion || nonce.length() < 16 || nonce.length() > 64
                || !("X".equals(axis) || "Z".equals(axis)) || !Double.isFinite(barrier)) {
                message(player, "Rejected PhaseLab authorization: invalid identity, expiry, or region.", false);
                return;
            }

            authorization = new Authorization(
                playerUuid, expires, minX, minY, minZ, maxX, maxY, maxZ, nonce, axis, barrier
            );
            send("READY|" + nonce + "|" + VERSION);
            message(player, "AUTHORIZED LAB READY for " + ((expires - now) / 1000L) + "s. F6 mode, F12 campaign.", false);
        } catch (RuntimeException exception) {
            message(player, "Rejected PhaseLab authorization: " + exception.getClass().getSimpleName(), false);
        }
    }

    private static void handleAck(LocalPlayer player, String[] parts) {
        if (!campaignRunning || currentCase == null) {
            return;
        }
        String kind = value(parts, 2);
        String caseId = value(parts, 3);
        if ("START".equals(kind) && currentCase.id().equals(caseId)) {
            waitingForAck = false;
            caseRunning = true;
            caseTick = 0;
            write("CASE_START", currentCase.id(), "", "family=" + currentCase.family());
            message(player, "CASE " + (caseIndex + 1) + "/" + campaignCases.size() + ": " + currentCase.id(), true);
        }
    }

    private static void handleResult(Minecraft client, LocalPlayer player, String[] parts) {
        stopKeys(client);
        if (!campaignRunning || currentCase == null) {
            return;
        }
        String verdict = value(parts, 2);
        String detail = value(parts, 3);
        String caseId = value(parts, 4);
        if (!currentCase.id().equals(caseId)) {
            abortCampaign(client, player, "result_case_mismatch");
            return;
        }

        waitingForResult = false;
        waitingForAck = false;
        caseRunning = false;
        write("CASE_RESULT", caseId, verdict, detail);

        if ("REPRODUCED".equals(verdict)) {
            lastWinningCase = currentCase;
            finishCampaign(player, "REPRODUCED", "winner=" + currentCase.id() + ";" + detail);
            message(player, "SERVER-AUTHORITATIVE REPRODUCTION: " + currentCase.id(), false);
            return;
        }

        if ("SAFETY_ABORT".equals(verdict) || "EXPIRED".equals(verdict)) {
            abortCampaign(client, player, verdict + ":" + detail);
            return;
        }

        caseIndex++;
        currentCase = null;
        cooldownTicks = BETWEEN_CASE_TICKS;
    }

    private static void abortCampaign(Minecraft client, LocalPlayer player, String reason) {
        Authorization auth = authorization;
        if (campaignRunning && auth != null) {
            send("ABORT|" + auth.nonce() + "|" + clean(reason));
            write("CAMPAIGN_ABORT", currentCase == null ? "" : currentCase.id(), "ABORTED", reason);
        }
        abortLocal(client, reason, true);
        if (player != null) {
            message(player, "Campaign aborted: " + reason, false);
        }
    }

    private static void abortLocal(Minecraft client, String reason, boolean writeSummary) {
        stopKeys(client);
        if (campaignRunning && writeSummary) {
            writeSummary("ABORTED", reason);
        }
        closeOutputs();
        campaignRunning = false;
        caseRunning = false;
        waitingForAck = false;
        waitingForResult = false;
        cooldownTicks = 0;
        caseTick = 0;
        caseIndex = 0;
        currentCase = null;
    }

    private static void finishCampaign(LocalPlayer player, String verdict, String detail) {
        write("CAMPAIGN_FINISH", currentCase == null ? "" : currentCase.id(), verdict, detail);
        writeSummary(verdict, detail);
        closeOutputs();
        campaignRunning = false;
        caseRunning = false;
        waitingForAck = false;
        waitingForResult = false;
        cooldownTicks = 0;
        caseTick = 0;
        currentCase = null;
        message(player, "CAMPAIGN RESULT: " + verdict + " | " + detail, false);
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

    private static void stopKeys(Minecraft client) {
        if (client == null || client.options == null) {
            return;
        }
        client.options.keyUp.setDown(false);
        client.options.keyDown.setDown(false);
        client.options.keyLeft.setDown(false);
        client.options.keyRight.setDown(false);
        client.options.keyShift.setDown(false);
        client.options.keyJump.setDown(false);
    }

    private static boolean send(String message) {
        try {
            ClientPlayNetworking.send(new LabMessagePayload(message));
            return true;
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    private static boolean openOutputs(LocalPlayer player) {
        closeOutputs();
        Path gameDir = Minecraft.getInstance().gameDirectory.toPath();
        Path configDir = FabricLoader.getInstance().getConfigDir().resolve("phaselab");
        OUTPUT_PATHS[0] = gameDir.resolve("PHASELAB_CAMPAIGN_LATEST.csv");
        OUTPUT_PATHS[1] = configDir.resolve("campaign-" + campaignId + ".csv");
        summaryPath = gameDir.resolve("PHASELAB_CAMPAIGN_SUMMARY.txt");
        try {
            Files.createDirectories(configDir);
            for (int i = 0; i < WRITERS.length; i++) {
                WRITERS[i] = Files.newBufferedWriter(
                    OUTPUT_PATHS[i], StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
                );
                WRITERS[i].write("utc_timestamp,campaign_id,mode,case_index,case_id,family,event,verdict,detail");
                WRITERS[i].newLine();
                WRITERS[i].flush();
            }
            return true;
        } catch (IOException exception) {
            closeOutputs();
            message(player, "Could not create campaign evidence: " + exception.getMessage(), false);
            return false;
        }
    }

    private static synchronized void write(String event, String caseId, String verdict, String detail) {
        if (campaignId == null) {
            return;
        }
        String family = currentCase == null ? "" : currentCase.family();
        String row = csv(Instant.now().toString()) + "," + csv(campaignId) + "," + csv(mode.name()) + ","
            + caseIndex + "," + csv(caseId) + "," + csv(family) + "," + csv(event) + ","
            + csv(verdict) + "," + csv(clean(detail));
        for (BufferedWriter writer : WRITERS) {
            if (writer == null) {
                continue;
            }
            try {
                writer.write(row);
                writer.newLine();
                writer.flush();
            } catch (IOException ignored) {
            }
        }
    }

    private static void writeSummary(String verdict, String detail) {
        if (summaryPath == null) {
            return;
        }
        String winner = lastWinningCase == null ? "none" : lastWinningCase.id();
        String text = "PhaseLab Campaign v" + VERSION + "\n"
            + "campaign_id=" + campaignId + "\n"
            + "mode=" + mode + "\n"
            + "verdict=" + verdict + "\n"
            + "detail=" + clean(detail) + "\n"
            + "winning_case=" + winner + "\n"
            + "completed_cases=" + caseIndex + "\n";
        try {
            Files.writeString(
                summaryPath, text, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE
            );
        } catch (IOException ignored) {
        }
    }

    private static synchronized void closeOutputs() {
        for (int i = 0; i < WRITERS.length; i++) {
            if (WRITERS[i] != null) {
                try {
                    WRITERS[i].close();
                } catch (IOException ignored) {
                }
                WRITERS[i] = null;
            }
        }
    }

    private static String value(String[] parts, int index) {
        return index >= 0 && index < parts.length ? parts[index] : "";
    }

    private static String clean(String value) {
        return value == null ? "" : value.replace('|', '/').replace('\n', ' ').replace('\r', ' ');
    }

    private static String csv(String value) {
        String safe = value == null ? "" : value.replace("\"", "\"\"");
        return "\"" + safe + "\"";
    }

    private static void message(LocalPlayer player, String text, boolean actionBar) {
        if (player != null) {
            player.displayClientMessage(Component.literal("[PhaseLab] " + text), actionBar);
        }
    }

    private enum CampaignMode {
        QUICK,
        DEEP,
        REPLAY;

        CampaignMode next() {
            return values()[(ordinal() + 1) % values().length];
        }
    }

    private record CaseSpec(String id, String family, int durationTicks, int paramA, int paramB) {
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
        String nonce,
        String barrierAxis,
        double barrierCoordinate
    ) {
    }
}