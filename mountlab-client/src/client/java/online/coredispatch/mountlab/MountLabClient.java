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

    private Phase phase = Phase.IDLE;
    private int intervalTicks = 2;
    private int maxSwapIndex = 2;
    private int thresholdIndex = 2;

    private boolean lastP;
    private boolean lastO;
    private boolean lastK;
    private boolean lastL;

    private long trialId;
    private int trialTick;
    private int swaps;
    private int phaseTicks;
    private int vehicleId;
    private int originalSlot;
    private int controlSlot;
    private int fallbackSlot;
    private boolean nextControl;
    private Item controlItem;
    private String mountName;
    private Vec3d startVehiclePos = Vec3d.ZERO;
    private Vec3d startPlayerPos = Vec3d.ZERO;
    private double bestOverlap;
    private Path csvPath;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(this::tick);
    }

    private void tick(MinecraftClient client) {
        handleKeys(client);
        if (phase == Phase.IDLE) return;

        if (client.player == null || client.world == null || !allowedLab(client)) {
            finish(client, "ABORT_CONTEXT", true);
            return;
        }

        Entity vehicle = client.player.getVehicle();
        if (vehicle == null || vehicle.getId() != vehicleId) {
            finish(client, "DETACHED", false);
            return;
        }

        trialTick++;
        phaseTicks++;
        double overlap = solidOverlapDepth(client, vehicle.getBoundingBox());
        bestOverlap = Math.max(bestOverlap, overlap);
        appendTick(client, vehicle, overlap, "");

        if (phase == Phase.SWAPPING) {
            double threshold = THRESHOLD_OPTIONS[thresholdIndex];
            if (swaps >= 2 && overlap >= threshold && threshold > 0.0) {
                enterLock(client, "OVERLAP_" + fmt(overlap));
                return;
            }

            if (swaps >= MAX_SWAP_OPTIONS[maxSwapIndex]) {
                enterLock(client, "MAX_SWAPS");
                return;
            }

            if (phaseTicks >= intervalTicks) {
                phaseTicks = 0;
                selectSlot(client, nextControl ? controlSlot : fallbackSlot);
                nextControl = !nextControl;
                swaps++;
            }
        } else if (phase == Phase.LOCKED && phaseTicks >= 20) {
            double moved = vehicle.getEntityPos().distanceTo(startVehiclePos);
            finish(client, "RETAINED_20T_MOVED_" + fmt(moved), false);
        }
    }

    private void handleKeys(MinecraftClient client) {
        if (client.getWindow() == null) return;
        boolean p = InputUtil.isKeyPressed(client.getWindow(), GLFW.GLFW_KEY_P);
        boolean o = InputUtil.isKeyPressed(client.getWindow(), GLFW.GLFW_KEY_O);
        boolean k = InputUtil.isKeyPressed(client.getWindow(), GLFW.GLFW_KEY_K);
        boolean l = InputUtil.isKeyPressed(client.getWindow(), GLFW.GLFW_KEY_L);

        if (p && !lastP) {
            if (phase == Phase.IDLE) start(client);
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
            status(client, "overlapStop=" + fmt(THRESHOLD_OPTIONS[thresholdIndex]));
        }

        lastP = p;
        lastO = o;
        lastK = k;
        lastL = l;
    }

    private void start(MinecraftClient client) {
        if (client.player == null || client.world == null) {
            status(client, "join the lab first");
            return;
        }
        if (!allowedLab(client)) {
            status(client, "blocked: singleplayer/private-IP lab only");
            return;
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
            return;
        }

        controlSlot = findHotbarSlot(client, controlItem);
        if (controlSlot < 0) {
            status(client, "control stick must be in hotbar");
            return;
        }
        fallbackSlot = findFallbackSlot(client, controlSlot);
        if (fallbackSlot < 0) {
            status(client, "need another hotbar slot to swap into");
            return;
        }

        originalSlot = client.player.getInventory().getSelectedSlot();
        vehicleId = vehicle.getId();
        startVehiclePos = vehicle.getEntityPos();
        startPlayerPos = client.player.getEntityPos();
        trialId = System.currentTimeMillis();
        trialTick = 0;
        swaps = 0;
        phaseTicks = 0;
        bestOverlap = 0.0;
        nextControl = false;
        phase = Phase.SWAPPING;
        csvPath = prepareCsv();

        selectSlot(client, controlSlot);
        appendEvent(client, vehicle, "START");
        status(client, "RUN " + mountName + " | hold W | " + intervalTicks + "t / "
            + MAX_SWAP_OPTIONS[maxSwapIndex] + " swaps / stop " + fmt(THRESHOLD_OPTIONS[thresholdIndex]));
    }

    private void enterLock(MinecraftClient client, String reason) {
        phase = Phase.LOCKED;
        phaseTicks = 0;
        selectSlot(client, controlSlot);
        Entity vehicle = client.player == null ? null : client.player.getVehicle();
        if (vehicle != null) appendEvent(client, vehicle, "LOCK_" + reason);
        status(client, "LOCKED control item | " + reason);
    }

    private void finish(MinecraftClient client, String result, boolean restoreOriginal) {
        Entity vehicle = client.player == null ? null : client.player.getVehicle();
        if (vehicle != null) appendEvent(client, vehicle, result);
        else appendDetached(client, result);

        if (restoreOriginal && client.player != null && originalSlot >= 0 && originalSlot < 9) {
            selectSlot(client, originalSlot);
        }
        status(client, result + " | swaps=" + swaps + " bestOverlap=" + fmt(bestOverlap));
        phase = Phase.IDLE;
        vehicleId = -1;
    }

    private void selectSlot(MinecraftClient client, int slot) {
        if (client.player == null || slot < 0 || slot > 8) return;
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
            if (slot != excluded) return slot;
        }
        return -1;
    }

    private double solidOverlapDepth(MinecraftClient client, Box entityBox) {
        double best = 0.0;
        int minX = (int) Math.floor(entityBox.minX);
        int minY = (int) Math.floor(entityBox.minY);
        int minZ = (int) Math.floor(entityBox.minZ);
        int maxX = (int) Math.floor(entityBox.maxX);
        int maxY = (int) Math.floor(entityBox.maxY);
        int maxZ = (int) Math.floor(entityBox.maxZ);

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
                        if (ox > 0 && oy > 0 && oz > 0) best = Math.max(best, Math.min(ox, Math.min(oy, oz)));
                    }
                }
            }
        }
        return best;
    }

    private boolean allowedLab(MinecraftClient client) {
        if (client.isInSingleplayer()) return true;
        ServerInfo info = client.getCurrentServerEntry();
        if (info == null || info.address == null) return false;
        String host = info.address.toLowerCase(Locale.ROOT).trim();
        int colon = host.lastIndexOf(':');
        if (colon > 0 && host.indexOf(':') == colon) host = host.substring(0, colon);
        if (host.equals("localhost") || host.equals("127.0.0.1") || host.equals("0.0.0.0") || host.endsWith(".local")) return true;
        if (host.startsWith("10.") || host.startsWith("192.168.")) return true;
        if (host.startsWith("172.")) {
            String[] parts = host.split("\\.");
            if (parts.length > 1) {
                try {
                    int second = Integer.parseInt(parts[1]);
                    return second >= 16 && second <= 31;
                } catch (NumberFormatException ignored) { }
            }
        }
        return false;
    }

    private Path prepareCsv() {
        try {
            Path dir = FabricLoader.getInstance().getGameDir().resolve("mountlab");
            Files.createDirectories(dir);
            Path file = dir.resolve("steerflip-" + trialId + ".csv");
            Files.writeString(file,
                "utc,trial,tick,phase,event,mount,vehicle_id,attached,selected_slot,holding_control,swaps,interval,max_swaps,threshold,player_x,player_y,player_z,vehicle_x,vehicle_y,vehicle_z,vehicle_moved,player_moved,overlap,best_overlap\n",
                StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
            return file;
        } catch (IOException e) {
            return null;
        }
    }

    private void appendTick(MinecraftClient client, Entity vehicle, double overlap, String event) {
        if (csvPath == null || client.player == null) return;
        boolean holding = client.player.getMainHandStack().isOf(controlItem);
        String line = String.join(",",
            Instant.now().toString(), Long.toString(trialId), Integer.toString(trialTick), phase.name(), event,
            mountName, Integer.toString(vehicle.getId()), Boolean.toString(client.player.getVehicle() == vehicle),
            Integer.toString(client.player.getInventory().getSelectedSlot()), Boolean.toString(holding), Integer.toString(swaps),
            Integer.toString(intervalTicks), Integer.toString(MAX_SWAP_OPTIONS[maxSwapIndex]), fmt(THRESHOLD_OPTIONS[thresholdIndex]),
            fmt(client.player.getX()), fmt(client.player.getY()), fmt(client.player.getZ()),
            fmt(vehicle.getX()), fmt(vehicle.getY()), fmt(vehicle.getZ()),
            fmt(vehicle.getEntityPos().distanceTo(startVehiclePos)), fmt(client.player.getEntityPos().distanceTo(startPlayerPos)),
            fmt(overlap), fmt(bestOverlap)) + "\n";
        write(line);
    }

    private void appendEvent(MinecraftClient client, Entity vehicle, String event) {
        appendTick(client, vehicle, solidOverlapDepth(client, vehicle.getBoundingBox()), event);
    }

    private void appendDetached(MinecraftClient client, String event) {
        if (csvPath == null || client.player == null) return;
        String line = String.join(",",
            Instant.now().toString(), Long.toString(trialId), Integer.toString(trialTick), phase.name(), event,
            mountName == null ? "unknown" : mountName, Integer.toString(vehicleId), "false",
            Integer.toString(client.player.getInventory().getSelectedSlot()), "false", Integer.toString(swaps),
            Integer.toString(intervalTicks), Integer.toString(MAX_SWAP_OPTIONS[maxSwapIndex]), fmt(THRESHOLD_OPTIONS[thresholdIndex]),
            fmt(client.player.getX()), fmt(client.player.getY()), fmt(client.player.getZ()),
            "NaN", "NaN", "NaN", "NaN", fmt(client.player.getEntityPos().distanceTo(startPlayerPos)),
            "0", fmt(bestOverlap)) + "\n";
        write(line);
    }

    private void write(String line) {
        try {
            Files.writeString(csvPath, line, StandardCharsets.UTF_8, StandardOpenOption.CREATE, StandardOpenOption.APPEND);
        } catch (IOException ignored) { }
    }

    private void status(MinecraftClient client, String message) {
        if (client.player != null) client.player.sendMessage(Text.literal("[MountLab] " + message), true);
    }

    private static String fmt(double value) {
        return String.format(Locale.ROOT, "%.5f", value);
    }
}
