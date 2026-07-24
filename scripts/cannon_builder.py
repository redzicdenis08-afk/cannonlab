#!/usr/bin/env python3
"""
CannonLab cannon_builder — generates a real cannon and emits a Sponge v2 .schem.

Builds a compact horizontal dispenser cannon (fires +x): obsidian barrel, water
trough (protects the charge), a row of side dispensers that eject TNT into the
trough, a payload dispenser, and a redstone ignition line with a lever fire-input.
tntfill-compatible (empty dispensers), lab fire-mode: redstone or button.

Honesty: this is a structurally-valid, physics-plausible build. Firing is
confirmed in-sim (payload launches); a live Sakura canary is the final proof.
"""
from __future__ import annotations
import gzip, io, struct, math

# ---- minimal Sponge v2 writer (matches CannonLab schem-audit.py reader) ----
COMPOUND,INT,SHORT,STRING,BYTE_ARRAY,INT_ARRAY = 10,3,2,8,7,11

def _name(s, v):
    r=v.encode(); s.write(struct.pack(">H",len(r))); s.write(r)
def _hdr(s,tag,nm): s.write(struct.pack(">B",tag)); _name(s,nm)
def _varint(vals):
    out=bytearray()
    for v in vals:
        while True:
            b=v&0x7F; v>>=7; out.append(b|(0x80 if v else 0))
            if not v: break
    return bytes(out)

def write_schem(path, blocks, block_entities, data_version=3465):
    xs=[p[0] for p in blocks]; ys=[p[1] for p in blocks]; zs=[p[2] for p in blocks]
    minx,miny,minz=min(xs),min(ys),min(zs)
    W=max(xs)-minx+1; H=max(ys)-miny+1; L=max(zs)-minz+1
    nb={(x-minx,y-miny,z-minz):v for (x,y,z),v in blocks.items()}
    states=sorted(set(nb.values()))
    if "minecraft:air" in states: states.remove("minecraft:air")
    states=["minecraft:air"]+states
    pal={s:i for i,s in enumerate(states)}
    ids=[]
    for y in range(H):
        for z in range(L):
            for x in range(W):
                ids.append(pal.get(nb.get((x,y,z),"minecraft:air"),0))
    bd=_varint(ids)
    out=io.BytesIO()
    _hdr(out,COMPOUND,"Schematic")
    _hdr(out,COMPOUND,"Metadata")
    for a in ("X","Y","Z"): _hdr(out,INT,f"WEOffset{a}"); out.write(struct.pack(">i",0))
    out.write(b"\x00")
    _hdr(out,COMPOUND,"Palette")
    for s,i in pal.items(): _hdr(out,INT,s); out.write(struct.pack(">i",i))
    out.write(b"\x00")
    _hdr(out,11 if False else 9,"BlockEntities"); # LIST
    # LIST header: element type COMPOUND, count
    out.write(struct.pack(">B",COMPOUND)); out.write(struct.pack(">i",len(block_entities)))
    for (x,y,z),bid in block_entities:
        nx,ny,nz=x-minx,y-miny,z-minz
        _hdr(out,STRING,"Id"); _name(out,bid)
        _hdr(out,INT_ARRAY,"Pos"); out.write(struct.pack(">i",3)); out.write(struct.pack(">iii",nx,ny,nz))
        out.write(b"\x00")
    for tag,nm,val,fmt in ((INT,"DataVersion",data_version,"i"),(SHORT,"Height",H,"h"),
                           (SHORT,"Length",L,"h"),(INT,"PaletteMax",len(pal),"i"),
                           (INT,"Version",2,"i"),(SHORT,"Width",W,"h")):
        _hdr(out,tag,nm); out.write(struct.pack(">"+fmt,val))
    _hdr(out,BYTE_ARRAY,"BlockData"); out.write(struct.pack(">i",len(bd))); out.write(bd)
    _hdr(out,INT_ARRAY,"Offset"); out.write(struct.pack(">i",3)); out.write(struct.pack(">iii",0,0,0))
    out.write(b"\x00")
    open(path,"wb").write(gzip.compress(out.getvalue(),mtime=0))
    return W,H,L,len(pal),len(block_entities)

# ---- build a horizontal dispenser cannon (v2: axis-aligned charges, EAST facing) ----
def build_cannon(barrel_len=16, n_propellant=6):
    """
    v2 fixes v1's two failures (sim + live diagnosed):
      * charges now sit BEHIND the payload on the fire axis (push +x), not on the side
      * every dispenser faces EAST (+x) so /tntfill detects them and they fire down-barrel
    Layout: 3-wide barrel (z=-1..1), 2-tall; a 3x2 back charge grid of 6 dispensers at
    x=0 facing east; payload dispenser at the front; redstone line + lever fire-input.
    """
    B={}; BE=[]
    def put(x,y,z,v): B[(x,y,z)]=v
    OBS="minecraft:obsidian"; WATER="minecraft:water[level=0]"
    DISP_E="minecraft:dispenser[facing=east,triggered=false]"   # faces fire direction
    DUST="minecraft:redstone_wire[east=side,west=side,north=side,south=side,power=0]"
    LEVER="minecraft:lever[face=floor,facing=north,powered=false]"

    # 3-wide barrel shell: floor y=0, roof y=3, side walls z=-2 and z=2, x=0..barrel_len
    for x in range(0, barrel_len+1):
        for z in range(-1,2):
            put(x,0,z,OBS)      # floor
            put(x,3,z,OBS)      # roof
        put(x,1,-2,OBS); put(x,2,-2,OBS)   # -z wall
        put(x,1, 2,OBS); put(x,2, 2,OBS)   # +z wall

    # water trough on the barrel floor (protects the charge), leave front 3 dry
    for x in range(1, barrel_len-2):
        for z in range(-1,2):
            put(x,1,z,WATER)

    # 6 charge dispensers: 3x2 grid at the BACK (x=0), facing EAST into the barrel
    cnt=0
    for y in (1,2):
        for z in (-1,0,1):
            if cnt>=n_propellant: break
            put(0,y,z,DISP_E); BE.append(((0,y,z),"minecraft:dispenser")); cnt+=1

    # payload dispenser at the front-center, facing EAST (fires the projectile out the muzzle)
    px=barrel_len-2
    put(px,1,0,DISP_E); BE.append(((px,1,0),"minecraft:dispenser"))

    # redstone ignition line ON TOP of the roof (y=4, every dust sits on roof obsidian
    # at y=3 -> fully supported) running back to the lever fire-input.
    for x in range(0, px+1):
        put(x,4,0,DUST)                 # supported by roof obsidian below
    put(0,4,-1,OBS); put(0,5,-1,LEVER)  # lever fire-input at the back of the line

    return B,BE,{"version":2,"barrel_len":barrel_len,"n_propellant":n_propellant,
                 "dispensers":len(BE),"fire_input":(-1,4,-3),"muzzle":(barrel_len,1,0),
                 "all_dispensers_face":"east"}

if __name__=="__main__":
    B,BE,meta=build_cannon()
    W,H,L,pal,nbe=write_schem("basic-dispenser-cannon-v2.schem", B, BE)
    print(f"built cannon: {W}x{H}x{L}  palette={pal}  dispensers={nbe}")
    print(f"  meta: {meta}")
    print("  wrote basic-dispenser-cannon-v2.schem")
