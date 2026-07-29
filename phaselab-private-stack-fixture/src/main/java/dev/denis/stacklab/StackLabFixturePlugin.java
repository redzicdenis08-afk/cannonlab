package dev.denis.stacklab;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.Registry;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.Chest;
import org.bukkit.block.Hopper;
import org.bukkit.block.data.Directional;
import org.bukkit.block.data.type.EndPortalFrame;
import org.bukkit.enchantments.Enchantment;
import org.bukkit.entity.Item;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockMultiPlaceEvent;
import org.bukkit.event.block.BlockPistonExtendEvent;
import org.bukkit.event.block.BlockPistonRetractEvent;
import org.bukkit.event.entity.EntityExplodeEvent;
import org.bukkit.event.entity.ItemSpawnEvent;
import org.bukkit.event.inventory.InventoryMoveItemEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

public final class StackLabFixturePlugin extends JavaPlugin implements Listener {
    private static final int Y = 65;
    private final Gson gson = new Gson();
    private Path evidencePath;
    private boolean cancelPortalMultiPlace;

    @Override
    public void onEnable() {
        try {
            Files.createDirectories(getDataFolder().toPath());
            evidencePath = getDataFolder().toPath().resolve("evidence.jsonl");
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to prepare StackLab evidence directory", exception);
        }
        Bukkit.getPluginManager().registerEvents(this, this);
        var command = getCommand("stacklab");
        if (command == null) {
            throw new IllegalStateException("stacklab command missing from plugin.yml");
        }
        command.setExecutor((sender, ignored, label, args) -> {
            if (args.length == 0) {
                sender.sendMessage("Usage: /" + label + " <build|reset|snapshot|give|tick>");
                return true;
            }
            try {
                return switch (args[0].toLowerCase()) {
                    case "build" -> build(sender);
                    case "portalbuild" -> portalBuild(sender);
                    case "reset" -> reset(sender);
                    case "snapshot" -> snapshot(sender, args.length > 1 ? args[1] : "manual");
                    case "portalsnapshot" -> portalSnapshot(sender, args.length > 1 ? args[1] : "manual");
                    case "give" -> give(sender, args);
                    case "tick" -> tick(sender, args);
                    case "cancelportal" -> cancelPortal(sender, args);
                    default -> false;
                };
            } catch (RuntimeException exception) {
                sender.sendMessage("StackLab error: " + exception.getMessage());
                getLogger().severe("Command failed: " + exception);
                return true;
            }
        });
        writeEvent("plugin_enable", Map.of("version", getPluginMeta().getVersion()));
    }

    private boolean build(org.bukkit.command.CommandSender sender) {
        World world = requireWorld();
        clearArena(world);

        // Source block is attacker-side X=15; connected targets begin in the neighboring X=16 claim.
        set(world, 15, Y, 0, Material.OAK_LOG);
        set(world, 16, Y, 0, Material.OAK_LOG);
        set(world, 17, Y, 0, Material.OAK_LOG);
        set(world, 16, Y + 1, 0, Material.OAK_LEAVES);
        set(world, 17, Y + 1, 0, Material.OAK_LEAVES);

        // 3x3 mining surface straddling the same claim boundary.
        for (int x = 15; x <= 17; x++) {
            for (int y = Y; y <= Y + 2; y++) {
                set(world, x, y, 4, Material.STONE);
            }
        }

        // Cross-border automation fixture. Hopper is attacker-side, chest is target-side.
        Block hopperBlock = set(world, 15, Y, 8, Material.HOPPER);
        Directional hopperData = (Directional) hopperBlock.getBlockData();
        hopperData.setFacing(org.bukkit.block.BlockFace.EAST);
        hopperBlock.setBlockData(hopperData, false);
        Block chestBlock = set(world, 16, Y, 8, Material.CHEST);
        Hopper hopper = (Hopper) hopperBlock.getState();
        hopper.getInventory().clear();
        hopper.getInventory().addItem(new ItemStack(Material.DIAMOND, 32));
        hopper.update(true, false);
        Chest chest = (Chest) chestBlock.getState();
        chest.getInventory().clear();
        chest.update(true, false);

        // Sticky-piston boundary fixture: piston at X=14 pushes attacker-side block at X=15 into X=16.
        Block piston = set(world, 14, Y, 12, Material.STICKY_PISTON);
        Directional pistonData = (Directional) piston.getBlockData();
        pistonData.setFacing(org.bukkit.block.BlockFace.EAST);
        piston.setBlockData(pistonData, false);
        set(world, 15, Y, 12, Material.DIAMOND_BLOCK);
        set(world, 14, Y, 11, Material.LEVER);

        writeEvent("arena_build", snapshotMap(world, "build"));
        sender.sendMessage("STACKLAB BUILD OK boundary=15/16 y=" + Y);
        return true;
    }

