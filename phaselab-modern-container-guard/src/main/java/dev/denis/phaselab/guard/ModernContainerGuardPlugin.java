package dev.denis.phaselab.guard;

import org.bukkit.Material;
import org.bukkit.plugin.java.JavaPlugin;

import java.lang.reflect.Method;
import java.util.Set;

public final class ModernContainerGuardPlugin extends JavaPlugin {
    @Override
    public void onEnable() {
        try {
            Class<?> confsClass = Class.forName("dev.kitteh.factions.config.Confs");
            Object mainConfig = confsClass.getMethod("main").invoke(null);
            Object factionsConfig = invoke(mainConfig, "factions");
            Object protectionConfig = invoke(factionsConfig, "protection");
            Object containersValue = invoke(protectionConfig, "getCustomContainers");

            if (!(containersValue instanceof Set<?> rawContainers)) {
                throw new IllegalStateException("FactionsUUID custom container set is unavailable");
            }

            @SuppressWarnings("unchecked")
            Set<Material> containers = (Set<Material>) rawContainers;
            boolean added = containers.add(Material.CRAFTER);
            if (!containers.contains(Material.CRAFTER)) {
                throw new IllegalStateException("Could not register CRAFTER as a protected container");
            }

            getLogger().info("FactionsUUID modern-container guard enabled; CRAFTER protected (added=" + added + ")");
        } catch (ReflectiveOperationException | RuntimeException exception) {
            throw new IllegalStateException("Unable to install FactionsUUID modern-container protection", exception);
        }
    }

    private Object invoke(Object target, String methodName) throws ReflectiveOperationException {
        Method method = target.getClass().getMethod(methodName);
        return method.invoke(target);
    }
}