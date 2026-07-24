package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.Bukkit;
import org.bukkit.Chunk;
import org.bukkit.Material;
import org.bukkit.Location;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.block.BlockState;
import org.bukkit.block.Dispenser;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.block.BlockExplodeEvent;
import org.bukkit.event.entity.EntityExplodeEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

public final class CannonLabPlugin extends JavaPlugin implements Listener {
    private ShotRecorder recorder;
    private LabRunController runController;
    private final List<ForcedChunk> forcedChunks = new ArrayList<>();
    private boolean manualExplosionsEnabled = true;

    @Override
    public void onEnable() {
        saveDefaultConfig();

        if (!worldEditAvailable()) {
            getLogger().severe("WorldEdit or FastAsyncWorldEdit is required. Disabling CannonLab.");
            Bukkit.getPluginManager().disablePlugin(this);
            return;
        }

        try {
            createDataDirectories();
            forceLoadArenaChunks();
        } catch (IOException | RuntimeException exception) {
            getLogger().severe("Unable to initialize CannonLab: " + exception.getMessage());
            releaseForcedChunks();
            Bukkit.getPluginManager().disablePlugin(this);
            return;
        }

        WorldEditService worldEditService = new WorldEditService();
        recorder = new ShotRecorder(this);
        runController = new LabRunController(this, worldEditService, recorder);
        Bukkit.getPluginManager().registerEvents(recorder, this);
        Bukkit.getPluginManager().registerEvents(runController, this);
        Bukkit.getPluginManager().registerEvents(this, this);

        getLogger().info("CannonLab 0.3 enabled. WorldEdit automation is ready."
                + " Forced chunks=" + forcedChunks.size());
        scheduleAutorun();
    }

    @Override
    public void onDisable() {
        if (recorder != null && recorder.isRecording()) {
            recorder.cancel();
        }
        releaseForcedChunks();
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (command.getName().equalsIgnoreCase("p")) {
            return plotCommand(sender, args);
        }
        if (command.getName().equalsIgnoreCase("bonetool")) {
            return giveBoneTool(sender);
        }
        if (args.length == 0) {
            sender.sendMessage("CannonLab: status, smoke, run <scenario>, cancel");
            return true;
        }

        try {
            return switch (args[0].toLowerCase(Locale.ROOT)) {
                case "status" -> status(sender);
                case "smoke" -> smoke(sender);
                case "run" -> run(sender, args);
                case "cancel" -> cancel(sender);
                default -> {
                    sender.sendMessage("Unknown command. Use status, smoke, run <scenario>, cancel.");
                    yield true;
                }
            };
        } catch (RuntimeException exception) {
            getLogger().severe("Command failed: " + exception.getMessage());
            exception.printStackTrace();
            sender.sendMessage("CannonLab command failed: " + exception.getMessage());
            return true;
        }
    }

    private boolean plotCommand(CommandSender sender, String[] args) {
        if (args.length == 0) {
            sender.sendMessage("CannonLab plot shim: /p tntfill or /p gui");
            return true;
        }
        return switch (args[0].toLowerCase(Locale.ROOT)) {
            case "tntfill" -> fillLoadedDispensers(sender);
            case "gui" -> {
                manualExplosionsEnabled = !manualExplosionsEnabled;
                sender.sendMessage("CannonLab manual explosions: "
                        + (manualExplosionsEnabled ? "ENABLED" : "DISABLED")
                        + ". Automated scenarios always retain explosion control.");
                yield true;
            }
            default -> {
                sender.sendMessage("Unsupported plot shim. Use /p tntfill or /p gui.");
                yield true;
            }
        };
    }

    private boolean fillLoadedDispensers(CommandSender sender) {
        int dispensers = 0;
        long tntItems = 0;
        for (Chunk chunk : arenaWorld().getLoadedChunks()) {
            for (BlockState state : chunk.getTileEntities()) {
                if (!(state instanceof Dispenser dispenser)) {
                    continue;
                }
                for (int slot = 0; slot < dispenser.getInventory().getSize(); slot++) {
                    dispenser.getInventory().setItem(slot, new ItemStack(Material.TNT, 64));
                    tntItems += 64;
                }
                dispenser.update(true, false);
                dispensers++;
            }
        }
        sender.sendMessage("CannonLab /p tntfill: filled " + dispensers
                + " loaded dispensers with " + tntItems + " TNT items.");
        return true;
    }