    private boolean reset(org.bukkit.command.CommandSender sender) {
        World world = requireWorld();
        clearArena(world);
        writeEvent("arena_reset", Map.of("world", world.getName()));
        sender.sendMessage("STACKLAB RESET OK");
        return true;
    }

    private boolean portalBuild(org.bukkit.command.CommandSender sender) {
        World world = requireWorld();
        clearPortalArena(world);

        // Interior is X=16..18, inside the neighboring claim. The final west frame is X=15.
        for (int x = 16; x <= 18; x++) {
            setPortalFrame(world, x, Y, 19, org.bukkit.block.BlockFace.SOUTH, true);
            setPortalFrame(world, x, Y, 23, org.bukkit.block.BlockFace.NORTH, true);
        }
        for (int z = 20; z <= 22; z++) {
            setPortalFrame(world, 15, Y, z, org.bukkit.block.BlockFace.EAST, z != 21);
            setPortalFrame(world, 19, Y, z, org.bukkit.block.BlockFace.WEST, true);
        }

        Block barrelBlock = set(world, 17, Y, 21, Material.BARREL);
        org.bukkit.block.Barrel barrel = (org.bukkit.block.Barrel) barrelBlock.getState();
        barrel.getInventory().clear();
        barrel.getInventory().addItem(new ItemStack(Material.NETHERITE_BLOCK, 27));
        barrel.update(true, false);

        writeEvent("portal_build", portalSnapshotMap(world, "build"));
        sender.sendMessage("STACKLAB PORTAL BUILD OK final_frame=15," + Y + ",21 interior_claim_x=16..18");
        return true;
    }

    private boolean portalSnapshot(org.bukkit.command.CommandSender sender, String label) {
        World world = requireWorld();
        Map<String, Object> snapshot = portalSnapshotMap(world, label);
        writeEvent("portal_snapshot", snapshot);
        sender.sendMessage("STACKLAB PORTAL SNAPSHOT " + label + " " + gson.toJson(snapshot));
        return true;
    }

