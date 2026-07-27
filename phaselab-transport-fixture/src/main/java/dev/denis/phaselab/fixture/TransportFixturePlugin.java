package dev.denis.phaselab.fixture;

import org.bukkit.Location;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Entity;
import org.bukkit.entity.EntityType;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import java.util.List;
import java.util.Locale;

/** Deterministic server-side mount fixture for defensive PhaseLab tests. */
public final class TransportFixturePlugin extends JavaPlugin {
    private static final List<EntityType> TYPES = List.of(
        EntityType.HORSE,
        EntityType.PIG,
        EntityType.CAMEL,
        EntityType.STRIDER,
        EntityType.MINECART,
        EntityType.OAK_CHEST_BOAT
    );

    @Override
    public void onEnable() {
        getLogger().info("PhaseLab TransportFixture enabled");
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage("This fixture command must be run by a player.");
            return true;
        }
        if (args.length == 0) {
            sender.sendMessage("Usage: /transportfixture <mount|clear> [type]");
            return true;
        }

        if (args[0].equalsIgnoreCase("clear")) {
            player.leaveVehicle();
            for (Entity entity : player.getWorld().getEntities()) {
                if (TYPES.contains(entity.getType())) {
                    entity.remove();
                }
            }
            sender.sendMessage("TRANSPORT_FIXTURE_CLEAR ok=true");
            return true;
        }

        if (!args[0].equalsIgnoreCase("mount") || args.length != 2) {
            sender.sendMessage("Usage: /transportfixture mount <horse|pig|camel|strider|minecart|chest_boat>");
            return true;
        }

        EntityType type;
        try {
            type = switch (args[1].toLowerCase(Locale.ROOT)) {
                case "horse" -> EntityType.HORSE;
                case "pig" -> EntityType.PIG;
                case "camel" -> EntityType.CAMEL;
                case "strider" -> EntityType.STRIDER;
                case "minecart" -> EntityType.MINECART;
                case "chest_boat" -> EntityType.OAK_CHEST_BOAT;
                default -> throw new IllegalArgumentException("Unknown transport type.");
            };
        } catch (IllegalArgumentException exception) {
            sender.sendMessage(exception.getMessage());
            return true;
        }

        player.leaveVehicle();
        for (Entity entity : player.getWorld().getEntities()) {
            if (TYPES.contains(entity.getType())) {
                entity.remove();
            }
        }

        Location spawn = new Location(player.getWorld(), -0.8D, 65.0D, 0.5D, -90.0F, 0.0F);
        Entity root = player.getWorld().spawnEntity(spawn, type);
        boolean mounted = root.addPassenger(player);
        sender.sendMessage(String.format(Locale.ROOT,
            "TRANSPORT_FIXTURE type=%s entity=%s mounted=%s root=%.6f,%.6f,%.6f",
            args[1].toLowerCase(Locale.ROOT), root.getType(), mounted,
            root.getLocation().getX(), root.getLocation().getY(), root.getLocation().getZ()));
        return true;
    }
}
