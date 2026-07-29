package dev.denis.phaselab.guard;

import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.entity.Player;
import org.bukkit.entity.ThrownPotion;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.LingeringPotionSplashEvent;
import org.bukkit.event.entity.ProjectileLaunchEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.projectiles.ProjectileSource;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

public final class SyntheticPotionXpGuardPlugin extends JavaPlugin implements Listener {
    private NamespacedKey syntheticKey;
    private final Map<UUID, ProjectileSource> suppressedShooters = new HashMap<>();

    @Override
    public void onEnable() {
        syntheticKey = new NamespacedKey(this, "synthetic_player_potion");
        getServer().getPluginManager().registerEvents(this, this);
        getLogger().info("Synthetic potion XP guard enabled");
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = false)
    public void onProjectileLaunch(ProjectileLaunchEvent event) {
        if (!(event.getEntity() instanceof ThrownPotion potion)) return;
        if (!(potion.getShooter() instanceof Player player)) return;

        // A genuine player-thrown lingering potion originates while a potion is
        // in one of the player's hands. ExcellentEnchants launches its synthetic
        // potion while the player still holds the bow, then assigns potion data.
        if (isPotion(player.getInventory().getItemInMainHand())
            || isPotion(player.getInventory().getItemInOffHand())) {
            return;
        }

        potion.getPersistentDataContainer().set(syntheticKey, PersistentDataType.BYTE, (byte) 1);
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = false)
    public void suppressSyntheticShooter(LingeringPotionSplashEvent event) {
        ThrownPotion potion = event.getEntity();
        Byte synthetic = potion.getPersistentDataContainer().get(syntheticKey, PersistentDataType.BYTE);
        if (synthetic == null || synthetic != (byte) 1) return;

        ProjectileSource shooter = potion.getShooter();
        if (!(shooter instanceof Player)) return;
        suppressedShooters.put(potion.getUniqueId(), shooter);
        potion.setShooter(null);
    }

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = false)
    public void restoreSyntheticShooter(LingeringPotionSplashEvent event) {
        ProjectileSource shooter = suppressedShooters.remove(event.getEntity().getUniqueId());
        if (shooter != null) event.getEntity().setShooter(shooter);
    }

    private boolean isPotion(ItemStack item) {
        if (item == null) return false;
        Material material = item.getType();
        return material == Material.LINGERING_POTION || material == Material.SPLASH_POTION;
    }
}