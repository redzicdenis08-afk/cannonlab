package dev.denis.phaselab.stack;

import org.bukkit.Bukkit;
import org.bukkit.command.Command;
import org.bukkit.command.CommandSender;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.PluginDescriptionFile;
import org.bukkit.plugin.java.JavaPlugin;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;

public final class StackProbePlugin extends JavaPlugin {
    private Path lastExport;

    @Override
    public void onEnable() {
        getDataFolder().mkdirs();
        getLogger().info("PhaseLab StackProbe enabled; use /phasestack export as OP");
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!sender.hasPermission("phaselab.stack.admin")) {
            sender.sendMessage("No permission.");
            return true;
        }
        String action = args.length == 0 ? "status" : args[0].toLowerCase();
        if (action.equals("status")) {
            sender.sendMessage("Loaded plugins: " + Bukkit.getPluginManager().getPlugins().length
                + "; last export: " + (lastExport == null ? "none" : lastExport));
            return true;
        }
        if (!action.equals("export")) {
            return false;
        }
        try {
            lastExport = exportStack();
            sender.sendMessage("PhaseLab stack export written: " + lastExport);
        } catch (IOException | NoSuchAlgorithmException ex) {
            getLogger().severe("Stack export failed: " + ex);
            sender.sendMessage("Stack export failed; check server log.");
        }
        return true;
    }

    private Path exportStack() throws IOException, NoSuchAlgorithmException {
        Plugin[] loaded = Bukkit.getPluginManager().getPlugins();
        Arrays.sort(loaded, Comparator.comparing(plugin -> plugin.getName().toLowerCase()));
        List<String> plugins = new ArrayList<>();
        for (Plugin plugin : loaded) {
            plugins.add(pluginJson(plugin));
        }
        String json = "{\n"
            + "  \"schema_version\": 1,\n"
            + "  \"captured_at\": \"" + escape(Instant.now().toString()) + "\",\n"
            + "  \"server_name\": \"" + escape(Bukkit.getName()) + "\",\n"
            + "  \"server_version\": \"" + escape(Bukkit.getVersion()) + "\",\n"
            + "  \"bukkit_version\": \"" + escape(Bukkit.getBukkitVersion()) + "\",\n"
            + "  \"java_version\": \"" + escape(System.getProperty("java.version")) + "\",\n"
            + "  \"plugin_count\": " + loaded.length + ",\n"
            + "  \"plugins\": [\n    " + String.join(",\n    ", plugins) + "\n  ]\n"
            + "}\n";
        Path output = getDataFolder().toPath().resolve("stack-export.json");
        Files.writeString(output, json, StandardCharsets.UTF_8);
        return output.toAbsolutePath();
    }

    private String pluginJson(Plugin plugin) throws NoSuchAlgorithmException {
        PluginDescriptionFile description = plugin.getDescription();
        Path source = pluginSource(plugin);
        String hash = source == null ? null : sha256(source);
        return "{"
            + "\"name\":\"" + escape(description.getName()) + "\","
            + "\"version\":\"" + escape(description.getVersion()) + "\","
            + "\"main\":\"" + escape(description.getMain()) + "\","
            + "\"api_version\":" + nullable(description.getAPIVersion()) + ","
            + "\"enabled\":" + plugin.isEnabled() + ","
            + "\"authors\":" + stringArray(description.getAuthors()) + ","
            + "\"depend\":" + stringArray(description.getDepend()) + ","
            + "\"soft_depend\":" + stringArray(description.getSoftDepend()) + ","
            + "\"load_before\":" + stringArray(description.getLoadBefore()) + ","
            + "\"jar_path\":" + nullable(source == null ? null : source.toString()) + ","
            + "\"jar_sha256\":" + nullable(hash)
            + "}";
    }

    private Path pluginSource(Plugin plugin) {
        try {
            URI uri = plugin.getClass().getProtectionDomain().getCodeSource().getLocation().toURI();
            if (!"file".equalsIgnoreCase(uri.getScheme())) {
                return null;
            }
            Path path = Path.of(uri).toAbsolutePath().normalize();
            return Files.isRegularFile(path) ? path : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    private String sha256(Path path) throws NoSuchAlgorithmException {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = input.read(buffer)) >= 0) {
                if (read > 0) digest.update(buffer, 0, read);
            }
        } catch (IOException ex) {
            return null;
        }
        return HexFormat.of().formatHex(digest.digest());
    }

    private String stringArray(List<String> values) {
        List<String> encoded = values.stream().map(this::nullable).toList();
        return "[" + String.join(",", encoded) + "]";
    }

    private String nullable(String value) {
        return value == null ? "null" : "\"" + escape(value) + "\"";
    }

    private String escape(String value) {
        return value.replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\n", "\\n")
            .replace("\r", "\\r");
    }
}
