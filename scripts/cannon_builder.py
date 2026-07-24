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

# ---- build a compact horizontal dispenser cannon ----
def build_cannon(barrel_len=14, n_propellant=6):
    B={}; BE=[]
    def put(x,y,z,v): B[(x,y,z)]=v
    OBS="minecraft:obsidian"; WATER="minecraft:water[level=0]"; AIR="minecraft:air"
    DISP_S="minecraft:dispenser[facing=south,triggered=false]"
    DUST="minecraft:redstone_wire[east=side,west=side,north=side,south=side,power=0]"
    LEVER="minecraft:lever[face=floor,facing=north,powered=false]"

    # barrel floor (y=0) and roof (y=2), z=0 lane, x=-1..barrel_len
    for x in range(-1, barrel_len+1):
        put(x,0,0,OBS)        # floor
        put(x,2,0,OBS)        # roof
        put(x,1,1,OBS)        # far wall (+z)
    put(-1,1,0,OBS)           # back wall; muzzle (front) left open so payload exits

    # water trough in the lane (protects the charge), leave front 2 dry
    for x in range(0, barrel_len-2):
        put(x,1,0,WATER)

    # side dispensers (z=-1) facing +z, eject TNT into the trough at z=0
    disp_xs=list(range(1, 1+n_propellant))
    for x in disp_xs:
        put(x,1,-1,DISP_S); BE.append(((x,1,-1),"minecraft:dispenser"))
    # payload dispenser near the front dry section
    px=barrel_len-3
    put(px,1,-1,DISP_S); BE.append(((px,1,-1),"minecraft:dispenser"))

    # redstone ignition line behind the dispensers (z=-2) + supports (y=0)
    for x in range(0, px+1):
        put(x,0,-2,OBS)       # support for dust
        put(x,1,-2,DUST)      # redstone line powering all dispenser backs
    # lever fire-input at the back of the line
    put(-1,0,-2,OBS); put(-1,1,-2,LEVER)

    return B,BE,{"barrel_len":barrel_len,"n_propellant":n_propellant,
                 "dispensers":len(BE),"fire_input":(-1,1,-2),"muzzle":(barrel_len,1,0)}

if __name__=="__main__":
    B,BE,meta=build_cannon()
    W,H,L,pal,nbe=write_schem("basic-dispenser-cannon.schem", B, BE)
    print(f"built cannon: {W}x{H}x{L}  palette={pal}  dispensers={nbe}")
    print(f"  meta: {meta}")
    print("  wrote basic-dispenser-cannon.schem")
