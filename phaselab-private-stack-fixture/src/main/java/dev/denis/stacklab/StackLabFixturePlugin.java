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
import org.bukkit.entity.AbstractHorse;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.Horse;
import org.bukkit.entity.Item;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Event;
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
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.PotionMeta;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.potion.PotionType;

import java.io.BufferedWriter;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
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
        registerOptionalAuraEvent("dev.aurelium.auraskills.api.event.mana.ManaAbilityActivateEvent", "mana_ability_activate");
        registerOptionalAuraEvent("dev.aurelium.auraskills.api.event.mana.ManaAbilityBlockBreakEvent", "mana_ability_break");
        registerOptionalAuraEvent("dev.aurelium.auraskills.api.event.mana.TerraformBlockBreakEvent", "terraform_break");
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
                    case "directionclaimsnapshot" -> directionClaimSnapshot(sender, args.length > 1 ? args[1] : "manual");
                    case "claimpoint" -> claimPoint(sender, args);
                    case "factionboost" -> factionBoost(sender, args);
                    case "give" -> give(sender, args);
                    case "boatuse" -> boatUse(sender, args);
                    case "boatinteract" -> boatInteract(sender, args);
                    case "horseprep" -> horsePrep(sender, args);
                    case "vehicleinteract" -> vehicleInteract(sender, args);
                    case "vehicledismount" -> vehicleDismount(sender, args);
                    case "vehiclecheck" -> vehicleCheck(sender, args);
                    case "grindstoneprep" -> grindstonePrep(sender, args);
                    case "break" -> breakBlock(sender, args);
                    case "alchemycycle" -> alchemyCycle(sender, args.length > 1 ? args[1] : "manual");
                    case "alchemyfinal" -> alchemyFinal(sender);
                    case "auramana" -> auraMana(sender, args);
                    case "aurastop" -> auraStop(sender, args);
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

    private void registerOptionalAuraEvent(String className, String evidenceType) {
        try {
            Class<? extends Event> eventClass = Class.forName(className).asSubclass(Event.class);
            Bukkit.getPluginManager().registerEvent(eventClass, this, EventPriority.MONITOR, (listener, event) -> {
                if (!event.getClass().getName().equals(className)) return;
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("event_class", event.getClass().getName());
                try {
                    Method cancelled = event.getClass().getMethod("isCancelled");
                    data.put("cancelled", Boolean.TRUE.equals(cancelled.invoke(event)));
                } catch (ReflectiveOperationException ignored) {
                    data.put("cancelled", false);
                }
                try {
                    if (evidenceType.equals("mana_ability_activate")) {
                        Player player = (Player) event.getClass().getMethod("getPlayer").invoke(event);
                        Object ability = event.getClass().getMethod("getManaAbility").invoke(event);
                        data.put("player", player.getName());
                        data.put("ability", String.valueOf(ability));
                        try {
                            data.put("ability_id", String.valueOf(ability.getClass().getMethod("getId").invoke(ability)));
                        } catch (ReflectiveOperationException ignored) {
                            data.put("ability_id", String.valueOf(ability));
                        }
                        data.put("duration", event.getClass().getMethod("getDuration").invoke(event));
                        data.put("mana_used", event.getClass().getMethod("getManaUsed").invoke(event));
                    } else if (event instanceof BlockBreakEvent breakEvent) {
                        Block block = breakEvent.getBlock();
                        data.put("player", breakEvent.getPlayer().getName());
                        data.put("x", block.getX());
                        data.put("y", block.getY());
                        data.put("z", block.getZ());
                        data.put("material", block.getType().name());
                    }
                } catch (ReflectiveOperationException exception) {
                    data.put("decode_error", exception.toString());
                }
                writeEvent(evidenceType, data);
            }, this, false);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            writeEvent("optional_event_registration_failed", Map.of("class", className, "error", exception.toString()));
        }
    }

    private boolean auraMana(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 3) {
            sender.sendMessage("Usage: /stacklab auramana <player> <amount>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        double amount = Double.parseDouble(args[2]);
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("requested", amount);
        try {
            Class<?> apiClass = Class.forName("dev.aurelium.auraskills.api.AuraSkillsApi");
            Object api = apiClass.getMethod("get").invoke(null);
            Object user = apiClass.getMethod("getUser", java.util.UUID.class).invoke(api, player.getUniqueId());
            Class<?> skillsUserClass = Class.forName("dev.aurelium.auraskills.api.user.SkillsUser");
            evidence.put("before", skillsUserClass.getMethod("getMana").invoke(user));
            evidence.put("max", skillsUserClass.getMethod("getMaxMana").invoke(user));
            skillsUserClass.getMethod("setMana", double.class).invoke(user, amount);
            evidence.put("after", skillsUserClass.getMethod("getMana").invoke(user));
            evidence.put("ok", true);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            evidence.put("ok", false);
            evidence.put("error", exception.toString());
        }
        writeEvent("aura_mana_set", evidence);
        sender.sendMessage("STACKLAB AURA MANA " + gson.toJson(evidence));
        return true;
    }

    private boolean auraStop(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 3) {
            sender.sendMessage("Usage: /stacklab aurastop <player> <ability>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        String abilityName = args[2].toUpperCase();
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("ability", abilityName);
        try {
            Object aura = Bukkit.getPluginManager().getPlugin("AuraSkills");
            if (aura == null) throw new IllegalStateException("AuraSkills not loaded");
            Object user = aura.getClass().getMethod("getUser", Player.class).invoke(aura, player);
            Class<? extends Enum> abilitiesClass = Class.forName("dev.aurelium.auraskills.api.mana.ManaAbilities").asSubclass(Enum.class);
            @SuppressWarnings({"unchecked", "rawtypes"})
            Object ability = Enum.valueOf(abilitiesClass, abilityName);
            Class<?> manaAbilityClass = Class.forName("dev.aurelium.auraskills.api.mana.ManaAbility");
            Object data = user.getClass().getMethod("getManaAbilityData", manaAbilityClass).invoke(user, ability);
            Class<?> dataClass = Class.forName("dev.aurelium.auraskills.common.mana.ManaAbilityData");
            evidence.put("was_activated", dataClass.getMethod("isActivated").invoke(data));
            evidence.put("was_ready", dataClass.getMethod("isReady").invoke(data));
            evidence.put("was_cooldown", dataClass.getMethod("getCooldown").invoke(data));
            dataClass.getMethod("setActivated", boolean.class).invoke(data, false);
            dataClass.getMethod("setReady", boolean.class).invoke(data, false);
            dataClass.getMethod("setCooldown", int.class).invoke(data, 0);
            evidence.put("ok", true);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            evidence.put("ok", false);
            evidence.put("error", exception.toString());
        }
        writeEvent("aura_ability_reset", evidence);
        sender.sendMessage("STACKLAB AURA STOP " + gson.toJson(evidence));
        return true;
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

        // Connected excavation lane. Terraform begins on attacker-side X=15
        // and can fan into the neighboring claim if secondary breaks bypass
        // ordinary BlockBreakEvent protection.
        for (int x = 15; x <= 18; x++) {
            set(world, x, Y, 2, Material.DIRT);
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

    private boolean directionClaimSnapshot(org.bukkit.command.CommandSender sender, String label) {
        Map<String, Object> witness = new LinkedHashMap<>();
        witness.put("label", label);
        try {
            Class<?> locationClass = Class.forName("dev.kitteh.factions.FLocation");
            Constructor<?> locationConstructor = locationClass.getConstructor(String.class, int.class, int.class);
            Class<?> boardClass = Class.forName("dev.kitteh.factions.Board");
            Method boardFactory = boardClass.getMethod("board");
            Object board = boardFactory.invoke(null);
            Method factionAt = boardClass.getMethod("factionAt", locationClass);

            Map<String, int[]> points = new LinkedHashMap<>();
            points.put("center", new int[]{0, 0});
            points.put("east_near", new int[]{1, 0});
            points.put("east_far", new int[]{5, 0});
            points.put("west_near", new int[]{-1, 0});
            points.put("west_far", new int[]{-5, 0});
            points.put("south_near", new int[]{0, 1});
            points.put("south_far", new int[]{0, 5});
            points.put("north_near", new int[]{0, -1});
            points.put("north_far", new int[]{0, -5});

            Method tag = null;
            Method isWilderness = null;
            for (Map.Entry<String, int[]> entry : points.entrySet()) {
                int[] chunk = entry.getValue();
                Object location = locationConstructor.newInstance("world", chunk[0], chunk[1]);
                Object faction = factionAt.invoke(board, location);
                if (tag == null) {
                    tag = faction.getClass().getMethod("tag");
                    isWilderness = faction.getClass().getMethod("isWilderness");
                }
                witness.put(entry.getKey() + "_chunk_x", chunk[0]);
                witness.put(entry.getKey() + "_chunk_z", chunk[1]);
                witness.put(entry.getKey() + "_tag", String.valueOf(tag.invoke(faction)));
                witness.put(entry.getKey() + "_wilderness", Boolean.TRUE.equals(isWilderness.invoke(faction)));
            }
            witness.put("verified", true);
        } catch (ReflectiveOperationException exception) {
            witness.put("verified", false);
            witness.put("error", exception.toString());
        }
        writeEvent("direction_claim_witness", witness);
        sender.sendMessage("STACKLAB DIRECTION CLAIM WITNESS " + gson.toJson(witness));
        return true;
    }

    private boolean claimPoint(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 4) {
            sender.sendMessage("Usage: /stacklab claimpoint <label> <chunk-x> <chunk-z>");
            return true;
        }
        Map<String, Object> witness = new LinkedHashMap<>();
        witness.put("label", args[1]);
        try {
            int chunkX = Integer.parseInt(args[2]);
            int chunkZ = Integer.parseInt(args[3]);
            witness.put("chunk_x", chunkX);
            witness.put("chunk_z", chunkZ);

            Class<?> locationClass = Class.forName("dev.kitteh.factions.FLocation");
            Constructor<?> locationConstructor = locationClass.getConstructor(String.class, int.class, int.class);
            Class<?> boardClass = Class.forName("dev.kitteh.factions.Board");
            Method boardFactory = boardClass.getMethod("board");
            Object board = boardFactory.invoke(null);
            Method factionAt = boardClass.getMethod("factionAt", locationClass);
            Object location = locationConstructor.newInstance("world", chunkX, chunkZ);
            Object faction = factionAt.invoke(board, location);
            Method tag = faction.getClass().getMethod("tag");
            Method isWilderness = faction.getClass().getMethod("isWilderness");
            witness.put("tag", String.valueOf(tag.invoke(faction)));
            witness.put("wilderness", Boolean.TRUE.equals(isWilderness.invoke(faction)));
            witness.put("verified", true);
        } catch (NumberFormatException | ReflectiveOperationException exception) {
            witness.put("verified", false);
            witness.put("error", exception.toString());
        }
        writeEvent("claim_point_witness", witness);
        sender.sendMessage("STACKLAB CLAIM POINT " + gson.toJson(witness));
        return true;
    }

    private boolean factionBoost(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 3) {
            sender.sendMessage("Usage: /stacklab factionboost <faction-tag> <value>");
            return true;
        }
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("tag", args[1]);
        try {
            double value = Double.parseDouble(args[2]);
            Class<?> factionsClass = Class.forName("dev.kitteh.factions.Factions");
            Object factions = factionsClass.getMethod("factions").invoke(null);
            Object faction = factionsClass.getMethod("get", String.class).invoke(factions, args[1]);
            if (faction == null) throw new IllegalStateException("Faction not found: " + args[1]);
            Method powerBoostGetter = faction.getClass().getMethod("powerBoost");
            Method powerBoostSetter = faction.getClass().getMethod("powerBoost", double.class);
            powerBoostSetter.invoke(faction, value);
            evidence.put("requested", value);
            evidence.put("actual", ((Number) powerBoostGetter.invoke(faction)).doubleValue());
            evidence.put("verified", true);
        } catch (NumberFormatException | ReflectiveOperationException | IllegalStateException exception) {
            evidence.put("verified", false);
            evidence.put("error", exception.toString());
        }
        writeEvent("faction_power_boost", evidence);
        sender.sendMessage("STACKLAB FACTION BOOST " + gson.toJson(evidence));
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


    private boolean boatUse(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab boatuse <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("STACKLAB BOAT USE player=" + args[1] + " accepted=false reason=offline");
            return true;
        }

        World world = player.getWorld();
        player.getInventory().setItemInMainHand(new ItemStack(Material.OAK_BOAT, 1));
        long before = world.getEntities().stream()
            .filter(entity -> entity.getType().name().contains("BOAT"))
            .count();
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("before_boats", before);
        evidence.put("player_x", player.getLocation().getX());
        evidence.put("player_y", player.getLocation().getY());
        evidence.put("player_z", player.getLocation().getZ());
        evidence.put("yaw", player.getLocation().getYaw());
        evidence.put("pitch", player.getLocation().getPitch());
        try {
            Object serverPlayer = player.getClass().getMethod("getHandle").invoke(player);
            Class<?> handClass = Class.forName("net.minecraft.world.InteractionHand");
            @SuppressWarnings({"unchecked", "rawtypes"})
            Object mainHand = Enum.valueOf((Class<? extends Enum>) handClass, "MAIN_HAND");
            Object nmsStack = serverPlayer.getClass().getMethod("getItemInHand", handClass).invoke(serverPlayer, mainHand);
            Object item = nmsStack.getClass().getMethod("getItem").invoke(nmsStack);
            Object level = serverPlayer.getClass().getMethod("level").invoke(serverPlayer);
            Class<?> levelClass = Class.forName("net.minecraft.world.level.Level");
            Class<?> nmsPlayerClass = Class.forName("net.minecraft.world.entity.player.Player");
            Method use = item.getClass().getMethod("use", levelClass, nmsPlayerClass, handClass);
            Object result = use.invoke(item, level, serverPlayer, mainHand);
            evidence.put("invoked", true);
            evidence.put("result", String.valueOf(result));
        } catch (ReflectiveOperationException exception) {
            evidence.put("invoked", false);
            evidence.put("error", exception.toString());
        }

        Bukkit.getScheduler().runTaskLater(this, () -> {
            var nearby = world.getEntities().stream()
                .filter(entity -> entity.getType().name().contains("BOAT"))
                .filter(entity -> entity.getLocation().distanceSquared(player.getLocation()) <= 64.0)
                .map(entity -> Map.of(
                    "uuid", entity.getUniqueId().toString(),
                    "type", entity.getType().name(),
                    "x", entity.getLocation().getX(),
                    "y", entity.getLocation().getY(),
                    "z", entity.getLocation().getZ()
                ))
                .toList();
            evidence.put("after_boats", world.getEntities().stream()
                .filter(entity -> entity.getType().name().contains("BOAT"))
                .count());
            evidence.put("nearby", nearby);
            evidence.put("held_after", itemSummary(player.getInventory().getItemInMainHand()));
            evidence.put("accepted", !nearby.isEmpty());
            writeEvent("server_boat_item_use", evidence);
            sender.sendMessage("STACKLAB BOAT USE " + gson.toJson(evidence));
        }, 2L);
        return true;
    }



    private boolean horsePrep(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab horseprep <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("STACKLAB HORSE PREP player=" + args[1] + " accepted=false reason=offline");
            return true;
        }
        World world = player.getWorld();
        world.getEntitiesByClass(Horse.class).forEach(Horse::remove);
        Location location = player.getLocation().clone();
        org.bukkit.util.Vector forward = location.getDirection().setY(0.0D);
        if (forward.lengthSquared() < 1.0E-6D) {
            forward = new org.bukkit.util.Vector(1.0D, 0.0D, 0.0D);
        } else {
            forward.normalize();
        }
        location.add(forward.multiply(1.5D));
        location.setY(Y);
        location.setPitch(0.0F);
        Horse horse = (Horse) world.spawnEntity(location, EntityType.HORSE);
        horse.setTamed(true);
        horse.setOwner(player);
        horse.getInventory().setSaddle(new ItemStack(Material.SADDLE));
        horse.addPotionEffect(new PotionEffect(PotionEffectType.FIRE_RESISTANCE, PotionEffect.INFINITE_DURATION, 0, false, false));
        horse.setAdult();
        horse.setHealth(horse.getMaxHealth());
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("horse_uuid", horse.getUniqueId().toString());
        evidence.put("type", horse.getType().name());
        evidence.put("x", horse.getLocation().getX());
        evidence.put("y", horse.getLocation().getY());
        evidence.put("z", horse.getLocation().getZ());
        evidence.put("tamed", horse.isTamed());
        evidence.put("saddled", horse.getInventory().getSaddle() != null);
        evidence.put("fire_resistance", horse.hasPotionEffect(PotionEffectType.FIRE_RESISTANCE));
        writeEvent("server_horse_prep", evidence);
        sender.sendMessage("STACKLAB HORSE PREP " + gson.toJson(evidence));
        return true;
    }

    private boolean vehicleInteract(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 3) {
            sender.sendMessage("Usage: /stacklab vehicleinteract <player> <entity-type>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        String requestedType = args[2].toUpperCase(java.util.Locale.ROOT);
        if (player == null) {
            sender.sendMessage("STACKLAB VEHICLE INTERACT player=" + args[1] + " mounted=false reason=offline");
            return true;
        }
        var target = player.getWorld().getEntities().stream()
            .filter(entity -> entity.getType().name().equals(requestedType))
            .min(java.util.Comparator.comparingDouble(entity -> entity.getLocation().distanceSquared(player.getLocation())))
            .orElse(null);
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("requested_type", requestedType);
        evidence.put("target_found", target != null);
        evidence.put("distance_squared", target == null ? -1.0 : target.getLocation().distanceSquared(player.getLocation()));
        try {
            if (target == null) throw new IllegalStateException("No nearby requested vehicle");
            Object serverPlayer = player.getClass().getMethod("getHandle").invoke(player);
            Object serverTarget = target.getClass().getMethod("getHandle").invoke(target);
            Class<?> handClass = Class.forName("net.minecraft.world.InteractionHand");
            @SuppressWarnings({"unchecked", "rawtypes"})
            Object mainHand = Enum.valueOf((Class<? extends Enum>) handClass, "MAIN_HAND");
            Class<?> vec3Class = Class.forName("net.minecraft.world.phys.Vec3");
            Object hitVector = serverTarget.getClass().getMethod("position").invoke(serverTarget);
            int entityId = (Integer) serverTarget.getClass().getMethod("getId").invoke(serverTarget);
            Class<?> packetClass = Class.forName("net.minecraft.network.protocol.game.ServerboundInteractPacket");
            Constructor<?> packetConstructor = packetClass.getConstructor(int.class, handClass, vec3Class, boolean.class);
            Object packet = packetConstructor.newInstance(entityId, mainHand, hitVector, false);
            Object connection = serverPlayer.getClass().getField("connection").get(serverPlayer);
            Method handleInteract = connection.getClass().getMethod("handleInteract", packetClass);
            handleInteract.invoke(connection, packet);
            evidence.put("invoked", true);
            evidence.put("path", "ServerboundInteractPacket->handleInteract");
            evidence.put("entity_id", entityId);
        } catch (ReflectiveOperationException | IllegalStateException exception) {
            evidence.put("invoked", false);
            evidence.put("error", exception.toString());
        }
        evidence.put("mounted", player.getVehicle() != null);
        evidence.put("vehicle_type", player.getVehicle() == null ? "NONE" : player.getVehicle().getType().name());
        writeEvent("server_vehicle_interact", evidence);
        sender.sendMessage("STACKLAB VEHICLE INTERACT " + gson.toJson(evidence));
        return true;
    }

    private boolean vehicleDismount(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab vehicledismount <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", args[1]);
        evidence.put("online", player != null);
        evidence.put("mounted_before", player != null && player.getVehicle() != null);
        try {
            if (player == null) throw new IllegalStateException("Player offline");
            Object serverPlayer = player.getClass().getMethod("getHandle").invoke(player);
            Class<?> inputClass = Class.forName("net.minecraft.world.entity.player.Input");
            Constructor<?> inputConstructor = inputClass.getConstructor(boolean.class, boolean.class, boolean.class, boolean.class, boolean.class, boolean.class, boolean.class);
            Object input = inputConstructor.newInstance(false, false, false, false, false, true, false);
            Class<?> packetClass = Class.forName("net.minecraft.network.protocol.game.ServerboundPlayerInputPacket");
            Object packet = packetClass.getConstructor(inputClass).newInstance(input);
            Object connection = serverPlayer.getClass().getField("connection").get(serverPlayer);
            connection.getClass().getMethod("handlePlayerInput", packetClass).invoke(connection, packet);
            evidence.put("invoked", true);
            evidence.put("path", "ServerboundPlayerInputPacket(shift=true)->handlePlayerInput");
        } catch (ReflectiveOperationException | IllegalStateException exception) {
            evidence.put("invoked", false);
            evidence.put("error", exception.toString());
        }
        evidence.put("mounted", player != null && player.getVehicle() != null);
        if (player != null) {
            evidence.put("x", player.getLocation().getX());
            evidence.put("y", player.getLocation().getY());
            evidence.put("z", player.getLocation().getZ());
        }
        writeEvent("server_vehicle_dismount", evidence);
        sender.sendMessage("STACKLAB VEHICLE DISMOUNT " + gson.toJson(evidence));
        return true;
    }

    private boolean boatInteract(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab boatinteract <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("STACKLAB BOAT INTERACT player=" + args[1] + " accepted=false reason=offline");
            return true;
        }
        var boat = player.getWorld().getEntities().stream()
            .filter(entity -> entity.getType().name().contains("BOAT"))
            .min(java.util.Comparator.comparingDouble(entity -> entity.getLocation().distanceSquared(player.getLocation())))
            .orElse(null);
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("boat_found", boat != null);
        evidence.put("distance_squared", boat == null ? -1.0 : boat.getLocation().distanceSquared(player.getLocation()));
        if (boat != null) {
            evidence.put("boat_uuid", boat.getUniqueId().toString());
            evidence.put("boat_type", boat.getType().name());
        }
        try {
            if (boat == null) throw new IllegalStateException("No nearby boat");
            Object serverPlayer = player.getClass().getMethod("getHandle").invoke(player);
            Object serverBoat = boat.getClass().getMethod("getHandle").invoke(boat);
            Class<?> handClass = Class.forName("net.minecraft.world.InteractionHand");
            @SuppressWarnings({"unchecked", "rawtypes"})
            Object mainHand = Enum.valueOf((Class<? extends Enum>) handClass, "MAIN_HAND");
            Class<?> vec3Class = Class.forName("net.minecraft.world.phys.Vec3");
            Object hitVector = serverBoat.getClass().getMethod("position").invoke(serverBoat);
            int entityId = (Integer) serverBoat.getClass().getMethod("getId").invoke(serverBoat);

            Class<?> packetClass = Class.forName("net.minecraft.network.protocol.game.ServerboundInteractPacket");
            Constructor<?> packetConstructor = packetClass.getConstructor(int.class, handClass, vec3Class, boolean.class);
            Object packet = packetConstructor.newInstance(entityId, mainHand, hitVector, false);

            Object connection = serverPlayer.getClass().getField("connection").get(serverPlayer);
            Method handleInteract = connection.getClass().getMethod("handleInteract", packetClass);
            handleInteract.invoke(connection, packet);
            evidence.put("invoked", true);
            evidence.put("path", "ServerboundInteractPacket->handleInteract");
            evidence.put("entity_id", entityId);
            evidence.put("result", "handled");
        } catch (ReflectiveOperationException | IllegalStateException exception) {
            evidence.put("invoked", false);
            evidence.put("error", exception.toString());
        }
        evidence.put("mounted", player.getVehicle() != null);
        evidence.put("vehicle_type", player.getVehicle() == null ? "NONE" : player.getVehicle().getType().name());
        writeEvent("server_boat_interact", evidence);
        sender.sendMessage("STACKLAB BOAT INTERACT " + gson.toJson(evidence));
        return true;
    }

    private boolean vehicleCheck(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab vehiclecheck <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("STACKLAB VEHICLE CHECK player=" + args[1] + " online=false");
            return true;
        }
        var vehicle = player.getVehicle();
        var nearby = player.getWorld().getEntities().stream()
            .filter(entity -> entity.getType().name().contains("BOAT"))
            .filter(entity -> entity.getLocation().distanceSquared(player.getLocation()) <= 100.0)
            .map(entity -> Map.of(
                "uuid", entity.getUniqueId().toString(),
                "type", entity.getType().name(),
                "x", entity.getLocation().getX(),
                "y", entity.getLocation().getY(),
                "z", entity.getLocation().getZ(),
                "passengers", entity.getPassengers().stream().map(passenger -> passenger.getName()).toList()
            ))
            .toList();
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("player", player.getName());
        evidence.put("mounted", vehicle != null);
        evidence.put("vehicle_type", vehicle == null ? "NONE" : vehicle.getType().name());
        evidence.put("vehicle_uuid", vehicle == null ? "NONE" : vehicle.getUniqueId().toString());
        evidence.put("nearby", nearby);
        writeEvent("server_vehicle_check", evidence);
        sender.sendMessage("STACKLAB VEHICLE CHECK " + gson.toJson(evidence));
        return true;
    }

    private boolean grindstonePrep(org.bukkit.command.CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /stacklab grindstoneprep <player>");
            return true;
        }
        Player player = Bukkit.getPlayerExact(args[1]);
        if (player == null) {
            sender.sendMessage("Player not online: " + args[1]);
            return true;
        }
        var top = player.getOpenInventory().getTopInventory();
        if (top.getType() != InventoryType.GRINDSTONE) {
            sender.sendMessage("STACKLAB GRINDSTONE PREP player=" + player.getName() + " accepted=false reason=not_open");
            return true;
        }
        ItemStack held = player.getInventory().getItemInMainHand();
        if (held.getType().isAir()) {
            sender.sendMessage("STACKLAB GRINDSTONE PREP player=" + player.getName() + " accepted=false reason=no_item");
            return true;
        }
        top.setItem(0, held.clone());
        player.getInventory().setItemInMainHand(null);
        Bukkit.getScheduler().runTaskLater(this, () -> writeEvent("grindstone_prepared", Map.of(
            "player", player.getName(),
            "input", itemSummary(top.getItem(0)),
            "result", itemSummary(top.getItem(2)),
            "input_fragility", enchantLevel(top.getItem(0), "excellentenchants:curse_of_fragility")
        )), 1L);
        sender.sendMessage("STACKLAB GRINDSTONE PREP player=" + player.getName() + " accepted=true");
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
        // BrewingStand#getInventory is the live inventory. Calling update()
        // after mutating it writes the captured empty snapshot back over the
        // live block, so apply tile-state fields first, then populate a fresh
        // live inventory.
        stand.setFuelLevel(20);
        stand.setBrewingTime(1);
        stand.update(true, false);
        BrewingStand liveStand = (BrewingStand) standBlock.getState();
        var inventory = liveStand.getInventory();
        inventory.clear();
        for (int slot = 0; slot < 3; slot++) inventory.setItem(slot, potion(PotionType.WATER));
        inventory.setIngredient(new ItemStack(Material.NETHER_WART));

        writeEvent("alchemy_cycle_start", alchemySnapshotMap(world, label));
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
        var inventory = stand.getInventory();
        inventory.clear();
        inventory.setItem(0, potion(PotionType.AWKWARD));
        writeEvent("alchemy_final_ready", alchemySnapshotMap(world, "final-ready"));
        sender.sendMessage("STACKLAB ALCHEMY FINAL READY");
        return true;
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
        result.put("terraform_source", type(world, 15, Y, 2));
        result.put("terraform_target_1", type(world, 16, Y, 2));
        result.put("terraform_target_2", type(world, 17, Y, 2));
        result.put("terraform_target_3", type(world, 18, Y, 2));
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
    public void onBrew(BrewEvent event) {
        if (!inArena(event.getBlock().getLocation())) return;
        writeEvent("brew_event", Map.of(
            "cancelled", event.isCancelled(),
            "ingredient", itemSummary(event.getContents().getIngredient()),
            "slot_0_before", itemSummary(event.getContents().getItem(0)),
            "slot_1_before", itemSummary(event.getContents().getItem(1)),
            "slot_2_before", itemSummary(event.getContents().getItem(2)),
            "result_count", event.getResults().size()
        ));
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
    public void onPlayerInteractEntityWitness(PlayerInteractEntityEvent event) {
        if (!event.getRightClicked().getType().name().contains("BOAT")) return;
        writeEvent("player_interact_boat", Map.of(
            "player", event.getPlayer().getName(),
            "target", event.getRightClicked().getUniqueId().toString(),
            "target_type", event.getRightClicked().getType().name(),
            "cancelled", event.isCancelled(),
            "hand", event.getHand().name(),
            "distance_squared", event.getPlayer().getLocation().distanceSquared(event.getRightClicked().getLocation())
        ));
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onVehicleEnterWitness(VehicleEnterEvent event) {
        if (!event.getVehicle().getType().name().contains("BOAT")) return;
        writeEvent("vehicle_enter", Map.of(
            "vehicle", event.getVehicle().getUniqueId().toString(),
            "vehicle_type", event.getVehicle().getType().name(),
            "entered", event.getEntered().getName(),
            "cancelled", event.isCancelled()
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