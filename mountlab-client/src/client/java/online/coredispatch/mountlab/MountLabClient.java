package online.coredispatch.mountlab;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.block.Block;
import net.minecraft.block.Blocks;
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
import net.minecraft.registry.Registries;
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
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class MountLabClient implements ClientModInitializer {
    private enum Phase { IDLE, SWAPPING, LOCKED, POST_DETACH }

    private record TickSample(
        long elapsedNanos, int tick, Phase phase, String event, String packetEvents,
        boolean attached, boolean vehicleExists, boolean graphHasPlayer, int currentVehicleId,
        boolean forwardHeld, int selectedSlot, boolean holdingControl, int swaps,
        double playerX, double playerY, double playerZ,
        double vehicleX, double vehicleY, double vehicleZ,
        double playerStep, double vehicleStep,
        double vehicleMoved, double playerMoved, double couplingError, double separation,
        double playerVelX, double playerVelY, double playerVelZ,
        double vehicleVelX, double vehicleVelY, double vehicleVelZ,
        String playerBlock, String vehicleBlock, boolean obsidianNearby,
        double rawOverlap, double overlapDelta, double bestOverlapDelta
    ) { }

    private static final int[] MAX_SWAP_OPTIONS = {4, 6, 8, 10, 12, 16};
    private static final double[] THRESHOLD_OPTIONS = {0.0, 0.02, 0.04, 0.08, 0.12};
    private static final int FIRST_RETENTION_MILESTONE = 20;
    private static final int SECOND_RETENTION_MILESTONE = 100;
    private static final int LOCKED_WATCH_TICKS = 200;
    private static final int POST_DETACH_TICKS = 40;
    private static final int MAX_TRIAL_TICKS = 320;
    private static final double COUPLING_ERROR_LIMIT = 0.75;
    private static final double JUMP_EVENT_THRESHOLD = 0.75;

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
    private Instant trialStartUtc;
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
    private Vec3d previousVehiclePos = Vec3d.ZERO;
    private Vec3d previousPlayerPos = Vec3d.ZERO;
    private double baselineOverlap;
    private double bestOverlapDelta;
    private Path csvPath;
    private List<TickSample> samples;
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
        if (trialTick >= MAX_TRIAL_TICKS) {
            finish(client, "ABORT_TIMEOUT", true);
            return;
        }

        String packetEvents = PacketProbe.drainEncoded();
        Entity vehicle = client.world.getEntityById(vehicleId);
        Entity currentVehicle = client.player.getVehicle();
        boolean attached = currentVehicle != null && currentVehicle.getId() == vehicleId;

        trialTick++;
        phaseTicks++;
        boolean forwardHeld = isKeyPressed(client, GLFW.GLFW_KEY_W);
        String event = "";

        if (phase == Phase.SWAPPING) {
            if (client.currentScreen != null) {
                finish(client, "ABORT_SCREEN_OPEN", true);
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
            releasedForwardTicks = forwardHeld ? 0 : releasedForwardTicks + 1;
            if (releasedForwardTicks >= 3) {
                finish(client, "ABORT_W_RELEASED", true);
                return;
            }
        }

        if (!attached && phase != Phase.POST_DETACH) {
            phase = Phase.POST_DETACH;
            phaseTicks = 0;
            event = packetEvents.contains("PASSENGERS") ? "DETACH_AFTER_PASSENGERS" : "DETACH_FIRST_SEEN";
            if (originalSlot >= 0 && originalSlot < 9) selectSlot(client, originalSlot);
            status(client, event + " | watching 40 more ticks");
        }

        double rawOverlap = vehicle == null ? 0.0 : solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
        double overlapDelta = Math.max(0.0, rawOverlap - baselineOverlap);
        bestOverlapDelta = Math.max(bestOverlapDelta, overlapDelta);

        if (phase == Phase.SWAPPING && attached && vehicle != null) {
            SteerFlipPlanner.Step step = planner.tick(overlapDelta, THRESHOLD_OPTIONS[thresholdIndex]);
            if (step.target() == SteerFlipPlanner.Target.CONTROL) selectSlot(client, controlSlot);
            else if (step.target() == SteerFlipPlanner.Target.FALLBACK) selectSlot(client, fallbackSlot);

            if (step.lock()) {
                phase = Phase.LOCKED;
                phaseTicks = 0;
                event = step.reason() == SteerFlipPlanner.Reason.OVERLAP
                    ? "LOCK_OVERLAP_" + fmt(overlapDelta)
                    : "LOCK_MAX_SWAPS";
                status(client, "LOCKED | long-tail watch started");
            }
        }

        double playerStep = client.player.getEntityPos().distanceTo(previousPlayerPos);
        double vehicleStep = vehicle == null ? Double.NaN : vehicle.getEntityPos().distanceTo(previousVehiclePos);
        if (event.isEmpty() && playerStep >= JUMP_EVENT_THRESHOLD) event = "PLAYER_STEP_JUMP_" + fmt(playerStep);
        if (event.isEmpty() && !Double.isNaN(vehicleStep) && vehicleStep >= JUMP_EVENT_THRESHOLD) {
            event = "VEHICLE_STEP_JUMP_" + fmt(vehicleStep);
        }

        if (phase == Phase.LOCKED) {
            if (phaseTicks == FIRST_RETENTION_MILESTONE && event.isEmpty()) event = "MILESTONE_RETAINED_20T";
            if (phaseTicks == SECOND_RETENTION_MILESTONE && event.isEmpty()) event = "MILESTONE_RETAINED_100T";
        }

        captureTick(client, vehicle, attached, rawOverlap, overlapDelta, forwardHeld, event, packetEvents,
            playerStep, vehicleStep);
        previousPlayerPos = client.player.getEntityPos();
        if (vehicle != null) previousVehiclePos = vehicle.getEntityPos();

        if (phase == Phase.LOCKED && phaseTicks >= LOCKED_WATCH_TICKS) {
            Vec3d vehicleDelta = vehicle == null ? Vec3d.ZERO : vehicle.getEntityPos().subtract(startVehiclePos);
            Vec3d playerDelta = client.player.getEntityPos().subtract(startPlayerPos);
            double vehicleMoved = vehicleDelta.length();
            double couplingError = vehicle == null ? Double.NaN : vehicleDelta.subtract(playerDelta).length();
            String quality = !Double.isNaN(couplingError) && couplingError <= COUPLING_ERROR_LIMIT ? "COUPLED" : "SUSPECT";
            finish(client, "RETAINED_200T_" + quality + "_VMOVED_" + fmt(vehicleMoved)
                + "_ERROR_" + fmt(couplingError), true);
        } else if (phase == Phase.POST_DETACH && phaseTicks >= POST_DETACH_TICKS) {
            finish(client, "DETACHED_POST40T", false);
        }
    }

    private boolean handleKeys(MinecraftClient client) {
        if (client.getWindow() == null) return false;
        if (client.currentScreen != null && phase == Phase.IDLE) {
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
            status(client, "blocked: approved lab/server only");
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
        previousVehiclePos = startVehiclePos;
        previousPlayerPos = startPlayerPos;
        baselineOverlap = solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
        bestOverlapDelta = 0.0;
        trialId = System.currentTimeMillis();
        trialStartNanos = System.nanoTime();
        trialStartUtc = Instant.now();
        trialTick = 0;
        phaseTicks = 0;
        releasedForwardTicks = 0;
        phase = Phase.SWAPPING;
        planner = new SteerFlipPlanner(intervalTicks, MAX_SWAP_OPTIONS[maxSwapIndex]);
        csvPath = prepareCsvPath();
        samples = new ArrayList<>(MAX_TRIAL_TICKS + 8);
        PacketProbe.start(vehicleId, client.player.getId());

        selectSlot(client, controlSlot);
        captureTick(client, vehicle, true, baselineOverlap, 0.0, true, "START", "", 0.0, 0.0);
        status(client, "RUN " + mountName + " | " + intervalTicks + "t / "
            + MAX_SWAP_OPTIONS[maxSwapIndex] + " swaps | 10s late-detach capture");
        return true;
    }

    private void finish(MinecraftClient client, String result, boolean restoreOriginal) {
        String packetEvents = PacketProbe.drainEncoded();
        Entity vehicle = client.world == null ? null : client.world.getEntityById(vehicleId);
        boolean attached = client.player != null && client.player.getVehicle() != null
            && client.player.getVehicle().getId() == vehicleId;
        if (client.player != null) {
            double raw = vehicle == null || client.world == null ? 0.0
                : solidHorizontalOverlapDepth(client, vehicle.getBoundingBox());
            double playerStep = client.player.getEntityPos().distanceTo(previousPlayerPos);
            double vehicleStep = vehicle == null ? Double.NaN : vehicle.getEntityPos().distanceTo(previousVehiclePos);
            captureTick(client, vehicle, attached, raw, Math.max(0.0, raw - baselineOverlap),
                isKeyPressed(client, GLFW.GLFW_KEY_W), result, packetEvents, playerStep, vehicleStep);
        }

        boolean saved = flushCsv();
        if (restoreOriginal && client.player != null && originalSlot >= 0 && originalSlot < 9) {
            selectSlot(client, originalSlot);
        }
        status(client, result + " | swaps=" + (planner == null ? 0 : planner.swaps())
            + " bestDelta=" + fmt(bestOverlapDelta) + (saved ? "" : " | CSV_WRITE_FAILED"));
        PacketProbe.stop();
        phase = Phase.IDLE;
        planner = null;
        vehicleId = -1;
        samples = null;
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

    private boolean obsidianNearby(MinecraftClient client, Entity vehicle) {
        if (vehicle == null) return false;
        Box box = vehicle.getBoundingBox().expand(0.35);
        int minX = (int) Math.floor(box.minX);
        int minY = (int) Math.floor(box.minY);
        int minZ = (int) Math.floor(box.minZ);
        int maxX = (int) Math.floor(box.maxX);
        int maxY = (int) Math.floor(box.maxY);
        int maxZ = (int) Math.floor(box.maxZ);
        BlockPos.Mutable pos = new BlockPos.Mutable();
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    pos.set(x, y, z);
                    Block block = client.world.getBlockState(pos).getBlock();
                    if (block == Blocks.OBSIDIAN || block == Blocks.CRYING_OBSIDIAN) return true;
                }
            }
        }
        return false;
    }

    private String blockAt(MinecraftClient client, Vec3d pos) {
        Block block = client.world.getBlockState(BlockPos.ofFloored(pos)).getBlock();
        return Registries.BLOCK.getId(block).toString();
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
            return dir.resolve("late-detach-" + trialId + ".csv");
        } catch (IOException e) {
            return null;
        }
    }

    private void captureTick(MinecraftClient client, Entity vehicle, boolean attached,
                             double rawOverlap, double overlapDelta, boolean forwardHeld,
                             String event, String packetEvents, double playerStep, double vehicleStep) {
        if (samples == null || client.player == null) return;
        boolean holding = client.player.getMainHandStack().isOf(controlItem);
        boolean vehicleExists = vehicle != null;
        boolean graphHasPlayer = vehicle != null && vehicle.getPassengerList().contains(client.player);
        int currentVehicleId = client.player.getVehicle() == null ? -1 : client.player.getVehicle().getId();
        Vec3d playerPos = client.player.getEntityPos();
        Vec3d playerDelta = playerPos.subtract(startPlayerPos);
        Vec3d playerVelocity = client.player.getVelocity();

        Vec3d vehiclePos = vehicle == null ? null : vehicle.getEntityPos();
        Vec3d vehicleDelta = vehicle == null ? null : vehiclePos.subtract(startVehiclePos);
        Vec3d vehicleVelocity = vehicle == null ? Vec3d.ZERO : vehicle.getVelocity();
        double vehicleMoved = vehicleDelta == null ? Double.NaN : vehicleDelta.length();
        double couplingError = vehicleDelta == null ? Double.NaN : vehicleDelta.subtract(playerDelta).length();
        double separation = vehiclePos == null ? Double.NaN : vehiclePos.distanceTo(playerPos);

        samples.add(new TickSample(
            System.nanoTime() - trialStartNanos, trialTick, phase, sanitize(event), sanitize(packetEvents),
            attached, vehicleExists, graphHasPlayer, currentVehicleId,
            forwardHeld, client.player.getInventory().getSelectedSlot(), holding,
            planner == null ? 0 : planner.swaps(),
            playerPos.x, playerPos.y, playerPos.z,
            vehiclePos == null ? Double.NaN : vehiclePos.x,
            vehiclePos == null ? Double.NaN : vehiclePos.y,
            vehiclePos == null ? Double.NaN : vehiclePos.z,
            playerStep, vehicleStep,
            vehicleMoved, playerDelta.length(), couplingError, separation,
            playerVelocity.x, playerVelocity.y, playerVelocity.z,
            vehicleVelocity.x, vehicleVelocity.y, vehicleVelocity.z,
            blockAt(client, playerPos), vehiclePos == null ? "missing" : blockAt(client, vehiclePos),
            obsidianNearby(client, vehicle), rawOverlap, overlapDelta, bestOverlapDelta
        ));
    }

    private boolean flushCsv() {
        if (csvPath == null || samples == null || trialStartUtc == null) return false;
        StringBuilder csv = new StringBuilder(Math.max(32_768, samples.size() * 650));
        csv.append("utc,elapsed_ns,trial,tick,phase,event,packet_events,mount,vehicle_id,attached,vehicle_exists,graph_has_player,current_vehicle_id,forward_held,selected_slot,holding_control,swaps,interval,max_swaps,threshold,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,player_step,vehicle_step,vehicle_moved,player_moved,coupling_error,separation,player_vel_x,player_vel_y,player_vel_z,vehicle_vel_x,vehicle_vel_y,vehicle_vel_z,player_block,vehicle_block,obsidian_nearby,raw_horizontal_overlap,overlap_delta,best_overlap_delta\n");
        for (TickSample sample : samples) {
            csv.append(String.join(",",
                trialStartUtc.plusNanos(sample.elapsedNanos()).toString(), Long.toString(sample.elapsedNanos()),
                Long.toString(trialId), Integer.toString(sample.tick()), sample.phase().name(), sample.event(),
                sample.packetEvents(), mountName == null ? "unknown" : mountName, Integer.toString(vehicleId),
                Boolean.toString(sample.attached()), Boolean.toString(sample.vehicleExists()),
                Boolean.toString(sample.graphHasPlayer()), Integer.toString(sample.currentVehicleId()),
                Boolean.toString(sample.forwardHeld()), Integer.toString(sample.selectedSlot()),
                Boolean.toString(sample.holdingControl()), Integer.toString(sample.swaps()),
                Integer.toString(intervalTicks), Integer.toString(MAX_SWAP_OPTIONS[maxSwapIndex]),
                fmt(THRESHOLD_OPTIONS[thresholdIndex]),
                fmt(sample.playerX()), fmt(sample.playerY()), fmt(sample.playerZ()),
                fmt(sample.vehicleX()), fmt(sample.vehicleY()), fmt(sample.vehicleZ()),
                fmt(sample.playerStep()), fmt(sample.vehicleStep()),
                fmt(sample.vehicleMoved()), fmt(sample.playerMoved()), fmt(sample.couplingError()), fmt(sample.separation()),
                fmt(sample.playerVelX()), fmt(sample.playerVelY()), fmt(sample.playerVelZ()),
                fmt(sample.vehicleVelX()), fmt(sample.vehicleVelY()), fmt(sample.vehicleVelZ()),
                sanitize(sample.playerBlock()), sanitize(sample.vehicleBlock()), Boolean.toString(sample.obsidianNearby()),
                fmt(sample.rawOverlap()), fmt(sample.overlapDelta()), fmt(sample.bestOverlapDelta())
            )).append('\n');
        }
        try {
            Files.writeString(csvPath, csv.toString(), StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
            return true;
        } catch (IOException ignored) {
            return false;
        }
    }

    private void status(MinecraftClient client, String message) {
        if (client.player != null) client.player.sendMessage(Text.literal("[MountLab] " + message), true);
    }

    private static String sanitize(String value) {
        if (value == null) return "";
        return value.replace(',', '|').replace('\n', ' ').replace('\r', ' ');
    }

    private static String fmt(double value) {
        return String.format(Locale.ROOT, "%.5f", value);
    }
}
