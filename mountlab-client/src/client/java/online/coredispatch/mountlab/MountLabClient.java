package online.coredispatch.mountlab;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ServerInfo;
import net.minecraft.client.util.InputUtil;
import net.minecraft.entity.Entity;
import net.minecraft.entity.passive.PigEntity;
import net.minecraft.entity.passive.StriderEntity;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.network.packet.c2s.play.UpdateSelectedSlotC2SPacket;
import net.minecraft.text.Text;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Box;
import net.minecraft.util.math.Vec3d;
import net.minecraft.util.shape.VoxelShape;
import org.lwjgl.glfw.GLFW;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Locale;

public final class MountLabClient implements ClientModInitializer {
    private enum Phase { IDLE, SWAPPING, LOCKED }

    private static final int[] MAX_SWAP_OPTIONS = {4, 6, 8, 10, 12, 16};
    private static final double[] THRESHOLD_OPTIONS = {0.0, 0.02, 0.04, 0.08, 0.12};
    private static final int RETENTION_TICKS = 20;
    private static final int MAX_TRIAL_TICKS = 200;
    private static final double COUPLING_ERROR_LIMIT = 0.75;

    private Phase phase = Phase.IDLE;
    private int intervalTicks = 2;
    private int maxSwapIndex = 2;
    private int thresholdIndex = 2;

    private boolean lastP;
    private boolean lastO;
    private boolean lastK;
    private boolean lastL;

