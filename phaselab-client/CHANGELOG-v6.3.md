# PhaseLab v6.3

- Adds a second, independent `PhaseLabCampaignClient` entrypoint.
- Adds six bounded ordinary-input campaign profiles.
- Adds F5 profile selection and F11 run/abort controls.
- Preserves geometry-aware collision-height and corridor validation.
- Adds campaign-specific CSV and summary outputs.
- Keeps the exact `extremecraft.net:25565` client lock.
- Keeps runtime and travel caps.
- Does not construct movement packets or directly alter position, velocity, collision, bounding boxes, or server state.
