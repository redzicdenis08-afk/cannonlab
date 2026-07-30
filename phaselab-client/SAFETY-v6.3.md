# PhaseLab v6.3 Safety Invariants

The campaign runner is player-only and hard-locked to `extremecraft.net:25565`.

CI verifies that the campaign class does not reference:

- `ServerboundMoveVehiclePacket`
- `ServerboundMovePlayerPacket`
- `setPos`
- `absMoveTo`
- `teleportTo`
- `setDeltaMovement`
- `noPhysics`
- `ClientPlayNetworking`

The runner only changes ordinary forward, back, left, right, and shift key states, releases them on abort/disconnect, and enforces runtime and travel caps.
