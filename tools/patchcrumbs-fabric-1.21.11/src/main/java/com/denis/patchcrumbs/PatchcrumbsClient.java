package com.denis.patchcrumbs;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.core.particles.ParticleTypes;
import net.minecraft.network.chat.Component;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Iterator;
import java.util.Locale;

public final class PatchcrumbsClient implements ClientModInitializer {
    private static final Deque<Crumb> CRUMBS = new ArrayDeque<>();
    private static final int MAX_CRUMBS = 24;
    private static final int CRUMB_LIFETIME_TICKS = 30 * 20;
    private static final int MERGE_WINDOW_TICKS = 8;
    private static final double MERGE_DISTANCE_SQUARED = 3.0 * 3.0;

    private static int clientTick;

    @Override
    public void onInitializeClient() {
        ClientTickEvents.END_CLIENT_TICK.register(PatchcrumbsClient::tick);
    }

    public static void recordExplosion(Vec3 center, float radius, int blockCount) {
        synchronized (CRUMBS) {
            for (Iterator<Crumb> iterator = CRUMBS.descendingIterator(); iterator.hasNext();) {
                Crumb crumb = iterator.next();
                if (clientTick - crumb.lastTick > MERGE_WINDOW_TICKS) {
                    break;
                }
                if (crumb.center.distanceToSqr(center) <= MERGE_DISTANCE_SQUARED) {
                    crumb.merge(center, radius, blockCount, clientTick);
                    return;
                }
            }

            CRUMBS.addLast(new Crumb(center, radius, blockCount, clientTick));
            while (CRUMBS.size() > MAX_CRUMBS) {
                CRUMBS.removeFirst();
            }
        }
    }

    private static void tick(Minecraft client) {
        clientTick++;

        synchronized (CRUMBS) {
            while (!CRUMBS.isEmpty() && clientTick - CRUMBS.peekFirst().lastTick > CRUMB_LIFETIME_TICKS) {
                CRUMBS.removeFirst();
            }
        }

        if (client.player == null || client.level == null) {
            return;
        }

        Crumb selected = selectBestCrumb(client.player.position());
        if (selected == null) {
            return;
        }

        int age = clientTick - selected.lastTick;
        if (age > CRUMB_LIFETIME_TICKS) {
            return;
        }

        if ((clientTick & 1) == 0) {
            double distance = Math.sqrt(client.player.position().distanceToSqr(selected.center));
            String wallAxis = Math.abs(selected.center.x - client.player.getX()) >= Math.abs(selected.center.z - client.player.getZ())
                    ? "X-wall"
                    : "Z-wall";

            int blockX = (int) Math.floor(selected.center.x);
            int blockY = (int) Math.floor(selected.center.y);
            int blockZ = (int) Math.floor(selected.center.z);

            String hud = String.format(
                    Locale.ROOT,
                    "Patchcrumb  X %d  Y %d  Z %d  | %s | %.1fm | %d blast%s",
                    blockX,
                    blockY,
                    blockZ,
                    wallAxis,
                    distance,
                    selected.explosionCount,
                    selected.explosionCount == 1 ? "" : "s"
            );
            client.player.displayClientMessage(Component.literal(hud), true);
        }

        if (age <= 10 * 20) {
            renderParticleMarker(client, selected.center);
        }
    }

    private static Crumb selectBestCrumb(Vec3 playerPosition) {
        synchronized (CRUMBS) {
            Crumb best = null;
            double bestScore = Double.POSITIVE_INFINITY;

            for (Crumb crumb : CRUMBS) {
                int age = clientTick - crumb.lastTick;
                if (age > CRUMB_LIFETIME_TICKS) {
                    continue;
                }

                double distanceSquared = playerPosition.distanceToSqr(crumb.center);
                double agePenalty = age * 0.35;
                double score = distanceSquared + agePenalty;
                if (score < bestScore) {
                    bestScore = score;
                    best = crumb;
                }
            }

            return best;
        }
    }

    private static void renderParticleMarker(Minecraft client, Vec3 center) {
        double baseX = Math.floor(center.x) + 0.5;
        double baseY = Math.floor(center.y) + 0.15;
        double baseZ = Math.floor(center.z) + 0.5;

        client.level.addParticle(ParticleTypes.END_ROD, baseX, baseY, baseZ, 0.0, 0.015, 0.0);
        client.level.addParticle(ParticleTypes.END_ROD, baseX, baseY + 0.75, baseZ, 0.0, 0.015, 0.0);
        client.level.addParticle(ParticleTypes.END_ROD, baseX, baseY + 1.5, baseZ, 0.0, 0.015, 0.0);

        if (clientTick % 3 == 0) {
            client.level.addParticle(ParticleTypes.END_ROD, baseX + 0.45, baseY + 0.75, baseZ + 0.45, 0.0, 0.0, 0.0);
            client.level.addParticle(ParticleTypes.END_ROD, baseX - 0.45, baseY + 0.75, baseZ + 0.45, 0.0, 0.0, 0.0);
            client.level.addParticle(ParticleTypes.END_ROD, baseX + 0.45, baseY + 0.75, baseZ - 0.45, 0.0, 0.0, 0.0);
            client.level.addParticle(ParticleTypes.END_ROD, baseX - 0.45, baseY + 0.75, baseZ - 0.45, 0.0, 0.0, 0.0);
        }
    }

    private static final class Crumb {
        private Vec3 center;
        private float maxRadius;
        private int totalBlockCount;
        private int explosionCount;
        private int lastTick;

        private Crumb(Vec3 center, float radius, int blockCount, int tick) {
            this.center = center;
            this.maxRadius = radius;
            this.totalBlockCount = blockCount;
            this.explosionCount = 1;
            this.lastTick = tick;
        }

        private void merge(Vec3 newCenter, float radius, int blockCount, int tick) {
            double oldWeight = explosionCount;
            double newWeight = oldWeight + 1.0;
            center = center.scale(oldWeight).add(newCenter).scale(1.0 / newWeight);
            maxRadius = Math.max(maxRadius, radius);
            totalBlockCount += blockCount;
            explosionCount++;
            lastTick = tick;
        }
    }
}
