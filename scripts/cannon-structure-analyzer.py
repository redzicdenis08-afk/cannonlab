import gzip, struct, sys, os
from collections import Counter, defaultdict

class R:
    def __init__(s, d): s.d = d; s.i = 0
    def u1(s): v = s.d[s.i]; s.i += 1; return v
    def b1(s): v = struct.unpack('>b', s.d[s.i:s.i+1])[0]; s.i += 1; return v
    def i2(s): v = struct.unpack('>h', s.d[s.i:s.i+2])[0]; s.i += 2; return v
    def u2(s): v = struct.unpack('>H', s.d[s.i:s.i+2])[0]; s.i += 2; return v
    def i4(s): v = struct.unpack('>i', s.d[s.i:s.i+4])[0]; s.i += 4; return v
    def i8(s): v = struct.unpack('>q', s.d[s.i:s.i+8])[0]; s.i += 8; return v
    def f4(s): v = struct.unpack('>f', s.d[s.i:s.i+4])[0]; s.i += 4; return v
    def f8(s): v = struct.unpack('>d', s.d[s.i:s.i+8])[0]; s.i += 8; return v
    def st(s):
        n = s.u2(); v = s.d[s.i:s.i+n].decode('utf-8', 'replace'); s.i += n; return v

def payload(r, t):
    if t == 1: return r.b1()
    if t == 2: return r.i2()
    if t == 3: return r.i4()
    if t == 4: return r.i8()
    if t == 5: return r.f4()
    if t == 6: return r.f8()
    if t == 7:
        n = r.i4(); return [r.b1() for _ in range(n)]
    if t == 8: return r.st()
    if t == 9:
        it = r.u1(); n = r.i4(); return [payload(r, it) for _ in range(n)]
    if t == 10:
        d = {}
        while True:
            tt = r.u1()
            if tt == 0: break
            nm = r.st(); d[nm] = payload(r, tt)
        return d
    if t == 11:
        n = r.i4(); return [r.i4() for _ in range(n)]
    if t == 12:
        n = r.i4(); return [r.i8() for _ in range(n)]
    raise ValueError(t)

def parse(d):
    r = R(d); t = r.u1(); assert t == 10; r.st(); return payload(r, t)

def decode_packed(vals, count, psize):
    bits = max(2, (max(1, psize) - 1).bit_length())
    u = [v & ((1 << 64) - 1) for v in vals]; mask = (1 << bits) - 1; res = []
    for idx in range(count):
        bi = idx * bits; li, off = divmod(bi, 64); v = (u[li] >> off) & mask
        if off + bits > 64: v |= (u[li+1] << (64 - off)) & mask
        res.append(v)
    return res

path = sys.argv[1]
raw = open(path, 'rb').read()
try: data = gzip.decompress(raw)
except Exception: data = raw
root = parse(data)
regions = root.get('Regions', {})
facing_by_block = defaultdict(Counter)
sand_cols = defaultdict(list)
pos_by_type = defaultdict(list)
for rn, reg in regions.items():
    size = reg.get('Size', {}); dims = tuple(abs(int(size.get(a, 0))) for a in ('x', 'y', 'z'))
    pal = reg.get('BlockStatePalette', [])
    states = [(e.get('Name', '?'), e.get('Properties') or {}) for e in pal]
    vol = dims[0] * dims[1] * dims[2]
    ids = decode_packed(reg.get('BlockStates', []), vol, len(states))
    for idx, pid in enumerate(ids):
        x = idx % dims[0]; q = idx // dims[0]; z = q % dims[2]; y = q // dims[2]
        nm, props = states[pid]
        base = nm.replace('minecraft:', '')
        if base == 'air': continue
        pos_by_type[base].append((x, y, z))
        if 'facing' in props: facing_by_block[base][props['facing']] += 1
        if base == 'sand': sand_cols[(x, z)].append(y)

print("FILE:", os.path.basename(path))
print("dims (x,y,z):", dims)
print("\n== FACINGS (which way real cannon parts point) ==")
for b in ('dispenser', 'dropper', 'piston', 'sticky_piston', 'observer', 'repeater'):
    if facing_by_block.get(b):
        print(f"  {b:14}", dict(facing_by_block[b]))
colheights = sorted([len(v) for v in sand_cols.values()], reverse=True)
print(f"\n== SAND COMP: {len(sand_cols)} sand columns, tallest stacks: {colheights[:12]} ==")
print("\n== SPATIAL LAYOUT (bounding boxes per part) ==")
for t in ('dispenser', 'sand', 'tnt', 'redstone_wire', 'repeater', 'observer',
          'sticky_piston', 'piston', 'slime_block', 'soul_sand', 'note_block', 'water', 'obsidian', 'redstone_block'):
    ps = pos_by_type.get(t, [])
    if ps:
        xs = [p[0] for p in ps]; ys = [p[1] for p in ps]; zs = [p[2] for p in ps]
        print(f"  {t:14} n={len(ps):5}  x[{min(xs):>2}-{max(xs):>2}] y[{min(ys):>2}-{max(ys):>2}] z[{min(zs):>2}-{max(zs):>2}]")
