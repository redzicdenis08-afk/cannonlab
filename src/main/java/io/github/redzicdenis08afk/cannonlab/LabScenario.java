package io.github.redzicdenis08afk.cannonlab;

import org.bukkit.Material;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.configuration.file.YamlConfiguration;

import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
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
        boolean suppressPasteSideEffects,
        int settleBeforeFillTicks,
        int fillToFireTicks,
        boolean enforceDispenserLimit,
        TargetType targetType,
        TargetDirection targetDirection,
        String targetFile,
        BlockPoint targetOrigin,
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
        List<TargetStage> targetStages,
        RegenConfig regeneration,
        DurabilityConfig durability,
        int shots,
        int volleysPerShot,
        int volleyIntervalTicks,
        int warmupTicks,
        int maxShotTicks,
        int quietTicks,
        boolean shutdownWhenFinished
) {
    LabScenario {
        fireInputs = List.copyOf(fireInputs);
        targetStages = List.copyOf(targetStages);
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

        boolean suppressPasteSideEffects = yaml.getBoolean("cannon.suppress-paste-side-effects", false);
        int settleBeforeFillTicks = Math.max(0, yaml.getInt("cannon.settle-before-fill-ticks", 0));
        int fillToFireTicks = Math.max(0, yaml.getInt("cannon.fill-to-fire-ticks", 0));

        TargetType targetType = targetType(yaml.getString("target.type", "watered"), "target.type");
        TargetDirection targetDirection = targetDirection(
                yaml.getString("target.direction", "east"),
                "target.direction"
        );

        Material defaultMaterial = defaultMaterial(targetType);
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

        int targetDistance = Math.max(1, yaml.getInt("target.distance", 160));
        int targetWidth = Math.max(1, yaml.getInt("target.width", 17));
        int targetHeight = Math.max(1, yaml.getInt("target.height", 32));
        int targetYOffset = yaml.getInt("target.y-offset", 0);
        int targetLateralOffset = yaml.getInt("target.lateral-offset", 0);
        String targetFile = yaml.getString("target.file", "").trim();
        BlockPoint targetOrigin = point(
                yaml,
                "target.origin",
                defaultTargetOrigin(targetDirection, targetDistance, targetYOffset, targetLateralOffset)
        );
        int targetLayers = Math.max(1, yaml.getInt("target.layers", 1));
        int targetSpacing = Math.max(1, yaml.getInt("target.spacing", 3));
        int hotdogBandWidth = Math.max(1, yaml.getInt("target.hotdog-band-width", 2));
        int pillarSpacing = Math.max(2, yaml.getInt("target.pillar-spacing", 3));

        boolean defaultRegen = targetType == TargetType.COBBLE_REGEN;
        RegenConfig regeneration = new RegenConfig(
                yaml.getBoolean("target.regeneration.enabled", defaultRegen),
                Math.max(0, yaml.getInt("target.regeneration.delay-ticks", 40)),
                Math.max(1, yaml.getInt("target.regeneration.interval-ticks", 10)),
                Math.max(1, yaml.getInt("target.regeneration.max-blocks-per-cycle", 32))
        );

        TargetStage legacyStage = new TargetStage(
                "legacy-target",
                targetType,
                targetMaterial,
                alternateMaterial,
                targetWidth,
                targetHeight,
                targetYOffset,
                targetLateralOffset,
                targetLayers,
                targetSpacing,
                0,
                hotdogBandWidth,
                pillarSpacing,
                regeneration
        );
        List<TargetStage> targetStages = stages(yaml, legacyStage);
        DurabilityConfig durability = durability(yaml);

        return new LabScenario(
                scenarioName,
                cannon,
                cannonOrigin,
                fireMode,
                primaryFireInput,
                fireInputs,
                directDispenser,
                Math.max(1, yaml.getInt("cannon.fire-pulse-ticks", 2)),
                suppressPasteSideEffects,
                settleBeforeFillTicks,
                fillToFireTicks,
                yaml.getBoolean("limits.enforce-dispenser-limit", true),
                targetType,
                targetDirection,
                targetFile,
                targetOrigin,
                targetMaterial,
                alternateMaterial,
                targetDistance,
                targetWidth,
                targetHeight,
                targetYOffset,
                targetLateralOffset,
                targetLayers,
                targetSpacing,
                hotdogBandWidth,
                pillarSpacing,
                targetStages,
                regeneration,
                durability,
                Math.max(1, yaml.getInt("run.shots", 1)),
                Math.max(1, yaml.getInt("run.volleys-per-shot", 1)),
                Math.max(1, yaml.getInt("run.volley-interval-ticks", 20)),
                Math.max(1, yaml.getInt("run.warmup-ticks", 20)),
                Math.max(20, yaml.getInt("run.max-shot-ticks", 240)),
                Math.max(2, yaml.getInt("run.quiet-ticks", 20)),
                yaml.getBoolean("run.shutdown-when-finished", false)
        );
    }

    private static List<TargetStage> stages(YamlConfiguration yaml, TargetStage legacy) {
        List<Map<?, ?>> configured = yaml.getMapList("target.stages");
        if (configured.isEmpty()) {
            return List.of(legacy);
        }

        List<TargetStage> result = new ArrayList<>();
        for (int index = 0; index < configured.size(); index++) {
            Map<?, ?> entry = configured.get(index);
            String prefix = "target.stages[" + index + "]";
            TargetType type = targetType(string(entry.get("type"), legacy.type().name()), prefix + ".type");
            RegenConfig fallbackRegen = type == TargetType.COBBLE_REGEN
                    ? new RegenConfig(true, legacy.regeneration().delayTicks(), legacy.regeneration().intervalTicks(), legacy.regeneration().maxBlocksPerCycle())
                    : legacy.regeneration();
            RegenConfig stageRegen = regeneration(entry.get("regeneration"), fallbackRegen);
            result.add(new TargetStage(
                    string(entry.get("name"), "stage-" + (index + 1)),
                    type,
                    material(entry.get("material"), defaultMaterial(type), prefix + ".material"),
                    material(entry.get("alternate-material"), legacy.alternateMaterial(), prefix + ".alternate-material"),
                    positive(entry.get("width"), legacy.width()),
                    positive(entry.get("height"), legacy.height()),
                    integer(entry.get("y-offset"), legacy.yOffset()),
                    integer(entry.get("lateral-offset"), legacy.lateralOffset()),
                    positive(entry.get("layers"), legacy.layers()),
                    positive(entry.get("spacing"), legacy.spacing()),
                    Math.max(0, integer(entry.get("gap-after"), 3)),
                    positive(entry.get("hotdog-band-width"), legacy.hotdogBandWidth()),
                    Math.max(2, integer(entry.get("pillar-spacing"), legacy.pillarSpacing())),
                    stageRegen
            ));
        }
        return result;
    }

    private static RegenConfig regeneration(Object raw, RegenConfig fallback) {
        Map<?, ?> values = raw instanceof Map<?, ?> map ? map : Map.of();
        return new RegenConfig(
                bool(values.get("enabled"), fallback.enabled()),
                Math.max(0, integer(values.get("delay-ticks"), fallback.delayTicks())),
                Math.max(1, integer(values.get("interval-ticks"), fallback.intervalTicks())),
                Math.max(1, integer(values.get("max-blocks-per-cycle"), fallback.maxBlocksPerCycle()))
        );
    }

    private static DurabilityConfig durability(YamlConfiguration yaml) {
        String rawMode = yaml.getString("target.durability.mode", "disabled");
        DurabilityMode mode;
        try {
            mode = DurabilityMode.valueOf(normalize(rawMode));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException(
                    "Unsupported target.durability.mode: " + rawMode,
                    exception
            );
        }

        Map<Material, Integer> materials = new LinkedHashMap<>();
        ConfigurationSection section = yaml.getConfigurationSection("target.durability.materials");
        if (section != null) {
            for (String key : section.getKeys(false)) {
                Material parsed = material(key, null, "target.durability.materials." + key);
                materials.put(parsed, Math.max(1, section.getInt(key, 1)));
            }
        }
        if (mode != DurabilityMode.DISABLED && materials.isEmpty()) {
            materials.put(Material.OBSIDIAN, 4);
            materials.put(Material.ANVIL, 3);
            materials.put(Material.CHIPPED_ANVIL, 3);
            materials.put(Material.DAMAGED_ANVIL, 3);
        }
        return new DurabilityConfig(
                mode,
                Math.max(1, yaml.getInt("target.durability.expiration-ticks", 1200)),
                yaml.getBoolean("target.durability.only-tnt", true),
                Math.max(0.5, yaml.getDouble("target.durability.hit-radius", 4.0)),
                materials
        );
    }

    private static BlockPoint defaultTargetOrigin(
            TargetDirection direction,
            int distance,
            int yOffset,
            int lateralOffset
    ) {
        return switch (direction) {
            case EAST -> new BlockPoint(distance, yOffset, lateralOffset);
            case WEST -> new BlockPoint(-distance, yOffset, lateralOffset);
            case SOUTH -> new BlockPoint(lateralOffset, yOffset, distance);
            case NORTH -> new BlockPoint(lateralOffset, yOffset, -distance);
        };
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

    private static int positive(Object value, int fallback) {
        return Math.max(1, integer(value, fallback));
    }

    private static int integer(Object value, int fallback) {
        return value instanceof Number number ? number.intValue() : fallback;
    }

    private static boolean bool(Object value, boolean fallback) {
        return value instanceof Boolean bool ? bool : fallback;
    }

    private static String string(Object value, String fallback) {
        if (value == null) {
            return fallback;
        }
        String result = String.valueOf(value).trim();
        return result.isEmpty() ? fallback : result;
    }

    private static Material material(String value, Material fallback, String path) {
        return material((Object) value, fallback, path);
    }

    private static Material material(Object value, Material fallback, String path) {
        if (value == null || String.valueOf(value).isBlank()) {
            return fallback;
        }
        Material parsed = Material.matchMaterial(String.valueOf(value), true);
        if (parsed == null || !parsed.isBlock()) {
            throw new IllegalArgumentException("Unsupported block material for " + path + ": " + value);
        }
        return parsed;
    }

    private static Material defaultMaterial(TargetType type) {
        return switch (type) {
            case COBBLE_REGEN, HOTDOG, PILLARS -> Material.COBBLESTONE;
            default -> Material.OBSIDIAN;
        };
    }

    private static TargetType targetType(String value, String path) {
        try {
            return TargetType.valueOf(normalize(value));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported " + path + ": " + value, exception);
        }
    }

    private static TargetDirection targetDirection(String value, String path) {
        try {
            return TargetDirection.valueOf(normalize(value));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported " + path + ": " + value, exception);
        }
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

    record DurabilityConfig(
            DurabilityMode mode,
            int expirationTicks,
            boolean onlyTnt,
            double hitRadius,
            Map<Material, Integer> materials
    ) {
        DurabilityConfig {
            materials = Map.copyOf(materials);
        }

        boolean enabled() {
            return mode != DurabilityMode.DISABLED && !materials.isEmpty();
        }

        int hitsToBreak(Material material) {
            return materials.getOrDefault(material, 1);
        }
    }

    record TargetStage(
            String name,
            TargetType type,
            Material material,
            Material alternateMaterial,
            int width,
            int height,
            int yOffset,
            int lateralOffset,
            int layers,
            int spacing,
            int gapAfter,
            int hotdogBandWidth,
            int pillarSpacing,
            RegenConfig regeneration
    ) {
    }

    enum FireMode {
        REDSTONE,
        BUTTON,
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

    enum DurabilityMode {
        DISABLED,
        AUTO,
        NATIVE,
        SIMULATE
    }
}
