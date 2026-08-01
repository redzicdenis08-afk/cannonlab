package online.coredispatch.mountlab;

/** Pure deterministic timing logic, isolated so it can be stress-tested without Minecraft. */
public final class SteerFlipPlanner {
    public enum Target { NONE, CONTROL, FALLBACK }
    public enum Reason { NONE, OVERLAP, MAX_SWAPS }
    public record Step(Target target, boolean lock, Reason reason) {
        public static final Step NONE = new Step(Target.NONE, false, Reason.NONE);
    }

    private final int intervalTicks;
    private final int maxSwaps;
    private int ticksSinceAction;
    private int swaps;
    private boolean nextControl;
    private boolean locked;

    public SteerFlipPlanner(int intervalTicks, int maxSwaps) {
        if (intervalTicks < 1 || intervalTicks > 20) {
            throw new IllegalArgumentException("intervalTicks must be 1..20");
        }
        if (maxSwaps < 2 || (maxSwaps & 1) != 0) {
            throw new IllegalArgumentException("maxSwaps must be an even number >= 2");
        }
        this.intervalTicks = intervalTicks;
        this.maxSwaps = maxSwaps;
    }

    public Step tick(double overlapDelta, double threshold) {
        if (locked) return Step.NONE;

        ticksSinceAction++;
        if (swaps >= 2 && threshold > 0.0 && overlapDelta + 1.0e-9 >= threshold) {
            locked = true;
            return new Step(Target.CONTROL, true, Reason.OVERLAP);
        }

        if (ticksSinceAction < intervalTicks) return Step.NONE;
        ticksSinceAction = 0;

        Target target = nextControl ? Target.CONTROL : Target.FALLBACK;
        nextControl = !nextControl;
        swaps++;

        if (swaps >= maxSwaps) {
            locked = true;
            return new Step(Target.CONTROL, true, Reason.MAX_SWAPS);
        }
        return new Step(target, false, Reason.NONE);
    }

    public int swaps() {
        return swaps;
    }

    public boolean locked() {
        return locked;
    }
}
