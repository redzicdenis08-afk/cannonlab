package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.Material;
import org.bukkit.configuration.file.YamlConfiguration;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

record LabScenario(
        String name,
        String cannonFile,
        BlockPoint cannonOrigin,
        FireMode fireMode,
        BlockPoint fireInput,
        List<BlockPoint> fireInputs,
        BlockPoint directDispenser,
        int firePulseTicks,
        boolean enforceDispenserLimit,
        TargetType targetType,
        TargetDirection targetDirection,
        Material targetMaterial,
        Material alternateMaterial,
        int targetDistance,
        int targetWidth,
        int targetHeight,
        int targetYOffset,
        int targetLateralOffset,
        int targetLayers,
        int targetSpacing,
        int hotdogBandWidth,
        int pillarSpacing,
        RegenConfig regeneration,
        int shots,
        int warmupTicks,
        int maxShotTicks,
        int quietTicks,
        boolean shutdownWhenFinished
) {
    LabScenario {
        fireInputs = List.copyOf(fireInputs);
    }

    static LabScenario load(File file) {
        if (!file.isFile()) {
            throw new IllegalArgumentException("Scenario does not exist: " + file.getAbsolutePath());
        }

        YamlConfiguration yaml = YamlConfiguration.loadConfiguration(file);
        String scenarioName = yaml.getString("name", stripExtension(file.getName()));
        String cannon = require(yaml.getString("cannon.file"), "cannon.file");

        BlockPoint cannonOrigin = point(yaml, "cannon.origin", new BlockPoint(0, 0, 0));
        BlockPoint primaryFireInput = point(yaml, "cannon.fire-input", new BlockPoint(0, 0, 0));
        List<BlockPoint> configuredInputs = points(yaml, "cannon.fire-inputs");
        List<BlockPoint> fireInputs = configuredInputs.isEmpty()
                ? List.of(primaryFireInput)
                : configuredInputs;
        BlockPoint directDispenser = point(
                yaml,
                "cannon.direct-dispenser",
                new BlockPoint(fireInputs.getFirst().x() + 1, fireInputs.getFirst().y(), fireInputs.getFirst().z())
        );

        String fireModeName = yaml.getString("cannon.fire-mode", "redstone");
        FireMode fireMode;
        if (fireModeName.equalsIgnoreCase("direct")) {
            fireMode = FireMode.DIRECT_DISPENSE;
        } else {
            try {
                fireMode = FireMode.valueOf(normalize(fireModeName));
            } catch (IllegalArgumentException exception) {
                throw new IllegalArgumentException("Unsupported cannon.fire-mode: " + fireModeName, exception);
            }
        }

        String targetName = yaml.getString("target.type", "watered");
        TargetType targetType;
        try {
            targetType = TargetType.valueOf(normalize(targetName));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported target.type: " + targetName, exception);
        }

        String directionName = yaml.getString("target.direction", "east");
        TargetDirection targetDirection;
        try {
            targetDirection = TargetDirection.valueOf(normalize(directionName));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported target.direction: " + directionName, exception);
        }

        Material defaultMaterial = switch (targetType) {
            case COBBLE_REGEN, HOTDOG, PILLARS -> Material.COBBLESTONE;
            default -> Material.OBSIDIAN;
        };
        Material targetMaterial = material(
                yaml.getString("target.material"),
                defaultMaterial,
                "target.material"
        );
        Material alternateMaterial = material(
                yaml.getString("target.alternate-material"),
                Material.OBSIDIAN,
                "target.alternate-material"
        );

        boolean defaultRegen = targetType == TargetType.COBBLE_REGEN;
        RegenConfig regeneration = new RegenConfig(
                yaml.getBoolean("target.regeneration.enabled", defaultRegen),
                Math.max(0, yaml.getInt("target.regeneration.delay-ticks", 40)),
                Math.max(1, yaml.getInt("target.regeneration.interval-ticks", 10)),
                Math.max(1, yaml.getInt("target.regeneration.max-blocks-per-cycle", 32))
        );

        return new LabScenario(
                scenarioName,
                cannon,
                cannonOrigin,
                fireMode,
                primaryFireInput,
                fireInputs,
                directDispenser,
                Math.max(1, yaml.getInt("cannon.fire-pulse-ticks", 2)),
                yaml.getBoolean("limits.enforce-dispenser-limit", true),
                targetType,
                targetDirection,
                targetMaterial,
                alternateMaterial,
                Math.max(1, yaml.getInt("target.distance", 160)),
                Math.max(1, yaml.getInt("target.width", 17)),
                Math.max(1, yaml.getInt("target.height", 32)),
                yaml.getInt("target.y-offset", 0),
                yaml.getInt("target.lateral-offset", 0),
                Math.max(1, yaml.getInt("target.layers", 1)),
                Math.max(1, yaml.getInt("target.spacing", 3)),
                Math.max(1, yaml.getInt("target.hotdog-band-width", 2)),
                Math.max(2, yaml.getInt("target.pillar-spacing", 3)),
                regeneration,
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

    private static List<BlockPoint> points(YamlConfiguration yaml, String path) {
        List<BlockPoint> result = new ArrayList<>();
        for (Map<?, ?> entry : yaml.getMapList(path)) {
            result.add(new BlockPoint(
                    integer(entry.get("x"), 0),
                    integer(entry.get("y"), 0),
                    integer(entry.get("z"), 0)
            ));
        }
        return result;
    }

    private static int integer(Object value, int fallback) {
        return value instanceof Number number ? number.intValue() : fallback;
    }

    private static Material material(String value, Material fallback, String path) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        Material parsed = Material.matchMaterial(value, true);
        if (parsed == null || !parsed.isBlock()) {
            throw new IllegalArgumentException("Unsupported block material for " + path + ": " + value);
        }
        return parsed;
    }

    private static String normalize(String value) {
        return value.toUpperCase(Locale.ROOT).replace('-', '_');
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

    record RegenConfig(
            boolean enabled,
            int delayTicks,
            int intervalTicks,
            int maxBlocksPerCycle
    ) {
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
        SLAB_FILTER,
        HOTDOG,
        PILLARS
    }

    enum TargetDirection {
        NORTH,
        SOUTH,
        EAST,
        WEST
    }
}
