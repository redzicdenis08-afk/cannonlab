package online.coredispatch.mountlab;

import java.util.Locale;

/** String-only policy. It never performs DNS resolution. */
public final class LabAddressPolicy {
    private static final String APPROVED_SERVER = "extremecraft.net";
    private static final int APPROVED_PORT = 25565;

    private LabAddressPolicy() { }

    public static boolean isPrivateLabAddress(String rawAddress) {
        if (rawAddress == null) return false;
        String address = rawAddress.trim().toLowerCase(Locale.ROOT);
        if (address.isEmpty()) return false;

        String host;
        int explicitPort = -1;

        if (address.startsWith("[")) {
            int close = address.indexOf(']');
            if (close < 0) return false;
            host = address.substring(1, close);
            explicitPort = parsePortSuffix(address.substring(close + 1));
            if (explicitPort == -2) return false;
        } else {
            int firstColon = address.indexOf(':');
            int lastColon = address.lastIndexOf(':');
            if (firstColon > 0 && firstColon == lastColon) {
                host = address.substring(0, firstColon);
                explicitPort = parsePortSuffix(address.substring(firstColon));
                if (explicitPort == -2) return false;
            } else {
                host = address;
            }
        }

        while (host.endsWith(".")) host = host.substring(0, host.length() - 1);
        if (host.isEmpty()) return false;

        // Exact authorized endpoint. No wildcard subdomains and no alternate ports.
        if (host.equals(APPROVED_SERVER)) {
            return explicitPort == -1 || explicitPort == APPROVED_PORT;
        }

        if (host.equals("localhost") || host.endsWith(".localhost") || host.endsWith(".local")) return true;

        boolean ipv6 = host.indexOf(':') >= 0;
        if (ipv6) {
            if (host.equals("::1") || host.equals("0:0:0:0:0:0:0:1")) return true;
            if (host.startsWith("fc") || host.startsWith("fd")) return true;
            return host.startsWith("fe8") || host.startsWith("fe9") || host.startsWith("fea") || host.startsWith("feb");
        }

        String[] parts = host.split("\\.", -1);
        if (parts.length != 4) return false;
        int[] octets = new int[4];
        for (int i = 0; i < 4; i++) {
            if (parts[i].isEmpty() || parts[i].length() > 3) return false;
            try {
                octets[i] = Integer.parseInt(parts[i]);
            } catch (NumberFormatException ignored) {
                return false;
            }
            if (octets[i] < 0 || octets[i] > 255) return false;
        }

        if (octets[0] == 10 || octets[0] == 127) return true;
        if (octets[0] == 192 && octets[1] == 168) return true;
        if (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) return true;
        return octets[0] == 0 && octets[1] == 0 && octets[2] == 0 && octets[3] == 0;
    }

    /** Returns -1 for no port, -2 for invalid, or a valid port number. */
    private static int parsePortSuffix(String suffix) {
        if (suffix.isEmpty()) return -1;
        if (suffix.charAt(0) != ':' || suffix.length() == 1) return -2;
        int port = 0;
        for (int i = 1; i < suffix.length(); i++) {
            char c = suffix.charAt(i);
            if (c < '0' || c > '9') return -2;
            port = port * 10 + (c - '0');
            if (port > 65535) return -2;
        }
        return port > 0 ? port : -2;
    }
}
