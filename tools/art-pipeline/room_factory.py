#!/usr/bin/env python3
"""Room factory: scene -> class mask -> walk mask -> footprint mask -> room.

Runs the full NBP mask pipeline per district (each pass judge/gate-checked,
internally best-of-N). Failed passes are retried; persistent failures are
reported in the ledger for reflective prompt revision, not silently patched.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')
LEDGER = os.path.join(AP, 'factory-ledger.json')
DEV_W, DEV_H = 1280, 896


def run(script, room, extra=()):
    r = subprocess.run([sys.executable, os.path.join(AP, script), '--room', room, *extra],
                       capture_output=True, text=True, timeout=1200)
    tail = (r.stdout + r.stderr).strip().splitlines()[-4:]
    return r.returncode == 0, tail


def build_room(room):
    art = os.path.join(ROOT, 'docs', 'art-options', 'rooms', room)
    rec = {'room': room, 'stages': {}}
    scene_met = os.path.join(art, 'scene-metrics.json')
    if not (os.path.exists(scene_met) and json.load(open(scene_met)).get('pass')):
        rec['stages']['scene'] = 'MISSING/UNGATED'
        return rec
    rec['stages']['scene'] = json.load(open(scene_met))

    for script, key, metf in (('nbp_mask.py', 'class', 'nbp-mask-metrics.json'),
                              ('nbp_walk.py', 'walk', 'nbp-walk-metrics.json'),
                              ('nbp_footprint.py', 'footprint', 'nbp-footprint-metrics.json')):
        mp = os.path.join(art, metf)
        if os.path.exists(mp) and json.load(open(mp)).get('pass'):
            rec['stages'][key] = json.load(open(mp))
            continue
        ok, tail = run(script, room)
        if not ok:  # one retry: NBP rolls are stochastic
            ok, tail = run(script, room)
        rec['stages'][key] = json.load(open(mp)) if os.path.exists(mp) else {'pass': False}
        if not rec['stages'][key].get('pass'):
            rec['stages'][key]['log'] = tail
            print(f'[{room}] {key} FAILED gates: {tail}')
            if key != 'footprint':
                return rec
            # footprint is optional: segment_room falls back to the
            # walk-authority heuristic when the mask is ungated
            print(f'[{room}] continuing without gated footprint (fallback compose)')
            continue
        print(f'[{room}] {key} ok')

    ok, tail = run('segment_room.py', room)
    rec['stages']['segment'] = {'pass': ok, 'log': tail}
    if not ok:
        print(f'[{room}] segment FAILED: {tail}')
        return rec
    print(f'[{room}] segment ok: {tail[-2:]}')

    # install the plate at device res + render a review overlay
    plate = Image.open(os.path.join(art, 'plate.png')).convert('RGB')
    plate.resize((DEV_W, DEV_H), Image.LANCZOS).save(
        os.path.join(ROOT, 'assets', 'rooms', f'{room}.jpg'), quality=88)
    import cv2
    W, H = plate.size
    col = np.asarray(Image.open(os.path.join(ROOT, 'assets', 'rooms', f'{room}.collision.png'))
                     .convert('L').resize((W, H), Image.NEAREST)) > 127
    inst = json.load(open(os.path.join(ROOT, 'assets', 'rooms', f'{room}.instances.json')))
    spx, spy = inst['spawn']
    n, lab = cv2.connectedComponents(col.astype(np.uint8))
    sid = lab[min(H - 1, int(spy / 448 * H)), min(W - 1, int(spx / 640 * W))]
    reach = lab == sid
    blend = np.asarray(plate).astype(np.float32).copy()
    blend[~col] = blend[~col] * 0.5 + np.array([255, 40, 40], np.float32) * 0.5
    blend[reach] = blend[reach] * 0.72 + np.array([40, 255, 90], np.float32) * 0.28
    isl = col & ~reach
    blend[isl] = blend[isl] * 0.45 + np.array([255, 230, 40], np.float32) * 0.55
    blue = np.zeros((H, W), dtype=bool)
    ohp = os.path.join(art, 'overhead.png')
    if os.path.exists(ohp):
        blue |= np.asarray(Image.open(ohp).convert('L').resize((W, H), Image.NEAREST)) > 127
    fpp = os.path.join(art, 'nbp-footprint.png')
    smp = os.path.join(AP, f'_srcmasks_{room}.npz')
    if os.path.exists(fpp) and os.path.exists(smp):
        fp = np.asarray(Image.open(fpp).convert('L').resize((W, H), Image.NEAREST)) > 127
        inst_arr = np.load(smp)['inst']
        if inst_arr.shape == (H, W):
            blocking_ids = {i['id'] for i in inst.get('instances', []) if i.get('blocking')}
            body_mask = np.isin(inst_arr, list(blocking_ids))
            blue |= body_mask & ~fp & col
    blend[blue] = blend[blue] * 0.45 + np.array([76, 140, 255], np.float32) * 0.55
    ov = Image.fromarray(blend.clip(0, 255).astype(np.uint8))
    ov.thumbnail((1400, 1400), Image.LANCZOS)
    ov.save(os.path.join(art, 'collision-preview.jpg'), quality=86)
    rec['stages']['install'] = {'pass': True, 'island_px': int(isl.sum()),
                                'walk_frac': round(float(col.mean()), 3),
                                'exits': inst.get('exits', [])}
    print(f'[{room}] installed (islands {int(isl.sum())}, walk {col.mean():.2f}, '
          f'exits {[e["edge"] for e in inst.get("exits", [])]})')
    return rec


def main():
    _cfg = json.load(open(os.path.join(AP, 'rooms.json')))
    rooms = sys.argv[1:] or (list(_cfg['rooms']) + list(_cfg.get('interiors', {})))
    with ThreadPoolExecutor(max_workers=3) as ex:
        recs = list(ex.map(build_room, rooms))
    ledger = {r['room']: r for r in recs}
    json.dump(ledger, open(LEDGER, 'w'), indent=1)
    done = [r['room'] for r in recs if r['stages'].get('install', {}).get('pass')]
    print(f'\nfactory: {len(done)}/{len(rooms)} rooms fully built: {done}')
    print('ledger:', LEDGER)


if __name__ == '__main__':
    main()