    private boolean cancelPortal(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("STACKLAB CANCELPORTAL " + cancelPortalMultiPlace);
            return true;
        }
        cancelPortalMultiPlace = Boolean.parseBoolean(args[1]);
        writeEvent("cancel_portal_mode", Map.of("enabled", cancelPortalMultiPlace));
        sender.sendMessage("STACKLAB CANCELPORTAL " + cancelPortalMultiPlace);
        return true;
    }

    private boolean snapshot(org.bukkit.command.CommandSender sender, String label) {
        World world = requireWorld();
        Map<String, Object> snapshot = snapshotMap(world, label);
        writeEvent("snapshot", snapshot);
        sender.sendMessage("STACKLAB SNAPSHOT " + label + " " + gson.toJson(snapshot));
        return true;
    }

    private boolean tick(org.bukkit.command.CommandSender sender, String[] args) {
        long ticks = args.length > 1 ? Long.parseLong(args[1]) : 20L;
        ticks = Math.max(1, Math.min(ticks, 1200));
        long finalTicks = ticks;
        Bukkit.getScheduler().runTaskLater(this, () -> {
            writeEvent("tick_complete", Map.of("ticks", finalTicks));
            sender.sendMessage("STACKLAB TICK COMPLETE " + finalTicks);
        }, ticks);
        sender.sendMessage("STACKLAB TICK START " + ticks);
        return true;
    }

    private boolean give(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 5) {
            sender.sendMessage("Usage: /stacklab give <player> <material> <namespace:key> <level>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        Material material = Material.matchMaterial(args[2]);
        if (material == null) {
            sender.sendMessage("Unknown material: " + args[2]);
            return true;
        }
        NamespacedKey key = NamespacedKey.fromString(args[3]);
        if (key == null) {
            sender.sendMessage("Invalid enchant key: " + args[3]);
            return true;
        }
        Enchantment enchantment = Registry.ENCHANTMENT.get(key);
        if (enchantment == null) {
            sender.sendMessage("Enchant not registered: " + key);
            return true;
        }
        int level = Integer.parseInt(args[4]);
        ItemStack item = new ItemStack(material);
        item.addUnsafeEnchantment(enchantment, level);
        player.getInventory().clear();
        player.getInventory().setItemInMainHand(item);
        writeEvent("give", Map.of("player", player.getName(), "material", material.name(), "enchant", key.toString(), "level", level));
        sender.sendMessage("STACKLAB GIVE OK player=" + player.getName() + " enchant=" + key + " level=" + level);
        return true;
    }

    private Map<String, Object> snapshotMap(World world, String label) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("label", label);
        result.put("tree_source", type(world, 15, Y, 0));
        result.put("tree_target_1", type(world, 16, Y, 0));
        result.put("tree_target_2", type(world, 17, Y, 0));
        result.put("tunnel_source", type(world, 15, Y + 1, 4));
        result.put("tunnel_target", type(world, 16, Y + 1, 4));
        result.put("piston_payload_source", type(world, 15, Y, 12));
        result.put("piston_payload_target", type(world, 16, Y, 12));
        result.put("hopper_count", inventoryCount(world.getBlockAt(15, Y, 8), Material.DIAMOND));
        result.put("target_chest_count", inventoryCount(world.getBlockAt(16, Y, 8), Material.DIAMOND));
        return result;
    }

    private Map<String, Object> portalSnapshotMap(World world, String label) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("label", label);
        result.put("final_frame", type(world, 15, Y, 21));
        result.put("final_frame_eye", hasEye(world.getBlockAt(15, Y, 21)));
        result.put("barrel_type", type(world, 17, Y, 21));
        result.put("barrel_netherite_blocks", inventoryCount(world.getBlockAt(17, Y, 21), Material.NETHERITE_BLOCK));
        result.put("portal_block_count", countBlocks(world, Material.END_PORTAL, 16, 18, Y, Y, 20, 22));
        result.put("dropped_netherite_blocks", world.getEntitiesByClass(Item.class).stream()
            .filter(item -> inPortalArena(item.getLocation()))
            .filter(item -> item.getItemStack().getType() == Material.NETHERITE_BLOCK)
            .mapToInt(item -> item.getItemStack().getAmount())
            .sum());
        return result;
    }

    private boolean hasEye(Block block) {
        return block.getBlockData() instanceof EndPortalFrame frame && frame.hasEye();
    }

    private int countBlocks(World world, Material material, int minX, int maxX, int minY, int maxY, int minZ, int maxZ) {
        int count = 0;
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                for (int z = minZ; z <= maxZ; z++) {
                    if (world.getBlockAt(x, y, z).getType() == material) count++;
                }
            }
        }
        return count;
    }

    private int inventoryCount(Block block, Material material) {
        if (!(block.getState() instanceof org.bukkit.inventory.InventoryHolder holder)) return -1;
        return holder.getInventory().all(material).values().stream().mapToInt(ItemStack::getAmount).sum();
    }

    private void clearArena(World world) {
        for (int x = 12; x <= 19; x++) {
            for (int y = Y - 1; y <= Y + 4; y++) {
                for (int z = -2; z <= 14; z++) {
                    world.getBlockAt(x, y, z).setType(Material.AIR, false);
                }
            }
        }
        for (int x = 12; x <= 19; x++) {
            for (int z = -2; z <= 14; z++) {
                world.getBlockAt(x, Y - 1, z).setType(Material.BEDROCK, false);
            }
        }
    }

    private void clearPortalArena(World world) {
        for (int x = 13; x <= 21; x++) {
            for (int y = Y - 2; y <= Y + 4; y++) {
                for (int z = 17; z <= 25; z++) {
                    world.getBlockAt(x, y, z).setType(Material.AIR, false);
                }
            }
        }
        for (int x = 13; x <= 21; x++) {
            for (int z = 17; z <= 25; z++) {
                world.getBlockAt(x, Y - 1, z).setType(Material.BEDROCK, false);
            }
        }
        world.getEntitiesByClass(Item.class).stream()
            .filter(item -> inPortalArena(item.getLocation()))
            .forEach(Item::remove);
    }

    private void setPortalFrame(World world, int x, int y, int z, org.bukkit.block.BlockFace facing, boolean eye) {
        Block block = set(world, x, y, z, Material.END_PORTAL_FRAME);
        EndPortalFrame data = (EndPortalFrame) block.getBlockData();
        data.setFacing(facing);
        data.setEye(eye);
        block.setBlockData(data, false);
    }

    private Block set(World world, int x, int y, int z, Material material) {
        Block block = world.getBlockAt(x, y, z);
        block.setType(material, false);
        return block;
    }

    private String type(World world, int x, int y, int z) {
        return world.getBlockAt(x, y, z).getType().name();
    }

    private World requireWorld() {
        World world = Bukkit.getWorld("world");
        if (world == null) throw new IllegalStateException("world is not loaded");
        return world;
    }

    private void writeEvent(String type, Map<String, ?> fields) {
        JsonObject object = new JsonObject();
        object.addProperty("ts", Instant.now().toString());
        object.addProperty("type", type);
        fields.forEach((key, value) -> object.add(key, gson.toJsonTree(value)));
        try (BufferedWriter writer = Files.newBufferedWriter(evidencePath, StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            writer.write(gson.toJson(object));
            writer.newLine();
        } catch (IOException exception) {
            getLogger().warning("Could not write evidence: " + exception.getMessage());
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onBreak(BlockBreakEvent event) {
        Location location = event.getBlock().getLocation();
        if (!inArena(location)) return;
        writeEvent("block_break", Map.of(
            "player", event.getPlayer().getName(),
            "block", event.getBlock().getType().name(),
            "x", location.getBlockX(), "y", location.getBlockY(), "z", location.getBlockZ(),
            "cancelled", event.isCancelled()
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onMoveItem(InventoryMoveItemEvent event) {
        writeEvent("inventory_move", Map.of(
            "item", event.getItem().getType().name(),
            "amount", event.getItem().getAmount(),
            "cancelled", event.isCancelled(),
            "source", event.getSource().getType().name(),
            "destination", event.getDestination().getType().name()
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onPistonExtend(BlockPistonExtendEvent event) {
        if (!inArena(event.getBlock().getLocation())) return;
        writeEvent("piston_extend", Map.of("cancelled", event.isCancelled(), "blocks", event.getBlocks().size(), "direction", event.getDirection().name()));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onPistonRetract(BlockPistonRetractEvent event) {
        if (!inArena(event.getBlock().getLocation())) return;
        writeEvent("piston_retract", Map.of("cancelled", event.isCancelled(), "blocks", event.getBlocks().size(), "direction", event.getDirection().name()));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onExplosion(EntityExplodeEvent event) {
        if (!inArena(event.getLocation())) return;
        writeEvent("entity_explode", Map.of("cancelled", event.isCancelled(), "blocks", event.blockList().size(), "entity", event.getEntityType().name()));
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void onPortalMultiPlaceGuard(BlockMultiPlaceEvent event) {
        boolean touchesBarrel = event.getReplacedBlockStates().stream()
            .anyMatch(state -> state.getType() == Material.BARREL && inPortalArena(state.getLocation()));
        if (cancelPortalMultiPlace && touchesBarrel) {
            event.setCancelled(true);
        }
        if (event.getReplacedBlockStates().stream().anyMatch(state -> inPortalArena(state.getLocation()))) {
            writeEvent("portal_multi_place_highest", Map.of(
                "player", event.getPlayer().getName(),
                "cancelled", event.isCancelled(),
                "touches_barrel", touchesBarrel,
                "states", event.getReplacedBlockStates().size(),
                "fixture_cancel_mode", cancelPortalMultiPlace
            ));
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onPortalMultiPlaceMonitor(BlockMultiPlaceEvent event) {
        if (event.getReplacedBlockStates().stream().noneMatch(state -> inPortalArena(state.getLocation()))) return;
        writeEvent("portal_multi_place_monitor", Map.of(
            "player", event.getPlayer().getName(),
            "cancelled", event.isCancelled(),
            "states", event.getReplacedBlockStates().size(),
            "event_block_x", event.getBlock().getX(),
            "event_block_y", event.getBlock().getY(),
            "event_block_z", event.getBlock().getZ()
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onItemSpawn(ItemSpawnEvent event) {
        if (!inPortalArena(event.getLocation())) return;
        writeEvent("portal_item_spawn", Map.of(
            "item", event.getEntity().getItemStack().getType().name(),
            "amount", event.getEntity().getItemStack().getAmount(),
            "cancelled", event.isCancelled(),
            "x", event.getLocation().getX(), "y", event.getLocation().getY(), "z", event.getLocation().getZ()
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onTeleport(PlayerTeleportEvent event) {
        if (!inArena(event.getFrom()) && !inArena(event.getTo())) return;
        Location to = event.getTo();
        writeEvent("teleport", Map.of(
            "player", event.getPlayer().getName(), "cause", event.getCause().name(), "cancelled", event.isCancelled(),
            "to_x", to == null ? Double.NaN : to.getX(), "to_y", to == null ? Double.NaN : to.getY(), "to_z", to == null ? Double.NaN : to.getZ()
        ));
    }

    private boolean inArena(Location location) {
        if (location == null || !location.getWorld().getName().equals("world")) return false;
        return location.getBlockX() >= 12 && location.getBlockX() <= 19
            && location.getBlockY() >= Y - 2 && location.getBlockY() <= Y + 6
            && location.getBlockZ() >= -3 && location.getBlockZ() <= 15;
    }

    private boolean inPortalArena(Location location) {
        if (location == null || !location.getWorld().getName().equals("world")) return false;
        return location.getBlockX() >= 13 && location.getBlockX() <= 21
            && location.getBlockY() >= Y - 2 && location.getBlockY() <= Y + 5
            && location.getBlockZ() >= 17 && location.getBlockZ() <= 25;
    }
}