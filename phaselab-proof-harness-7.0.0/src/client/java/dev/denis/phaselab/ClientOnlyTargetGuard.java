package dev.denis.phaselab;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Locale;

/** Exact-address client-side authorization guard for owned/private test servers. */
public final class ClientOnlyTargetGuard {
    private static final String CONFIG_DIRECTORY = "phaselab-proof-harness";
    private static final String TARGETS_FILE = "authorized-targets.txt";

    private ClientOnlyTargetGuard() {
    }

    public static boolean isAuthorized(Path gameDirectory, String serverAddress) {
        if (gameDirectory == null || serverAddress == null || serverAddress.isBlank()) {
            return false;
        }

        Path directory = gameDirectory.resolve("config").resolve(CONFIG_DIRECTORY);
        Path file = directory.resolve(TARGETS_FILE);
        try {
            Files.createDirectories(directory);
            if (Files.notExists(file)) {
                Files.writeString(
                    file,
                    "# One exact owned/private test server address per line.\n"
                        + "# Examples: 127.0.0.1:25565 or private-clone.example:25565\n"
                        + "# The harness stays disabled until the current address appears here.\n",
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE_NEW,
                    StandardOpenOption.WRITE
                );
                return false;
            }

            String expected = normalizeForComparison(serverAddress);
            for (String rawLine : Files.readAllLines(file, StandardCharsets.UTF_8)) {
                String line = rawLine.trim();
                if (line.isEmpty() || line.startsWith("#")) {
                    continue;
                }
                if (normalizeForComparison(line).equals(expected)) {
                    return true;
                }
            }
        } catch (IOException ignored) {
            return false;
        }
        return false;
    }

    public static String normalizeForComparison(String value) {
        if (value == null) {
            return "";
        }
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        while (normalized.endsWith(".")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }
}
