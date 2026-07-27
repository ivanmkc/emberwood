#!/usr/bin/env python3
"""Generate src/rooms/index.js from built room assets + the world graph.

For each built room: tile rows from the collision mask, spawn, and exits
with resolved targets and arrival tiles (center of the paired edge strip in
the target room, nudged inward).
"""
import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
OPP = {'n': 's', 's': 'n', 'w': 'e', 'e': 'w'}


def load_room(name):
    ij = os.path.join(ROOT, 'assets', 'rooms', f'{name}.instances.json')
    cp = os.path.join(ROOT, 'assets', 'rooms', f'{name}.collision.png')
    if not (os.path.exists(ij) and os.path.exists(cp)):
        return None
    d = json.load(open(ij))
    col = np.asarray(Image.open(cp).convert('L').resize((640, 448), Image.NEAREST)) > 127
    rows = []
    ret_col = col
    for ty in range(28):
        row = ''
        for tx in range(40):
            row += '.' if col[ty * 16:(ty + 1) * 16, tx * 16:(tx + 1) * 16].mean() > 0.4 else '#'
        rows.append(row)
    return {'data': d, 'rows': rows, 'col': ret_col}


def arrival_tile(target_room, edge_in_target):
    """Arrival point: center of the target's strip on edge_in_target, nudged inward."""
    for e in target_room['data'].get('exits', []):
        if e['edge'] == edge_in_target:
            x0, y0, x1, y1 = e['rect']
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            nudge = 28
            if edge_in_target == 'n':
                cy = y1 + nudge
            elif edge_in_target == 's':
                cy = y0 - nudge
            elif edge_in_target == 'w':
                cx = x1 + nudge
            else:
                cx = x0 - nudge
            return max(1, min(38, round(cx / 16))), max(1, min(26, round(cy / 16)))
    sp = target_room['data']['spawn']
    return round(sp[0] / 16), round(sp[1] / 16)


def main():
    cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    graph = dict(cfg['rooms'])
    graph['anchorroom'] = cfg['anchors']['anchorroom']
    for k, v in cfg.get('interiors', {}).items():
        graph[k] = {'exits': {'s': v['parent']}}
    doors_f = os.path.join(AP, 'doors.json')
    doors = json.load(open(doors_f)) if os.path.exists(doors_f) else {}
    built = {}
    for name in graph:
        r = load_room(name)
        if r:
            built[name] = r
    out = {}
    for name, r in built.items():
        exits = []
        for e in r['data'].get('exits', []):
            to = graph[name]['exits'].get(e['edge'])
            if not to or (to != 'overworld' and to not in built):
                continue
            if to == 'overworld':
                tx, ty = 38, 26
                to_rect = None
            else:
                tx, ty = arrival_tile(built[to], OPP[e['edge']])
                to_rect = None
                for te in built[to]['data'].get('exits', []):
                    if te['edge'] == OPP[e['edge']]:
                        to_rect = te['rect']
            # interior return exits arrive at the parent's DOOR, not an edge
            pdoor = next((dd for dd in doors.get(to, []) if dd['to'] == name), None)
            if e['edge'] == 's' and pdoor:
                to_rect = pdoor['rect']
                tx = max(1, min(38, round((pdoor['rect'][0] + pdoor['rect'][2]) / 2 / 16)))
                ty = max(1, min(26, round((pdoor['rect'][3] + 14) / 16)))
            # adaptive trigger depth: the belt starts exactly where the
            # walkable approach ends (fixed-depth belts swallowed gameplay
            # area, e.g. the anchor's west bank)
            rx0, ry0, rx1, ry1 = e['rect']
            colm = r['col']

            def standable(px, py):
                return 8 <= py <= 446 and 4 <= px <= 635 and                     colm[py - 8:py + 1, px - 4:px + 5].all()
            if e['edge'] in ('n', 's'):
                feet = []
                for px in range(max(4, rx0), min(636, rx1), 4):
                    rng = range(8, 120) if e['edge'] == 'n' else range(446, 320, -1)
                    for py in rng:
                        if standable(px, py):
                            feet.append(py)
                            break
                if feet:
                    if e['edge'] == 'n':
                        ry1 = max(ry1, min(feet) + 8)
                    else:
                        ry0 = min(ry0, max(feet) - 8)
            else:
                feet = []
                for py in range(max(8, ry0), min(447, ry1), 4):
                    rng = range(4, 120) if e['edge'] == 'w' else range(635, 520, -1)
                    for px in rng:
                        if standable(px, py):
                            feet.append(px)
                            break
                if feet:
                    if e['edge'] == 'w':
                        rx1 = max(rx1, min(feet) + 12)
                    else:
                        rx0 = min(rx0, max(feet) + 4)
            exits.append({'edge': e['edge'], 'rect': [rx0, ry0, rx1, ry1], 'to': to,
                          'tx': tx, 'ty': ty, 'toRect': to_rect})
        for dd in doors.get(name, []):
            if dd['to'] not in built:
                continue
            dx0, dy0, dx1, dy1 = dd['rect']
            # trigger must reach where the player can actually stand: scan
            # down from the door base to the first walkable row
            colm = r['col']
            # box-standable scan across the whole door width: the trigger
            # must reach a spot where an 8x8 hitbox can actually stand
            best = None
            for cxd in range(max(4, dx0 + 4), min(636, dx1 - 3), 4):
                for yy in range(max(8, dy1 - 8), min(447, dy1 + 90)):
                    if colm[yy - 8:yy + 1, cxd - 4:cxd + 5].all():
                        if best is None or yy < best:
                            best = yy
                        break
            yb = best if best is not None else dy1
            trig = [dx0, dy1 - 6, dx1, min(447, yb + 12)]
            itx, ity = arrival_tile(built[dd['to']], 's')
            srect = None
            for te in built[dd['to']]['data'].get('exits', []):
                if te['edge'] == 's':
                    srect = te['rect']
            exits.append({'edge': 'door', 'rect': trig, 'to': dd['to'],
                          'tx': itx, 'ty': ity, 'toRect': srect})
        out[name] = {'id': name, 'plate': f'rooms/{name}.jpg', 'rows': r['rows'],
                     'spawn': [round(v) for v in r['data']['spawn']], 'exits': exits}
    js = ('// GENERATED by tools/art-pipeline/gen_rooms_index.py - do not hand-edit.\n'
          '// Plate-room registry: tile rows from collision, spawns, edge exits.\n'
          'export const PLATE_ROOMS = ' + json.dumps(out, indent=1) + ';\n'
          'export const PLATE_ROOM_NAMES = ' + json.dumps(sorted(out)) + ';\n')
    open(os.path.join(ROOT, 'src', 'rooms', 'index.js'), 'w').write(js)
    print(f'src/rooms/index.js: {len(out)} rooms, '
          f'{sum(len(v["exits"]) for v in out.values())} wired exits')


if __name__ == '__main__':
    main()
