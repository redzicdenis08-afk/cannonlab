package dev.denis.phaselab.guard;

import org.bukkit.Material;
import org.bukkit.Location;
import org.bukkit.entity.Player;
import org.bukkit.entity.Projectile;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityChangeBlockEvent;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Set;

public final class ModernContainerGuardPlugin extends JavaPlugin implements Listener {
    private Constructor<?> factionLocationConstructor;
    private Method factionAtLocation;

    @Override
    public void onEnable() {
        try {
            Plugin factionsPlugin = getServer().getPluginManager().getPlugin("FactionsUUID");
            if (factionsPlugin == null || !factionsPlugin.isEnabled()) {
                throw new IllegalStateException("FactionsUUID is not enabled");
            }
            ClassLoader factionsLoader = factionsPlugin.getClass().getClassLoader();

            Class<?> confsClass = Class.forName("dev.kitteh.factions.config.Confs", true, factionsLoader);
            Object mainConfig = confsClass.getMethod("main").invoke(null);
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

            Class<?> locationClass = Class.forName("dev.kitteh.factions.FLocation", true, factionsLoader);
            factionLocationConstructor = locationClass.getConstructor(Location.class);
            factionAtLocation = locationClass.getMethod("faction");

            getServer().getPluginManager().registerEvents(this, this);
            getLogger().info("FactionsUUID modern-container guard enabled; CRAFTER added=" + crafterAdded + ", DECORATED_POT added=" + potAdded);
        } catch (ReflectiveOperationException | RuntimeException exception) {
            throw new IllegalStateException("Unable to install FactionsUUID modern-container protection", exception);
        }
    }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onProjectilePotBreak(EntityChangeBlockEvent event) {
        if (event.getBlock().getType() != Material.DECORATED_POT) return;
        if (!(event.getEntity() instanceof Projectile)) return;
        if (!isNormalFaction(event.getBlock().getLocation())) return;

        event.setCancelled(true);
    }

    private boolean isNormalFaction(Location location) {
        try {
            Object factionLocation = factionLocationConstructor.newInstance(location);
            Object faction = factionAtLocation.invoke(factionLocation);
            return Boolean.TRUE.equals(faction.getClass().getMethod("isNormal").invoke(faction));
        } catch (ReflectiveOperationException exception) {
            getLogger().severe("Could not resolve faction for decorated-pot protection: " + exception);
            return true;
        }
    }

    private Object invoke(Object target, String methodName) throws ReflectiveOperationException {
        Method method = target.getClass().getMethod(methodName);
        return method.invoke(target);
    }
}