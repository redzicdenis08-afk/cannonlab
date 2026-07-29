package dev.denis.phaselab.guard;

import org.bukkit.Material;
import org.bukkit.block.DecoratedPot;
import org.bukkit.entity.Player;
import org.bukkit.entity.Projectile;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityChangeBlockEvent;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;

import java.lang.reflect.Method;
import java.util.Set;

public final class ModernContainerGuardPlugin extends JavaPlugin implements Listener {
    @Override
    public void onEnable() {
        try {
            Plugin factionsPlugin = getServer().getPluginManager().getPlugin("FactionsUUID");
            if (factionsPlugin == null || !factionsPlugin.isEnabled()) {
                throw new IllegalStateException("FactionsUUID is not enabled");
            }
            // Invoke the public FactionsPlugin#conf bridge on the already loaded
            // plugin instance. Paper isolates plugin classloaders, so trying to
            // Class.forName internal Factions classes from this plugin is invalid.
            Object mainConfig = invoke(factionsPlugin, "conf");
            Object factionsConfig = invoke(mainConfig, "factions");
            Object protectionConfig = invoke(factionsConfig, "protection");
            Object containersValue = invoke(protectionConfig, "getCustomContainers");

            if (!(containersValue instanceof Set<?> rawContainers)) {
                throw new IllegalStateException("FactionsUUID custom container set is unavailable");
            }

            @SuppressWarnings("unchecked")
            Set<Material> containers = (Set<Material>) rawContainers;
            boolean crafterAdded = containers.add(Material.CRAFTER);
            boolean potAdded = containers.add(Material.DECORATED_POT);
            if (!containers.contains(Material.CRAFTER) || !containers.contains(Material.DECORATED_POT)) {
                throw new IllegalStateException("Could not register modern protected containers");
            }

            getServer().getPluginManager().registerEvents(this, this);
            getLogger().info("FactionsUUID modern-container guard enabled; CRAFTER added=" + crafterAdded + ", DECORATED_POT added=" + potAdded);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            throw new IllegalStateException("Unable to install FactionsUUID modern-container protection", exception);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onProjectilePotBreak(EntityChangeBlockEvent event) {
        if (event.getBlock().getType() != Material.DECORATED_POT) return;
        if (!(event.getEntity() instanceof Projectile projectile)) return;
        if (!(projectile.getShooter() instanceof Player)) return;
        if (!(event.getBlock().getState() instanceof DecoratedPot pot)) return;
        if (pot.getInventory().getItem() == null || pot.getInventory().getItem().getType().isAir()) return;

        event.setCancelled(true);
    }

    private Object invoke(Object target, String methodName) throws ReflectiveOperationException {
        Method method = target.getClass().getMethod(methodName);
        return method.invoke(target);
    }
}