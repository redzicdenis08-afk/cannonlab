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

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashSet;
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
            Set<Material> containers = new HashSet<>((Set<Material>) rawContainers);
            boolean crafterAdded = containers.add(Material.CRAFTER);
            boolean potAdded = containers.add(Material.DECORATED_POT);
            if (!containers.contains(Material.CRAFTER) || !containers.contains(Material.DECORATED_POT)) {
                throw new IllegalStateException("Could not register modern protected containers");
            }

            setField(protectionConfig, "customContainersMat", containers);
            Object namesValue = getField(protectionConfig, "customContainers");
            if (!(namesValue instanceof Set<?> rawNames)) {
                throw new IllegalStateException("FactionsUUID custom container names are unavailable");
            }
            Set<String> names = new HashSet<>();
            for (Object value : rawNames) names.add(String.valueOf(value));
            names.add(Material.CRAFTER.name());
            names.add(Material.DECORATED_POT.name());
            setField(protectionConfig, "customContainers", names);

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

    private Object getField(Object target, String fieldName) throws ReflectiveOperationException {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.get(target);
    }

    private void setField(Object target, String fieldName, Object value) throws ReflectiveOperationException {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        field.set(target, value);
    }
}