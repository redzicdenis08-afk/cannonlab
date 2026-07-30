#!/usr/bin/env python3
"""
Cannon stress harness — Sakura 26.1.2 physics. Diagnoses v1 failure and finds
a launching design by sweeping geometry. Uses physics_core constants.
"""
from __future__ import annotations
import math

GRAVITY, DRAG, FUSE = 0.04, 0.98, 79

def knockback(cx,cy,cz, tx,ty,tz, radius=4.0, mult=1.0):
    dx,dy,dz=tx-cx,ty-cy,tz-cz
    d=math.sqrt(dx*dx+dy*dy+dz*dz)
    if d==0: return (mult,0.0,0.0)
    s=max(0.0,1.0-d/radius/2.0)*mult
    return (dx/d*s, dy/d*s, dz/d*s)

def fire_inline(n_charges, charge_offset, proj_fuse, launch_y=1.5):
    """
    CORRECT pattern: n charges stacked directly BEHIND the projectile on the
    fire axis (-x), all detonate tick 0. Projectile launches +x, then flies.
    charge_offset = blocks the charge stack sits behind the projectile.
    Returns (exit_vx, explode_x, explode_y, ticks).
    """
    vx=vy=vz=0.0
    for _ in range(n_charges):
        kx,ky,kz=knockback(-charge_offset,launch_y,0, 0,launch_y,0)
        vx+=kx; vy+=ky; vz+=kz
    x,y,z=0.0,launch_y,0.0; f=proj_fuse; t=0
    while f>0:
        vy-=GRAVITY
        x+=vx; y+=vy; z+=vz
        vx*=DRAG; vy*=DRAG; vz*=DRAG
        f-=1; t+=1
    return (n_charges*knockback(-charge_offset,launch_y,0,0,launch_y,0)[0], x, y, t)

def banner(s): print("\n"+"="*62+f"\n{s}\n"+"="*62)

if __name__=="__main__":
    banner("DIAGNOSIS: why v1 failed")
    print("  v1 put dispensers on the SIDE (z=-1) facing +z into water.")
    print("  Problems the sim + screenshot expose:")
    print("   1. charges fired PERPENDICULAR to the barrel -> ~0 forward push on payload")
    print("   2. /tntfill found 'no empty dispensers' -> dispenser facing/'powered' wrong")
    print("   3. single pulse, no charge-behind-payload geometry -> nothing launches")
    print("  FIX: charges must sit BEHIND the payload on the fire axis, pushing +x.")

    banner("STRESS: inline charges behind payload — exit velocity vs count")
    for n in [1,2,4,6,8,12,16]:
        vx,ex,ey,t=fire_inline(n, charge_offset=1.0, proj_fuse=FUSE)
        print(f"  {n:>2} charges -> exit vx={vx:5.2f}  (full-fuse flight lands x={ex:6.1f} y={ey:6.1f})")
    print("  LEARNING: exit velocity is linear in charge count; full 79 fuse overshoots.")

    banner("STRESS: tune fuse to hit a wall 30 blocks out (per charge count)")
    targets=[30]
    for n in [4,6,8,12]:
        found=None
        for f in range(2,80):
            vx,ex,ey,t=fire_inline(n,1.0,f)
            if abs(ex-30)<=1.5 and ey>=0.5:
                found=(f,ex,ey); break
        if found:
            f,ex,ey=found
            print(f"  {n:>2} charges: fuse {f:>2} -> hits x={ex:.1f} y={ey:.1f}  WORKS")
        else:
            print(f"  {n:>2} charges: no fuse lands it at 30 cleanly")

    banner("STRESS: charge offset sensitivity (how far behind payload)")
    for off in [0.5,1.0,2.0,3.0]:
        vx,ex,ey,t=fire_inline(6, off, 6)
        print(f"  offset {off}: exit vx={vx:.2f}  (closer charges push harder)")

    banner("V2 DESIGN (from the sim)")
    print("  Barrel along +x, water trough. Payload dispenser at the FRONT.")
    print("  Charge dispensers stacked directly BEHIND payload on the axis,")
    print("  ALL facing the fire direction (+x) so /tntfill detects them and they")
    print("  dispense INTO the barrel line. Single redstone pulse fires all.")
    print("  Sim says ~6 charges + short payload fuse launches to 30 blocks.")
