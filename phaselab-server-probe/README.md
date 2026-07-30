# PhaseGuard Probe

Server-authoritative diagnostic plugin for an authorized Sakura/Paper/Factions test clone.

## Commands

- `/phaseprobe start <player> [ticks] [label]`
- `/phaseprobe snapshot [player]`
- `/phaseprobe stop [player]`
- `/phaseprobe listeners`
- `/phaseprobe status`

Session JSONL files are written to `plugins/PhaseGuardProbe/sessions/`.

The probe records player and vehicle position/velocity, mount state, claim owner, collision materials, water/lava occupancy, event cancellation at every Bukkit priority, and candidate plugins registered at the priority where cancellation changes.