    private long trialId;
    private long trialStartNanos;
    private int trialTick;
    private int phaseTicks;
    private int releasedForwardTicks;
    private int vehicleId = -1;
    private int originalSlot = -1;
    private int controlSlot = -1;
    private int fallbackSlot = -1;
    private Item controlItem;
    private String mountName;
    private Vec3d startVehiclePos = Vec3d.ZERO;
    private Vec3d startPlayerPos = Vec3d.ZERO;
    private double baselineOverlap;
    private double bestOverlapDelta;
    private Path csvPath;
    private StringBuilder csvBuffer;
    private SteerFlipPlanner planner;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(this::tick);
    }

    private void tick(MinecraftClient client) {
        boolean startedThisTick = handleKeys(client);
        if (startedThisTick || phase == Phase.IDLE) return;

        if (client.player == null || client.world == null || !allowedLab(client)) {
            finish(client, "ABORT_CONTEXT", true);
            return;
        }
        if (client.currentScreen != null) {
            finish(client, "ABORT_SCREEN_OPEN", true);
            return;
        }
        if (trialTick >= MAX_TRIAL_TICKS) {
            finish(client, "ABORT_TIMEOUT", true);
            return;
        }
        if (!client.player.getInventory().getStack(controlSlot).isOf(controlItem)) {
            finish(client, "ABORT_CONTROL_ITEM_MOVED", true);
            return;
        }
        if (client.player.getInventory().getStack(fallbackSlot).isOf(controlItem)) {
            finish(client, "ABORT_FALLBACK_BECAME_CONTROL", true);
            return;
        }

        Entity vehicle = client.player.getVehicle();
        if (vehicle == null || vehicle.getId() != vehicleId) {
            finish(client, "DETACHED", true);
            return;
        }

        boolean forwardHeld = isKeyPressed(client, GLFW.GLFW_KEY_W);
        releasedForwardTicks = forwardHeld ? 0 : releasedForwardTicks + 1;
        if (releasedForwardTicks >= 3) {
            finish(client, "ABORT_W_RELEASED", true);
            return;
        }

        trialTick++;
        phaseTicks++;
        double rawOverlap = solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
        double overlapDelta = Math.max(0.0, rawOverlap - baselineOverlap);
        bestOverlapDelta = Math.max(bestOverlapDelta, overlapDelta);
        String event = "";

        if (phase == Phase.SWAPPING) {
            SteerFlipPlanner.Step step = planner.tick(overlapDelta, THRESHOLD_OPTIONS[thresholdIndex]);
            if (step.target() == SteerFlipPlanner.Target.CONTROL) selectSlot(client, controlSlot);
            else if (step.target() == SteerFlipPlanner.Target.FALLBACK) selectSlot(client, fallbackSlot);

            if (step.lock()) {
                phase = Phase.LOCKED;
                phaseTicks = 0;
                event = step.reason() == SteerFlipPlanner.Reason.OVERLAP
                    ? "LOCK_OVERLAP_" + fmt(overlapDelta)
                    : "LOCK_MAX_SWAPS";
                status(client, "LOCKED control item | " + event);
            }
        }

        appendTick(client, vehicle, rawOverlap, overlapDelta, forwardHeld, event);

        if (phase == Phase.LOCKED && phaseTicks >= RETENTION_TICKS) {
            Vec3d vehicleDelta = vehicle.getEntityPos().subtract(startVehiclePos);
            Vec3d playerDelta = client.player.getEntityPos().subtract(startPlayerPos);
            double vehicleMoved = vehicleDelta.length();
            double couplingError = vehicleDelta.subtract(playerDelta).length();
            String quality = couplingError <= COUPLING_ERROR_LIMIT ? "COUPLED" : "SUSPECT";
            finish(client, "RETAINED_20T_" + quality + "_VMOVED_" + fmt(vehicleMoved)
                + "_ERROR_" + fmt(couplingError), false);
        }
    }

    /** Returns true only when a new trial starts, preventing interval=1 from swapping twice in the start tick. */
    private boolean handleKeys(MinecraftClient client) {
        if (client.getWindow() == null) return false;
        if (client.currentScreen != null) {
            lastP = lastO = lastK = lastL = false;
            return false;
        }

        boolean p = isKeyPressed(client, GLFW.GLFW_KEY_P);
        boolean o = isKeyPressed(client, GLFW.GLFW_KEY_O);
        boolean k = isKeyPressed(client, GLFW.GLFW_KEY_K);
        boolean l = isKeyPressed(client, GLFW.GLFW_KEY_L);
        boolean started = false;

        if (p && !lastP) {
            if (phase == Phase.IDLE) started = start(client);
            else finish(client, "MANUAL_STOP", true);
        }
        if (o && !lastO && phase == Phase.IDLE) {
            intervalTicks = intervalTicks % 3 + 1;
            status(client, "interval=" + intervalTicks + "t");
        }
        if (k && !lastK && phase == Phase.IDLE) {
            maxSwapIndex = (maxSwapIndex + 1) % MAX_SWAP_OPTIONS.length;
            status(client, "maxSwaps=" + MAX_SWAP_OPTIONS[maxSwapIndex]);
        }
        if (l && !lastL && phase == Phase.IDLE) {
            thresholdIndex = (thresholdIndex + 1) % THRESHOLD_OPTIONS.length;
            status(client, "overlapDeltaStop=" + fmt(THRESHOLD_OPTIONS[thresholdIndex]));
        }

        lastP = p;
        lastO = o;
        lastK = k;
        lastL = l;
        return started;
    }

    private boolean start(MinecraftClient client) {
        if (client.player == null || client.world == null) {
            status(client, "join the lab first");
            return false;
        }
        if (!allowedLab(client)) {
            status(client, "blocked: singleplayer/private-IP lab only");
            return false;
        }
        if (!isKeyPressed(client, GLFW.GLFW_KEY_W)) {
            status(client, "hold W before pressing P");
            return false;
        }

        Entity vehicle = client.player.getVehicle();
        if (vehicle instanceof PigEntity) {
            controlItem = Items.CARROT_ON_A_STICK;
            mountName = "pig";
        } else if (vehicle instanceof StriderEntity) {
            controlItem = Items.WARPED_FUNGUS_ON_A_STICK;
            mountName = "strider";
        } else {
            status(client, "mount a pig or strider first");
            return false;
        }

        controlSlot = findHotbarSlot(client, controlItem);
        if (controlSlot < 0) {
            status(client, "control stick must be in hotbar");
            return false;
        }
        fallbackSlot = findFallbackSlot(client, controlSlot);
        if (fallbackSlot < 0) {
            status(client, "need another hotbar slot to swap into");
            return false;
        }

        originalSlot = client.player.getInventory().getSelectedSlot();
        vehicleId = vehicle.getId();
        startVehiclePos = vehicle.getEntityPos();
        startPlayerPos = client.player.getEntityPos();
        baselineOverlap = solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
        bestOverlapDelta = 0.0;
        trialId = System.currentTimeMillis();
        trialStartNanos = System.nanoTime();
        trialTick = 0;
        phaseTicks = 0;
        releasedForwardTicks = 0;
        phase = Phase.SWAPPING;
        planner = new SteerFlipPlanner(intervalTicks, MAX_SWAP_OPTIONS[maxSwapIndex]);
        csvPath = prepareCsvPath();
        csvBuffer = new StringBuilder(16_384);
        csvBuffer.append("utc,elapsed_ns,trial,tick,phase,event,mount,vehicle_id,attached,forward_held,selected_slot,holding_control,swaps,interval,max_swaps,threshold,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,vehicle_moved,player_moved,coupling_error,separation,raw_horizontal_overlap,overlap_delta,best_overlap_delta\n");

        selectSlot(client, controlSlot);
        appendTick(client, vehicle, baselineOverlap, 0.0, true, "START");
        status(client, "RUN " + mountName + " | " + intervalTicks + "t / "
            + MAX_SWAP_OPTIONS[maxSwapIndex] + " swaps / delta stop " + fmt(THRESHOLD_OPTIONS[thresholdIndex]));
        return true;
    }

    private void finish(MinecraftClient client, String result, boolean restoreOriginal) {
        Entity vehicle = client.player == null ? null : client.player.getVehicle();
        if (vehicle != null) {
            double raw = client.world == null ? 0.0 : solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
            appendTick(client, vehicle, raw, Math.max(0.0, raw - baselineOverlap), isKeyPressed(client, GLFW.GLFW_KEY_W), result);
        } else {
            appendDetached(client, result);
        }

        flushCsv();
        if (restoreOriginal && client.player != null && originalSlot >= 0 && originalSlot < 9) {
            selectSlot(client, originalSlot);
        }
        status(client, result + " | swaps=" + (planner == null ? 0 : planner.swaps())
            + " bestDelta=" + fmt(bestOverlapDelta));
        phase = Phase.IDLE;
        planner = null;
        vehicleId = -1;
        csvBuffer = null;
    }

    private boolean isKeyPressed(MinecraftClient client, int key) {
        return client.getWindow() != null && InputUtil.isKeyPressed(client.getWindow(), key);
    }

    private void selectSlot(MinecraftClient client, int slot) {
        if (client.player == null || slot < 0 || slot > 8) return;
        if (client.player.getInventory().getSelectedSlot() == slot) return;
        client.player.getInventory().setSelectedSlot(slot);
        if (client.getNetworkHandler() != null) {
            client.getNetworkHandler().sendPacket(new UpdateSelectedSlotC2SPacket(slot));
        }
    }

    private int findHotbarSlot(MinecraftClient client, Item target) {
        for (int slot = 0; slot < 9; slot++) {
            ItemStack stack = client.player.getInventory().getStack(slot);
            if (stack.isOf(target)) return slot;
        }
        return -1;
    }

    private int findFallbackSlot(MinecraftClient client, int excluded) {
        for (int slot = 0; slot < 9; slot++) {
            if (slot != excluded && client.player.getInventory().getStack(slot).isEmpty()) return slot;
        }
        for (int slot = 0; slot < 9; slot++) {
            if (slot != excluded && !client.player.getInventory().getStack(slot).isOf(controlItem)) return slot;
        }
        return -1;
    }

    private double solidHorizontalOverlapDepth(MinecraftClient client, Box entityBox) {
        double best = 0.0;
        int minX = (int) Math.floor(entityBox.minX);
        int minY = (int) Math.floor(entityBox.minY);
        int minZ = (int) Math.floor(entityBox.minZ);
        int maxX = (int) Math.floor(entityBox.maxX - 1.0e-7);
        int maxY = (int) Math.floor(entityBox.maxY - 1.0e-7);
        int maxZ = (int) Math.floor(entityBox.maxZ - 1.0e-7);

        BlockPos.Mutable pos = new BlockPos.Mutable();
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    pos.set(x, y, z);
                    VoxelShape shape = client.world.getBlockState(pos).getCollisionShape(client.world, pos);
                    if (shape.isEmpty()) continue;
                    for (Box local : shape.getBoundingBoxes()) {
                        Box blockBox = local.offset(pos);
                        double ox = Math.min(entityBox.maxX, blockBox.maxX) - Math.max(entityBox.minX, blockBox.minX);
                        double oy = Math.min(entityBox.maxY, blockBox.maxY) - Math.max(entityBox.minY, blockBox.minY);
                        double oz = Math.min(entityBox.maxZ, blockBox.maxZ) - Math.max(entityBox.minZ, blockBox.minZ);
                        best = Math.max(best, MountLabMath.horizontalPenetration(ox, oy, oz));
                    }
                }
            }
        }
        return best;
    }

    private boolean allowedLab(MinecraftClient client) {
        if (client.isInSingleplayer()) return true;
        ServerInfo info = client.getCurrentServerEntry();
        return info != null && LabAddressPolicy.isPrivateLabAddress(info.address);
    }

    private Path prepareCsvPath() {
        try {
            Path dir = FabricLoader.getInstance().getGameDir().resolve("mountlab");
            Files.createDirectories(dir);
            return dir.resolve("steerflip-" + trialId + ".csv");
        } catch (IOException e) {
            return null;
        }
    }

    private void appendTick(MinecraftClient client, Entity vehicle, double rawOverlap, double overlapDelta,
                            boolean forwardHeld, String event) {
        if (csvBuffer == null || client.player == null) return;
        boolean holding = client.player.getMainHandStack().isOf(controlItem);
        Vec3d vehicleDelta = vehicle.getEntityPos().subtract(startVehiclePos);
        Vec3d playerDelta = client.player.getEntityPos().subtract(startPlayerPos);
        double couplingError = vehicleDelta.subtract(playerDelta).length();
        double separation = vehicle.getEntityPos().distanceTo(client.player.getEntityPos());
        csvBuffer.append(String.join(",",
            Instant.now().toString(), Long.toString(System.nanoTime() - trialStartNanos), Long.toString(trialId),
            Integer.toString(trialTick), phase.name(), event, mountName, Integer.toString(vehicle.getId()),
            Boolean.toString(client.player.getVehicle() == vehicle), Boolean.toString(forwardHeld),
            Integer.toString(client.player.getInventory().getSelectedSlot()), Boolean.toString(holding),
            Integer.toString(planner == null ? 0 : planner.swaps()), Integer.toString(intervalTicks),
            Integer.toString(MAX_SWAP_OPTIONS[maxSwapIndex]), fmt(THRESHOLD_OPTIONS[thresholdIndex]),
            fmt(client.player.getX()), fmt(client.player.getY()), fmt(client.player.getZ()),
            fmt(vehicle.getX()), fmt(vehicle.getY()), fmt(vehicle.getZ()),
            fmt(vehicleDelta.length()), fmt(playerDelta.length()), fmt(couplingError), fmt(separation),
            fmt(rawOverlap), fmt(overlapDelta), fmt(bestOverlapDelta))).append('\n');
    }

    private void appendDetached(MinecraftClient client, String event) {
        if (csvBuffer == null) return;
        String playerX = "NaN";
        String playerY = "NaN";
        String playerZ = "NaN";
        String playerMoved = "NaN";
        int selected = -1;
        if (client.player != null) {
            playerX = fmt(client.player.getX());
            playerY = fmt(client.player.getY());
            playerZ = fmt(client.player.getZ());
            playerMoved = fmt(client.player.getEntityPos().distanceTo(startPlayerPos));
            selected = client.player.getInventory().getSelectedSlot();
        }
        csvBuffer.append(String.join(",",
            Instant.now().toString(), Long.toString(System.nanoTime() - trialStartNanos), Long.toString(trialId),
            Integer.toString(trialTick), phase.name(), event, mountName == null ? "unknown" : mountName,
            Integer.toString(vehicleId), "false", "false", Integer.toString(selected), "false",
            Integer.toString(planner == null ? 0 : planner.swaps()), Integer.toString(intervalTicks),
            Integer.toString(MAX_SWAP_OPTIONS[maxSwapIndex]), fmt(THRESHOLD_OPTIONS[thresholdIndex]),
            playerX, playerY, playerZ, "NaN", "NaN", "NaN", "NaN", playerMoved,
            "NaN", "NaN", "0", "0", fmt(bestOverlapDelta))).append('\n');
    }

    private void flushCsv() {
        if (csvPath == null || csvBuffer == null) return;
        try {
            Files.writeString(csvPath, csvBuffer.toString(), StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        } catch (IOException ignored) { }
    }

    private void status(MinecraftClient client, String message) {
        if (client.player != null) client.player.sendMessage(Text.literal("[MountLab] " + message), true);
    }

    private static String fmt(double value) {
        return String.format(Locale.ROOT, "%.5f", value);
    }
}
