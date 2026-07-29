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
import org.bukkit.block.BrewingStand;
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
import org.bukkit.event.inventory.BrewEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryMoveItemEvent;
import org.bukkit.event.inventory.InventoryType;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.PotionMeta;
import org.bukkit.plugin.RegisteredListener;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.potion.PotionType;

import java.io.BufferedWriter;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class StackLabFixturePlugin extends JavaPlugin implements Listener {
    private static final int Y = 65;
    private final Gson gson = new Gson();
    private Path evidencePath;
    private boolean cancelPortalMultiPlace;
    private int observedAlchemyBrewEvents;

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
                    case "claimsnapshot" -> claimSnapshot(sender, args.length > 1 ? args[1] : "manual");
                    case "give" -> give(sender, args);
                    case "break" -> breakBlock(sender, args);
                    case "alchemyprep" -> alchemyPrep(sender, args);
                    case "alchemyopen" -> alchemyOpen(sender, args);
                    case "alchemycycle" -> alchemyCycle(sender, args.length > 1 ? args[1] : "manual");
                    case "alchemyfinal" -> alchemyFinal(sender);
                    case "alchemystate" -> alchemyState(sender, args.length > 1 ? args[1] : "manual");
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
        hopper.getInventory().setItem(0, new ItemStack(Material.DIAMOND, 32));
        Chest chest = (Chest) chestBlock.getState();
        chest.getInventory().clear();

        // Sticky-piston boundary fixture: piston at X=14 pushes attacker-side block at X=15 into X=16.
        Block piston = set(world, 14, Y, 12, Material.STICKY_PISTON);
        Directional pistonData = (Directional) piston.getBlockData();
        pistonData.setFacing(org.bukkit.block.BlockFace.EAST);
        piston.setBlockData(pistonData, false);
        set(world, 15, Y, 12, Material.DIAMOND_BLOCK);
        set(world, 14, Y, 11, Material.LEVER);

        // Physical workstation for the AuraSkills + ExcellentEnchants
        // grindstone event-priority interaction.
        set(world, 13, Y, 5, Material.GRINDSTONE);

        // Brewing amplifier fixture. The side redstone block locks the hopper
        // during brewing and is removed after AuraSkills observes BrewEvent.
        set(world, 13, Y + 2, 9, Material.BREWING_STAND);
        set(world, 13, Y + 1, 9, Material.HOPPER);
        set(world, 13, Y, 9, Material.CHEST);
        set(world, 14, Y + 1, 9, Material.REDSTONE_BLOCK);

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
        barrel.getInventory().setItem(0, new ItemStack(Material.NETHERITE_BLOCK, 27));

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

    private boolean claimSnapshot(org.bukkit.command.CommandSender sender, String label) {
        Map<String, Object> witness = new LinkedHashMap<>();
        witness.put("label", label);
        witness.put("attacker_chunk_x", 0);
        witness.put("attacker_chunk_z", 0);
        witness.put("victim_chunk_x", 1);
        witness.put("victim_chunk_z", 0);
        try {
            Class<?> locationClass = Class.forName("dev.kitteh.factions.FLocation");
            Constructor<?> locationConstructor = locationClass.getConstructor(String.class, int.class, int.class);
            Class<?> boardClass = Class.forName("dev.kitteh.factions.Board");
            Method boardFactory = boardClass.getMethod("board");
            Object board = boardFactory.invoke(null);
            Method factionAt = boardClass.getMethod("factionAt", locationClass);

            Object attackerLocation = locationConstructor.newInstance("world", 0, 0);
            Object victimLocation = locationConstructor.newInstance("world", 1, 0);
            Object attackerPortalLocation = locationConstructor.newInstance("world", 0, 1);
            Object victimPortalLocation = locationConstructor.newInstance("world", 1, 1);
            Object attackerFaction = factionAt.invoke(board, attackerLocation);
            Object victimFaction = factionAt.invoke(board, victimLocation);
            Object attackerPortalFaction = factionAt.invoke(board, attackerPortalLocation);
            Object victimPortalFaction = factionAt.invoke(board, victimPortalLocation);

            Method tag = attackerFaction.getClass().getMethod("tag");
            Method isWilderness = attackerFaction.getClass().getMethod("isWilderness");
            witness.put("attacker_tag", String.valueOf(tag.invoke(attackerFaction)));
            witness.put("victim_tag", String.valueOf(tag.invoke(victimFaction)));
            witness.put("attacker_portal_tag", String.valueOf(tag.invoke(attackerPortalFaction)));
            witness.put("victim_portal_tag", String.valueOf(tag.invoke(victimPortalFaction)));
            witness.put("attacker_wilderness", Boolean.TRUE.equals(isWilderness.invoke(attackerFaction)));
            witness.put("victim_wilderness", Boolean.TRUE.equals(isWilderness.invoke(victimFaction)));
            witness.put("attacker_portal_wilderness", Boolean.TRUE.equals(isWilderness.invoke(attackerPortalFaction)));
            witness.put("victim_portal_wilderness", Boolean.TRUE.equals(isWilderness.invoke(victimPortalFaction)));
            witness.put("verified", true);
        } catch (ReflectiveOperationException exception) {
            witness.put("verified", false);
            witness.put("error", exception.toString());
        }
        writeEvent("claim_witness", witness);
        sender.sendMessage("STACKLAB CLAIM WITNESS " + gson.toJson(witness));
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

    private boolean breakBlock(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 5) {
            sender.sendMessage("Usage: /stacklab break <player> <x> <y> <z>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        int x = Integer.parseInt(args[2]);
        int y = Integer.parseInt(args[3]);
        int z = Integer.parseInt(args[4]);
        Block block = requireWorld().getBlockAt(x, y, z);
        Material before = block.getType();
        boolean accepted = player.breakBlock(block);
        writeEvent("server_break_request", Map.of(
            "player", player.getName(),
            "x", x, "y", y, "z", z,
            "before", before.name(),
            "accepted", accepted,
            "after", block.getType().name()
        ));
        sender.sendMessage("STACKLAB BREAK player=" + player.getName() + " accepted=" + accepted + " before=" + before + " after=" + block.getType());
        return true;
    }

    private boolean alchemyPrep(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab alchemyprep <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        setAuraSkillState(player, "ALCHEMY", 50, 0D);
        observedAlchemyBrewEvents = 0;
        clearAuraBrewingCache();
        Map<String, Object> state = brewingCacheSnapshot("prep");
        state.put("player", player.getName());
        state.put("alchemy_level", auraSkillLevel(player, "ALCHEMY"));
        state.put("alchemy_xp", auraSkillXp(player, "ALCHEMY"));
        writeEvent("alchemy_cache_prep", state);
        sender.sendMessage("STACKLAB ALCHEMY PREP " + gson.toJson(state));
        return true;
    }

    private boolean alchemyOpen(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab alchemyopen <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        Block standBlock = requireWorld().getBlockAt(13, Y + 2, 9);
        if (!(standBlock.getState() instanceof BrewingStand stand)) {
            sender.sendMessage("STACKLAB ALCHEMY OPEN missing brewing stand");
            return true;
        }
        player.openInventory(stand.getInventory());
        writeEvent("alchemy_server_open", Map.of(
            "player", player.getName(),
            "inventory", player.getOpenInventory().getTopInventory().getType().name()
        ));
        sender.sendMessage("STACKLAB ALCHEMY OPEN player=" + player.getName() + " inventory="
            + player.getOpenInventory().getTopInventory().getType().name());
        return true;
    }

    private boolean alchemyCycle(org.bukkit.command.CommandSender sender, String label) {
        World world = requireWorld();
        Block standBlock = world.getBlockAt(13, Y + 2, 9);
        if (!(standBlock.getState() instanceof BrewingStand stand)) {
            sender.sendMessage("STACKLAB ALCHEMY missing brewing stand");
            return true;
        }

        // Lock extraction until the actual BrewEvent and AuraSkills' delayed
        // before/after comparison have completed.
        set(world, 14, Y + 1, 9, Material.REDSTONE_BLOCK);
        stand.setFuelLevel(20);
        stand.setBrewingTime(1);
        stand.update(true, false);

        // BlockState#update writes the snapshot inventory back to the world.
        // Populate the live inventory only after that state update or the
        // just-added potions and ingredient are erased before the next tick.
        BrewingStand liveStand = (BrewingStand) standBlock.getState();
        var inventory = liveStand.getInventory();
        inventory.clear();
        for (int slot = 0; slot < 3; slot++) inventory.setItem(slot, potion(PotionType.WATER));
        inventory.setIngredient(new ItemStack(Material.NETHER_WART));

        writeEvent("alchemy_cycle_start", Map.of("label", label));
        Bukkit.getScheduler().runTaskLater(this, () -> {
            world.getBlockAt(14, Y + 1, 9).setType(Material.AIR, false);
            writeEvent("alchemy_hopper_unlocked", alchemySnapshotMap(world, label));
        }, 6L);
        Bukkit.getScheduler().runTaskLater(this, () -> {
            writeEvent("alchemy_cycle_end", alchemySnapshotMap(world, label));
        }, 35L);
        sender.sendMessage("STACKLAB ALCHEMY CYCLE " + label);
        return true;
    }

    private boolean alchemyFinal(org.bukkit.command.CommandSender sender) {
        World world = requireWorld();
        world.getBlockAt(13, Y + 1, 9).setType(Material.AIR, false);
        world.getBlockAt(14, Y + 1, 9).setType(Material.AIR, false);
        Block standBlock = world.getBlockAt(13, Y + 2, 9);
        if (!(standBlock.getState() instanceof BrewingStand stand)) {
            sender.sendMessage("STACKLAB ALCHEMY missing brewing stand");
            return true;
        }
        stand.getInventory().clear();
        stand.getInventory().setItem(0, potion(PotionType.WATER));
        writeEvent("alchemy_final_ready", alchemySnapshotMap(world, "final-ready"));
        sender.sendMessage("STACKLAB ALCHEMY FINAL READY");
        return true;
    }

    private boolean alchemyState(org.bukkit.command.CommandSender sender, String label) {
        Map<String, Object> state = brewingCacheSnapshot(label);
        Player player = Bukkit.getPlayerExact("AttackerBot");
        if (player != null) {
            state.put("alchemy_level", auraSkillLevel(player, "ALCHEMY"));
            state.put("alchemy_xp", auraSkillXp(player, "ALCHEMY"));
        }
        writeEvent("alchemy_cache_state", state);
        sender.sendMessage("STACKLAB ALCHEMY STATE " + label + " " + gson.toJson(state));
        return true;
    }

    private Object findBrewingLeveler() {
        for (RegisteredListener registered : BrewEvent.getHandlerList().getRegisteredListeners()) {
            Listener listener = registered.getListener();
            if (listener.getClass().getName().equals("dev.aurelium.auraskills.bukkit.source.BrewingLeveler")) {
                return listener;
            }
        }
        throw new IllegalStateException("AuraSkills BrewingLeveler listener not registered");
    }

    @SuppressWarnings("unchecked")
    private Map<Object, Object> auraBrewingCache() {
        Object leveler = findBrewingLeveler();
        try {
            Field field = leveler.getClass().getDeclaredField("brewingStands");
            field.setAccessible(true);
            return (Map<Object, Object>) field.get(leveler);
        } catch (ReflectiveOperationException exception) {
            throw new IllegalStateException("Could not inspect AuraSkills brewing cache", exception);
        }
    }

    private void clearAuraBrewingCache() {
        auraBrewingCache().clear();
    }

    private Map<String, Object> brewingCacheSnapshot(String label) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("label", label);
        result.put("observed_brew_events", observedAlchemyBrewEvents);
        Map<Object, Object> cache = auraBrewingCache();
        result.put("stand_count", cache.size());
        List<Map<String, Object>> stands = new java.util.ArrayList<>();
        for (Map.Entry<Object, Object> entry : cache.entrySet()) {
            Map<String, Object> stand = new LinkedHashMap<>();
            stand.put("position", String.valueOf(entry.getKey()));
            try {
                Field slotsField = entry.getValue().getClass().getDeclaredField("slots");
                slotsField.setAccessible(true);
                Map<?, ?> slots = (Map<?, ?>) slotsField.get(entry.getValue());
                stand.put("slot_count", slots.size());
                List<Map<String, Object>> slotRows = new java.util.ArrayList<>();
                for (Map.Entry<?, ?> slotEntry : slots.entrySet()) {
                    Object slot = slotEntry.getValue();
                    boolean brewed = (boolean) slot.getClass().getMethod("isBrewed").invoke(slot);
                    Collection<?> ingredients = (Collection<?>) slot.getClass().getMethod("getIngredients").invoke(slot);
                    Map<String, Object> slotRow = new LinkedHashMap<>();
                    slotRow.put("slot", slotEntry.getKey());
                    slotRow.put("brewed", brewed);
                    slotRow.put("ingredient_count", ingredients.size());
                    slotRow.put("ingredients", ingredients.stream().map(String::valueOf).toList());
                    slotRows.add(slotRow);
                }
                stand.put("slots", slotRows);
            } catch (ReflectiveOperationException exception) {
                stand.put("error", exception.getClass().getSimpleName() + ":" + exception.getMessage());
            }
            stands.add(stand);
        }
        result.put("stands", stands);
        return result;
    }

    private ItemStack potion(PotionType type) {
        ItemStack item = new ItemStack(Material.POTION);
        PotionMeta meta = (PotionMeta) item.getItemMeta();
        meta.setBasePotionType(type);
        item.setItemMeta(meta);
        return item;
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

        Player attacker = Bukkit.getPlayerExact("AttackerBot");
        if (attacker != null) {
            result.put("attacker_enchanting_xp", auraEnchantingXp(attacker));
            result.put("attacker_alchemy_xp", auraSkillXp(attacker, "ALCHEMY"));
            var top = attacker.getOpenInventory().getTopInventory();
            result.put("attacker_open_inventory", top.getType().name());
            if (top.getType() == InventoryType.GRINDSTONE) {
                result.put("grindstone_input_0", itemSummary(top.getItem(0)));
                result.put("grindstone_input_1", itemSummary(top.getItem(1)));
                result.put("grindstone_result", itemSummary(top.getItem(2)));
                result.put("grindstone_input_fragility", enchantLevel(top.getItem(0), "excellentenchants:curse_of_fragility"));
                result.put("grindstone_result_fragility", enchantLevel(top.getItem(2), "excellentenchants:curse_of_fragility"));
            }
        }
        result.putAll(alchemySnapshotMap(world, label));
        return result;
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private Object auraEnchantingXp(Player player) {
        return auraSkillXp(player, "ENCHANTING");
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private void setAuraSkillState(Player player, String skillName, int level, double value) {
        try {
            Class<?> apiClass = Class.forName("dev.aurelium.auraskills.api.AuraSkillsApi");
            Object api = apiClass.getMethod("get").invoke(null);
            Object user = apiClass.getMethod("getUser", java.util.UUID.class).invoke(api, player.getUniqueId());
            Class<? extends Enum> skillsClass = (Class<? extends Enum>) Class.forName("dev.aurelium.auraskills.api.skill.Skills");
            Object skill = Enum.valueOf(skillsClass, skillName);
            Class<?> skillClass = Class.forName("dev.aurelium.auraskills.api.skill.Skill");
            Class<?> skillsUserClass = Class.forName("dev.aurelium.auraskills.api.user.SkillsUser");
            skillsUserClass.getMethod("setSkillLevel", skillClass, int.class, boolean.class).invoke(user, skill, level, true);
            skillsUserClass.getMethod("setSkillXp", skillClass, double.class).invoke(user, skill, value);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            throw new IllegalStateException("Could not reset AuraSkills " + skillName + " state", exception);
        }
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private Object auraSkillLevel(Player player, String skillName) {
        try {
            Class<?> apiClass = Class.forName("dev.aurelium.auraskills.api.AuraSkillsApi");
            Object api = apiClass.getMethod("get").invoke(null);
            Object user = apiClass.getMethod("getUser", java.util.UUID.class).invoke(api, player.getUniqueId());
            Class<? extends Enum> skillsClass = (Class<? extends Enum>) Class.forName("dev.aurelium.auraskills.api.skill.Skills");
            Object skill = Enum.valueOf(skillsClass, skillName);
            Class<?> skillClass = Class.forName("dev.aurelium.auraskills.api.skill.Skill");
            Class<?> skillsUserClass = Class.forName("dev.aurelium.auraskills.api.user.SkillsUser");
            return skillsUserClass.getMethod("getSkillLevel", skillClass).invoke(user, skill);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            return "reflection-error:" + exception.getClass().getSimpleName();
        }
    }

    private Object auraSkillXp(Player player, String skillName) {
        try {
            Class<?> apiClass = Class.forName("dev.aurelium.auraskills.api.AuraSkillsApi");
            Object api = apiClass.getMethod("get").invoke(null);
            Object user = apiClass.getMethod("getUser", java.util.UUID.class).invoke(api, player.getUniqueId());
            Class<? extends Enum> skillsClass = (Class<? extends Enum>) Class.forName("dev.aurelium.auraskills.api.skill.Skills");
            Object skill = Enum.valueOf(skillsClass, skillName);
            Class<?> skillClass = Class.forName("dev.aurelium.auraskills.api.skill.Skill");
            Class<?> skillsUserClass = Class.forName("dev.aurelium.auraskills.api.user.SkillsUser");
            return skillsUserClass.getMethod("getSkillXp", skillClass).invoke(user, skill);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            return "reflection-error:" + exception.getClass().getSimpleName();
        }
    }

    private Map<String, Object> alchemySnapshotMap(World world, String label) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("alchemy_label", label);
        Block standBlock = world.getBlockAt(13, Y + 2, 9);
        if (standBlock.getState() instanceof BrewingStand stand) {
            result.put("alchemy_slot_0", itemSummary(stand.getInventory().getItem(0)));
            result.put("alchemy_slot_1", itemSummary(stand.getInventory().getItem(1)));
            result.put("alchemy_slot_2", itemSummary(stand.getInventory().getItem(2)));
            result.put("alchemy_ingredient", itemSummary(stand.getInventory().getIngredient()));
            result.put("alchemy_brew_time", stand.getBrewingTime());
        }
        result.put("alchemy_chest_potions", inventoryCount(world.getBlockAt(13, Y, 9), Material.POTION));
        return result;
    }

    private String itemSummary(ItemStack item) {
        if (item == null || item.getType().isAir()) return "AIR";
        return item.getType().name() + "x" + item.getAmount();
    }

    private int enchantLevel(ItemStack item, String rawKey) {
        if (item == null) return 0;
        NamespacedKey key = NamespacedKey.fromString(rawKey);
        if (key == null) return 0;
        Enchantment enchantment = Registry.ENCHANTMENT.get(key);
        return enchantment == null ? 0 : item.getEnchantmentLevel(enchantment);
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
    public void onGrindstoneResultClick(InventoryClickEvent event) {
        if (!(event.getWhoClicked() instanceof Player player)) return;
        if (event.getView().getTopInventory().getType() != InventoryType.GRINDSTONE) return;
        if (event.getRawSlot() != 2) return;

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("player", player.getName());
        data.put("cancelled", event.isCancelled());
        data.put("action", event.getAction().name());
        data.put("click", event.getClick().name());
        data.put("input", itemSummary(event.getView().getTopInventory().getItem(0)));
        data.put("result", itemSummary(event.getView().getTopInventory().getItem(2)));
        data.put("input_fragility", enchantLevel(event.getView().getTopInventory().getItem(0), "excellentenchants:curse_of_fragility"));
        data.put("enchanting_xp_monitor", auraEnchantingXp(player));
        writeEvent("grindstone_result_click", data);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onBrewObserved(BrewEvent event) {
        if (event.getBlock().getX() != 13 || event.getBlock().getY() != Y + 2 || event.getBlock().getZ() != 9) return;
        observedAlchemyBrewEvents++;
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("cancelled", event.isCancelled());
        data.put("ingredient", itemSummary(event.getContents().getIngredient()));
        data.put("slot_0_before", itemSummary(event.getContents().getItem(0)));
        data.put("slot_1_before", itemSummary(event.getContents().getItem(1)));
        data.put("slot_2_before", itemSummary(event.getContents().getItem(2)));
        data.put("event_count", observedAlchemyBrewEvents);
        writeEvent("brew_event", data);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onBrewingResultClick(InventoryClickEvent event) {
        if (!(event.getWhoClicked() instanceof Player player)) return;
        if (event.getView().getTopInventory().getType() != InventoryType.BREWING) return;
        if (event.getRawSlot() < 0 || event.getRawSlot() > 2) return;

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("player", player.getName());
        data.put("slot", event.getRawSlot());
        data.put("cancelled", event.isCancelled());
        data.put("action", event.getAction().name());
        data.put("item", itemSummary(event.getCurrentItem()));
        data.put("alchemy_xp_monitor", auraSkillXp(player, "ALCHEMY"));
        writeEvent("alchemy_result_click", data);
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