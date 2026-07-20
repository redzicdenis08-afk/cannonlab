package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.configuration.file.YamlConfiguration;

import java.io.File;
import java.util.Locale;

record LabScenario(
        String name,
        String cannonFile,
        BlockPoint cannonOrigin,
        FireMode fireMode,
        BlockPoint fireInput,
        BlockPoint directDispenser,
        int firePulseTicks,
        boolean enforceDispenserLimit,
        TargetType targetType,
        int targetDistance,
        int targetWidth,
        int targetHeight,
        int targetLayers,
        int targetSpacing,
        int shots,
        int warmupTicks,
        int maxShotTicks,
        int quietTicks,
        boolean shutdownWhenFinished
) {
    static LabScenario load(File file) {
        if (!file.isFile()) {
            throw new IllegalArgumentException("Scenario does not exist: " + file.getAbsolutePath());
        }

        YamlConfiguration yaml = YamlConfiguration.loadConfiguration(file);
        String scenarioName = yaml.getString("name", stripExtension(file.getName()));
        String cannon = require(yaml.getString("cannon.file"), "cannon.file");

        BlockPoint cannonOrigin = point(yaml, "cannon.origin", new BlockPoint(0, 0, 0));
        BlockPoint fireInput = point(yaml, "cannon.fire-input", new BlockPoint(0, 0, 0));
        BlockPoint directDispenser = point(
                yaml,
                "cannon.direct-dispenser",
                new BlockPoint(fireInput.x() + 1, fireInput.y(), fireInput.z())
        );

        FireMode fireMode;
        String fireModeName = yaml.getString("cannon.fire-mode", "redstone");
        try {
            fireMode = FireMode.valueOf(fireModeName.toUpperCase(Locale.ROOT).replace('-', '_'));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported cannon.fire-mode: " + fireModeName, exception);
        }

        String targetName = yaml.getString("target.type", "watered");
        TargetType targetType;
        try {
            targetType = TargetType.valueOf(targetName.toUpperCase(Locale.ROOT).replace('-', '_'));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported target.type: " + targetName, exception);
        }

        return new LabScenario(
                scenarioName,
                cannon,
                cannonOrigin,
                fireMode,
                fireInput,
                directDispenser,
                Math.max(1, yaml.getInt("cannon.fire-pulse-ticks", 2)),
                yaml.getBoolean("limits.enforce-dispenser-limit", true),
                targetType,
                Math.max(1, yaml.getInt("target.distance", 160)),
                Math.max(1, yaml.getInt("target.width", 17)),
                Math.max(1, yaml.getInt("target.height", 32)),
                Math.max(1, yaml.getInt("target.layers", 1)),
                Math.max(1, yaml.getInt("target.spacing", 3)),
                Math.max(1, yaml.getInt("run.shots", 1)),
                Math.max(1, yaml.getInt("run.warmup-ticks", 20)),
                Math.max(20, yaml.getInt("run.max-shot-ticks", 240)),
                Math.max(2, yaml.getInt("run.quiet-ticks", 20)),
                yaml.getBoolean("run.shutdown-when-finished", false)
        );
    }

    private static BlockPoint point(YamlConfiguration yaml, String path, BlockPoint fallback) {
        return new BlockPoint(
                yaml.getInt(path + ".x", fallback.x()),
                yaml.getInt(path + ".y", fallback.y()),
                yaml.getInt(path + ".z", fallback.z())
        );
    }

    private static String require(String value, String path) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("Missing required scenario value: " + path);
        }
        return value;
    }

    private static String stripExtension(String name) {
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : name;
    }

    record BlockPoint(int x, int y, int z) {
    }

    enum FireMode {
        REDSTONE,
        DIRECT_DISPENSE
    }

    enum TargetType {
        DRY,
        WATERED,
        COBBLE_REGEN,
        FILTER,
        SLAB_FILTER
    }
}
