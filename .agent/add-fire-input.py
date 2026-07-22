#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / "src/main/java/io/github/redzicdenis08afk/cannonlab/LabRunController.java"
text = path.read_text(encoding="utf-8")
old = '''        for (PulseState pulse : uniquePulses.values()) {
            plugin.getLogger().info("Redstone fire at " + coordinates(pulse.location())
                    + " | previous=" + pulse.previousType()
                    + " | neighbours=" + describeNeighbours(pulse.block()));
            pulse.block().setType(Material.REDSTONE_BLOCK, true);
'''
new = '''        for (PulseState pulse : uniquePulses.values()) {
            plugin.getLogger().info("Redstone fire at " + coordinates(pulse.location())
                    + " | previous=" + pulse.previousType()
                    + " | neighbours=" + describeNeighbours(pulse.block()));
            recorder.recordControlEvent(
                    "FIRE_INPUT",
                    pulse.location(),
                    "previous=" + pulse.previousType() + ";pulse_ticks=" + scenario.firePulseTicks()
            );
            pulse.block().setType(Material.REDSTONE_BLOCK, true);
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one redstone pulse block, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Explicit FIRE_INPUT telemetry inserted.")
