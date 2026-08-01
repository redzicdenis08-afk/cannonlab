package online.coredispatch.mountlab;

import java.util.Locale;

/** String-only policy. It never performs DNS resolution. */
public final class LabAddressPolicy {
    private LabAddressPolicy() { }

    public static boolean isPrivateLabAddress(String rawAddress) {
        if (rawAddress == null) return false;
        String host = rawAddress.trim().toLowerCase(Locale.ROOT);
        if (host.isEmpty()) return false;

        if (host.startsWith("[")) {
            int close = host.indexOf(']');
            if (close < 0) return false;
            String suffix = host.substring(close + 1);
            if (!validPortSuffix(suffix)) return false;
            host = host.substring(1, close);
        } else {
            int firstColon = host.indexOf(':');
            int lastColon = host.lastIndexOf(':');
            if (firstColon > 0 && firstColon == lastColon) {
                String suffix = host.substring(firstColon);
                if (!validPortSuffix(suffix)) return false;
                host = host.substring(0, firstColon);
            }
        }

        while (host.endsWith(".")) host = host.substring(0, host.length() - 1);
        if (host.isEmpty()) return false;
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

    private static boolean validPortSuffix(String suffix) {
        if (suffix.isEmpty()) return true;
        if (suffix.charAt(0) != ':' || suffix.length() == 1) return false;
        int port = 0;
        for (int i = 1; i < suffix.length(); i++) {
            char c = suffix.charAt(i);
            if (c < '0' || c > '9') return false;
            port = port * 10 + (c - '0');
            if (port > 65535) return false;
        }
        return port > 0;
    }
}
