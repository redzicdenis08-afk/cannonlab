package online.coredispatch.mountlab;

import java.util.Random;

public final class MountLabStress {
    public static void main(String[] args) {
        testPlannerExactTiming();
        testOverlapLock();
        testAddressPolicy();
        testCollisionMetric();
        fuzzPlanner(250_000);
        System.out.println("MountLab pure-logic stress tests passed (250,000 randomized schedules).");
    }

    private static void testPlannerExactTiming() {
        for (int interval = 1; interval <= 3; interval++) {
            for (int max : new int[]{4, 6, 8, 10, 12, 16}) {
                SteerFlipPlanner planner = new SteerFlipPlanner(interval, max);
                int actionCount = 0;
                for (int tick = 1; tick <= interval * max; tick++) {
                    SteerFlipPlanner.Step step = planner.tick(0.0, 0.04);
                    boolean actionTick = tick % interval == 0;
                    check((step.target() != SteerFlipPlanner.Target.NONE) == actionTick, "wrong action cadence");
                    if (actionTick) actionCount++;
                    if (tick < interval * max) check(!step.lock(), "locked early");
                }
                check(planner.locked(), "did not lock at max");
                check(planner.swaps() == max, "wrong swap total");
                check(actionCount == max, "wrong action total");
                check(planner.tick(999, 0.01).equals(SteerFlipPlanner.Step.NONE), "acted after lock");
            }
        }
    }

    private static void testOverlapLock() {
        SteerFlipPlanner planner = new SteerFlipPlanner(1, 16);
        check(!planner.tick(0.10, 0.04).lock(), "overlap lock before two swaps");
        check(!planner.tick(0.10, 0.04).lock(), "overlap lock before two completed swaps");
        SteerFlipPlanner.Step lock = planner.tick(0.04, 0.04);
        check(lock.lock() && lock.reason() == SteerFlipPlanner.Reason.OVERLAP, "overlap did not lock");
        check(lock.target() == SteerFlipPlanner.Target.CONTROL, "overlap lock did not force control");
    }

    private static void testAddressPolicy() {
        String[] allowed = {"localhost", "localhost:25565", "dev.local:25565", "127.0.0.1", "127.8.1.2:1",
            "10.0.0.5:25565", "172.16.0.1", "172.31.255.254", "192.168.1.9", "[::1]:25565", "fd00::1", "fe80::1",
            "extremecraft.net", "extremecraft.net:25565", "EXTREMECRAFT.NET:25565", "extremecraft.net.:25565"};
        String[] denied = {"example.com", "8.8.8.8", "172.15.1.1", "172.32.1.1", "192.169.1.1", "1.2.3.4:25565",
            "999.1.1.1", "10.example.com", "fctest.com", "fd-lab.example", "[::1]evil", "10.0.0.1:evil", "10.0.0.1:70000", "", "[]:25565",
            "extremecraft.net:25566", "play.extremecraft.net", "evil-extremecraft.net", "extremecraft.net.evil"};
        for (String value : allowed) check(LabAddressPolicy.isPrivateLabAddress(value), "should allow " + value);
        for (String value : denied) check(!LabAddressPolicy.isPrivateLabAddress(value), "should deny " + value);
    }

    private static void testCollisionMetric() {
        check(close(MountLabMath.horizontalPenetration(0.03, 1.0, 0.8), 0.03), "x wall depth");
        check(close(MountLabMath.horizontalPenetration(0.8, 0.01, 0.8), 0.0), "floor false positive");
        check(close(MountLabMath.horizontalPenetration(0.2, 1.0, 0.05), 0.05), "corner depth");
        check(close(MountLabMath.horizontalPenetration(0.0, 1.0, 1.0), 0.0), "non-overlap");
    }

    private static void fuzzPlanner(int iterations) {
        Random random = new Random(0x4D4F554E544C4142L);
        for (int i = 0; i < iterations; i++) {
            int interval = 1 + random.nextInt(3);
            int[] options = {4, 6, 8, 10, 12, 16};
            int max = options[random.nextInt(options.length)];
            double threshold = random.nextBoolean() ? 0.0 : new double[]{0.02, 0.04, 0.08, 0.12}[random.nextInt(4)];
            SteerFlipPlanner planner = new SteerFlipPlanner(interval, max);
            int previousSwaps = 0;
            int actions = 0;
            for (int tick = 1; tick <= 200 && !planner.locked(); tick++) {
                double overlap = random.nextDouble() < 0.04 ? random.nextDouble() * 0.2 : 0.0;
                SteerFlipPlanner.Step step = planner.tick(overlap, threshold);
                if (step.target() != SteerFlipPlanner.Target.NONE) actions++;
                check(planner.swaps() >= previousSwaps, "swap count went backwards");
                check(planner.swaps() - previousSwaps <= 1, "multiple swaps in one tick");
                check(planner.swaps() <= max, "exceeded max swaps");
                previousSwaps = planner.swaps();
                if (step.lock()) check(step.target() == SteerFlipPlanner.Target.CONTROL, "lock without control target");
            }
            check(planner.locked(), "fuzz schedule failed to terminate");
            check(actions <= max, "too many actions");
        }
    }

    private static boolean close(double a, double b) {
        return Math.abs(a - b) < 1.0e-9;
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
