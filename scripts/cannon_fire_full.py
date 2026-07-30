#!/usr/bin/env python3
"""
Full cannon firing sim — Sakura 26.1.2. Models the REAL mechanism:
  charge TNT (in water) explodes -> knockback launches the projectile AND
  explosion-primes it (fuse 10..29) -> projectile flies -> detonates downrange.
This lets us test a cannon design's LAUNCH without a live server.
"""
from __future__ import annotations
import math, random

GRAVITY, DRAG = 0.04, 0.98

def knockback(cx,cy,cz, tx,ty,tz, radius=4.0, mult=1.0):
    dx,dy,dz=tx-cx,ty-cy,tz-cz
    d=math.sqrt(dx*dx+dy*dy+dz*dz)
    if d==0: return (mult,0.0,0.0)
    s=max(0.0,1.0-d/radius/2.0)*mult
    return (dx/d*s, dy/d*s, dz/d*s)

def simulate_shot(n_charge, charge_pos, proj_pos, prime_fuse, wall_x=15.0, wall_ylo=0, wall_yhi=10):
    """
    All n_charge detonate at charge_pos on tick 0. Projectile gets summed knockback
    + explosion-prime fuse, flies, and DETONATES on wall impact (block collision) or
    when its fuse expires. Returns whether it hit the wall.
    """
    px,py,pz = proj_pos
    vx=vy=vz=0.0
    for _ in range(n_charge):
        kx,ky,kz=knockback(*charge_pos, px,py,pz)
        vx+=kx; vy+=ky; vz+=kz
    exit_v=math.sqrt(vx*vx+vy*vy+vz*vz)
    f=prime_fuse; t=0; x,y,z=px,py,pz
    while f>0:
        vy-=GRAVITY
        x+=vx; y+=vy; z+=vz
        vx*=DRAG; vy*=DRAG; vz*=DRAG
        f-=1; t+=1
        if x>=wall_x:                       # collision: projectile hits the wall -> detonates
            hit = wall_ylo-1 <= y <= wall_yhi+1
            return {"hit":hit,"exit_v":round(exit_v,2),"ex":round(x,1),"ey":round(y,1),
                    "ticks":t,"reason":"wall-impact" if hit else "over/under wall"}
    return {"hit":False,"exit_v":round(exit_v,2),"ex":round(x,1),"ey":round(y,1),
            "ticks":t,"reason":"fuse-expired-in-flight (short)"}

def banner(s): print("\n"+"="*62+f"\n{s}\n"+"="*62)

if __name__=="__main__":
    banner("MINIMAL CANNON: charge behind projectile -> hit a wall 15 blocks out")
    print("  projectile (0,1.5,0); charge 1 block behind (-1,1.5,0); wall at x=15, y0-10.")
    print("  projectile self-primes off the blast (fuse 10-29) and detonates on impact.\n")
    for n in [1,2,3,4,5,6,8]:
        rows=[simulate_shot(n,(-1,1.5,0),(0,1.5,0),pf,wall_x=15) for pf in range(10,30)]
        hits=sum(1 for r in rows if r["hit"])
        eys=[r["ey"] for r in rows]
        print(f"  {n:>2} charge (exit_v={rows[0]['exit_v']:5.2f}): hits wall on {hits}/20 prime-fuses"
              f"  | impact y range {min(eys):.1f}..{max(eys):.1f}")

    banner("VERDICT: minimal design that reliably hits the 15-block wall")
    best=None
    for n in [1,2,3,4,5,6,8]:
        rows=[simulate_shot(n,(-1,1.5,0),(0,1.5,0),pf,wall_x=15) for pf in range(10,30)]
        frac=sum(1 for r in rows if r["hit"])/len(rows)
        if frac>=0.9 and best is None:
            best=(n,frac)
    if best:
        n,frac=best
        print(f"  MINIMAL WORKING (in sim): {n} charges behind the projectile -> hits 15-block wall {frac*100:.0f}% of the time.")
        print(f"  BUILD RULE: {n} charge dispensers 1 block behind 1 projectile dispenser, same axis,")
        print(f"  in a water trough; single ignition. Higher wall = more charges (velocity). This is the")
        print(f"  real minimal cannon: it works because the WALL stops the projectile and it detonates on impact.")
    else:
        print("  even 8 charges didn't reliably hit; wall too far/tall for point-blank single-charge.")
