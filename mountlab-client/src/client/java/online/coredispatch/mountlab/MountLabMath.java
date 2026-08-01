package online.coredispatch.mountlab;

public final class MountLabMath {
    private static final double EPSILON = 1.0e-7;

    private MountLabMath() { }

    /**
     * Returns horizontal minimum-translation depth. Vertical contacts such as floors and ceilings return zero.
     */
    public static double horizontalPenetration(double overlapX, double overlapY, double overlapZ) {
        if (overlapX <= EPSILON || overlapY <= EPSILON || overlapZ <= EPSILON) return 0.0;
        if (overlapY <= overlapX + EPSILON && overlapY <= overlapZ + EPSILON) return 0.0;
        return Math.min(overlapX, overlapZ);
    }
}
