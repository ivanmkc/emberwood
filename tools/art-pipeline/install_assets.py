#!/usr/bin/env python3
"""Install GATED art into the game's assets/ directory.

Only items whose latest gate verdict is pass are copied — this is itself a
deterministic gate: integration cannot ship un-judged art. Writes
assets/manifest.json for the JS loader.
"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, 'docs', 'art-options')
VERDICTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'verdicts.json')
DEST = os.path.join(ROOT, 'assets')

TILE_NAMES = ['ground', 'plate', 'dust', 'coolant', 'walkway', 'rubble',
              'minefloor', 'minewall', 'floorpanel', 'wallpanel', 'carpet',
              'overgrowth', 'domefloor']
PROP_NAMES = ['tree', 'rock', 'chest', 'beacon', 'lamp', 'house',
              'terminal', 'rack', 'vat', 'bush', 'mast', 'crates', 'pipe',
              'stall', 'tree2']
CHAR_SHEET = ['player', 'chief', 'angler', 'settler', 'keeper']  # 4-directional
CHAR_SINGLE = ['trader', 'sludge', 'drone', 'boss', 'petdrone']


def main():
    verdicts = json.load(open(VERDICTS))
    missing, failed = [], []

    def check(kind, name):
        v = verdicts.get(f'{kind}:{name}')
        if v is None:
            missing.append(f'{kind}:{name}')
            return False
        if not v['pass']:
            failed.append(f'{kind}:{name}')
            return False
        return True

    manifest = {'tiles': {}, 'props': {}, 'chars': {}}
    os.makedirs(os.path.join(DEST, 'tiles'), exist_ok=True)
    os.makedirs(os.path.join(DEST, 'props'), exist_ok=True)
    os.makedirs(os.path.join(DEST, 'chars'), exist_ok=True)

    for name in TILE_NAMES:
        if not check('tile', name):
            continue
        variants = []
        for i in range(8):
            src = os.path.join(ART, 'tiles-scifi', f'{name}-{i}.png')
            if os.path.exists(src):
                shutil.copy(src, os.path.join(DEST, 'tiles', f'{name}-{i}.png'))
                variants.append(f'tiles/{name}-{i}.png')
        if variants:
            manifest['tiles'][name] = variants

    for name in PROP_NAMES:
        if not check('asset', name):
            continue
        src = os.path.join(ART, 'assets-scifi', f'{name}.png')
        shutil.copy(src, os.path.join(DEST, 'props', f'{name}.png'))
        manifest['props'][name] = f'props/{name}.png'

    for name in CHAR_SHEET:
        if not check('char', name):
            continue
        dirs = {}
        for d in ['down', 'up', 'left', 'right']:
            src = os.path.join(ART, 'chars-scifi', f'{name}-{d}.png')
            if os.path.exists(src):
                shutil.copy(src, os.path.join(DEST, 'chars', f'{name}-{d}.png'))
                dirs[d] = f'chars/{name}-{d}.png'
        if len(dirs) == 4:
            manifest['chars'][name] = dirs

    for name in CHAR_SINGLE:
        if not check('char', name):
            continue
        src = os.path.join(ART, 'chars-scifi', f'{name}.png')
        shutil.copy(src, os.path.join(DEST, 'chars', f'{name}.png'))
        manifest['chars'][name] = f'chars/{name}.png'

    json.dump(manifest, open(os.path.join(DEST, 'manifest.json'), 'w'), indent=1)
    print('installed:', {k: len(v) for k, v in manifest.items()})
    if missing or failed:
        print('NOT installed — missing verdicts:', missing, 'failed gates:', failed)
        sys.exit(1)


if __name__ == '__main__':
    main()