    private boolean giveBoneTool(CommandSender sender) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage("/bonetool must be used by a player.");
            return true;
        }
        player.getInventory().addItem(new ItemStack(Material.BONE));
        player.sendMessage("Bone tool: right-click places sand, sneak-right-click places obsidian, left-click removes.");
        return true;
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onManualEntityExplosion(EntityExplodeEvent event) {
        if (!manualExplosionsEnabled && (runController == null || !runController.isRunning())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onManualBlockExplosion(BlockExplodeEvent event) {
        if (!manualExplosionsEnabled && (runController == null || !runController.isRunning())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority = EventPriority.HIGH, ignoreCancelled = true)
    public void onBoneTool(PlayerInteractEvent event) {
        ItemStack item = event.getItem();
        if (item == null || item.getType() != Material.BONE || event.getClickedBlock() == null) {
            return;
        }
        Action action = event.getAction();
        if (action == Action.LEFT_CLICK_BLOCK) {
            event.getClickedBlock().setType(Material.AIR, false);
            event.setCancelled(true);
            return;
        }
        if (action != Action.RIGHT_CLICK_BLOCK) {
            return;
        }
        Block placement = event.getClickedBlock().getRelative(event.getBlockFace());
        placement.setType(event.getPlayer().isSneaking() ? Material.OBSIDIAN : Material.SAND, false);
        event.setCancelled(true);
    }

    private boolean status(CommandSender sender) {
        World world = arenaWorld();
        sender.sendMessage("CannonLab enabled | world=" + world.getName()
                + " | WorldEdit=" + worldEditPluginName()
                + " | forcedChunks=" + forcedChunks.size()
                + " | profile=" + getConfig().getString("parity-profile.id", "unprofiled")
                + "/" + getConfig().getString("parity-profile.evidence-grade", "unknown")
                + " | run=" + runController.status());
        return true;
    }

    private boolean smoke(CommandSender sender) {
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        world.getChunkAt(origin).load(true);

        sender.sendMessage("Smoke PASS | world=" + world.getName()
                + " origin=" + origin.getBlockX() + "," + origin.getBlockY() + "," + origin.getBlockZ()
                + " forcedChunks=" + forcedChunks.size()
                + " scenarios=" + directory("scenarios")
                + " cannons=" + directory("cannons"));
        return true;
    }

    private boolean run(CommandSender sender, String[] args) {
        if (args.length < 2) {
            sender.sendMessage("Usage: /cannonlab run <scenario.yml>");
            return true;
        }
        runController.run(args[1], sender);
        return true;
    }

    private boolean cancel(CommandSender sender) {
        runController.cancel(sender);
        return true;
    }

    private void scheduleAutorun() {
        String scenario = System.getProperty("cannonlab.scenario");
        if (scenario == null || scenario.isBlank()) {
            scenario = System.getenv("CANNONLAB_SCENARIO");
        }
        if (scenario == null || scenario.isBlank()) {
            return;
        }

        String selectedScenario = scenario;
        Bukkit.getScheduler().runTaskLater(this, () -> {
            try {
                runController.run(selectedScenario, Bukkit.getConsoleSender());
            } catch (RuntimeException exception) {
                getLogger().severe("Autorun failed: " + exception.getMessage());
                exception.printStackTrace();
                Bukkit.shutdown();
            }
        }, 60L);
    }

    private void forceLoadArenaChunks() {
        World world = arenaWorld();
        Location origin = arenaOrigin(world);
        int radiusX = Math.max(0, getConfig().getInt("arena.radius-x", 256));
        int radiusZ = Math.max(0, getConfig().getInt("arena.radius-z", 96));

        int minimumChunkX = Math.floorDiv(origin.getBlockX() - radiusX, 16);
        int maximumChunkX = Math.floorDiv(origin.getBlockX() + radiusX, 16);
        int minimumChunkZ = Math.floorDiv(origin.getBlockZ() - radiusZ, 16);
        int maximumChunkZ = Math.floorDiv(origin.getBlockZ() + radiusZ, 16);

        for (int chunkX = minimumChunkX; chunkX <= maximumChunkX; chunkX++) {
            for (int chunkZ = minimumChunkZ; chunkZ <= maximumChunkZ; chunkZ++) {
                Chunk chunk = world.getChunkAt(chunkX, chunkZ);
                chunk.load(true);
                if (!chunk.isForceLoaded()) {
                    chunk.setForceLoaded(true);
                    forcedChunks.add(new ForcedChunk(world, chunkX, chunkZ));
                }
            }
        }
    }

    private void releaseForcedChunks() {
        for (ForcedChunk forcedChunk : forcedChunks) {
            try {
                forcedChunk.world().getChunkAt(forcedChunk.x(), forcedChunk.z()).setForceLoaded(false);
            } catch (RuntimeException exception) {
                getLogger().warning("Unable to release forced chunk "
                        + forcedChunk.x() + "," + forcedChunk.z() + ": " + exception.getMessage());
            }
        }
        forcedChunks.clear();
    }

    World arenaWorld() {
        String worldName = getConfig().getString("arena.world", "world");
        World world = Bukkit.getWorld(worldName);
        if (world == null) {
            throw new IllegalStateException("Arena world is not loaded: " + worldName);
        }
        return world;
    }

    Location arenaOrigin(World world) {
        return new Location(
                world,
                getConfig().getInt("arena.origin.x", 0),
                getConfig().getInt("arena.origin.y", 100),
                getConfig().getInt("arena.origin.z", 0)
        );
    }

    File resolveScenarioFile(String name) {
        String normalized = name.endsWith(".yml") ? name : name + ".yml";
        return resolveInside(directory("scenarios"), normalized);
    }

    File resolveCannonFile(String name) {
        String normalized = name.endsWith(".schem") ? name : name + ".schem";
        File file = resolveInside(directory("cannons"), normalized);
        if (!file.isFile()) {
            throw new IllegalArgumentException("Cannon schematic not found: " + file.getAbsolutePath());
        }
        return file;
    }

    File resolveTargetFile(String name) {
        String normalized = name.endsWith(".schem") ? name : name + ".schem";
        File file = resolveInside(directory("targets"), normalized);
        if (!file.isFile()) {
            throw new IllegalArgumentException("Target schematic not found: " + file.getAbsolutePath());
        }
        return file;
    }

    private File resolveInside(Path baseDirectory, String name) {
        Path resolved = baseDirectory.resolve(name).normalize();
        if (!resolved.startsWith(baseDirectory)) {
            throw new IllegalArgumentException("Path escapes CannonLab directory: " + name);
        }
        return resolved.toFile();
    }

    private void createDataDirectories() throws IOException {
        Files.createDirectories(directory("cannons"));
        Files.createDirectories(directory("targets"));
        Files.createDirectories(directory("scenarios"));
        Files.createDirectories(directory("results"));
    }

    private Path directory(String name) {
        return getDataFolder().toPath().resolve(name).toAbsolutePath().normalize();
    }

    private boolean worldEditAvailable() {
        return Bukkit.getPluginManager().getPlugin("WorldEdit") != null
                || Bukkit.getPluginManager().getPlugin("FastAsyncWorldEdit") != null;
    }

    private String worldEditPluginName() {
        Plugin worldEdit = Bukkit.getPluginManager().getPlugin("FastAsyncWorldEdit");
        if (worldEdit == null) {
            worldEdit = Bukkit.getPluginManager().getPlugin("WorldEdit");
        }
        return worldEdit == null ? "missing" : worldEdit.getName() + " " + worldEdit.getPluginMeta().getVersion();
    }

    private record ForcedChunk(World world, int x, int z) {
    }
}
