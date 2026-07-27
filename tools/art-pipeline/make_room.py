#!/usr/bin/env python3
"""Plate-room pipeline: turn a full NBP scene image into a playable room.

Steps:
  1. overlay a labeled tile grid on the plate
  2. Gemini vision votes (3x majority) on per-tile walkability
  3. force solid borders; flood-fill blocked components -> per-cell base row
     (for player-behind-object overdraw)
  4. emit src/rooms/<name>.js + assets/rooms/<name>.jpg + an overlay debug png
  5. deterministic gate: BFS spawn -> exit

Usage: python3 tools/art-pipeline/make_room.py
"""
import json
import os
import sys

from PIL import Image, ImageDraw
from google import genai
from google.genai import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATE = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
NAME = 'anchorroom'
COLS, ROWS = 40, 28
SPAWN = (20, 20)      # plaza floor, center
EXIT_TILE = (11, 27)  # bottom-left stair -> back to overworld

client = genai.Client(vertexai=True, project='adk-coding-agents', location='global')


def grid_overlay(img):
    im = img.convert('RGB').resize((1000, 700), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    cw, chh = 1000 / COLS, 700 / ROWS
    for c in range(COLS + 1):
        d.line([(c * cw, 0), (c * cw, 700)], fill=(255, 0, 255), width=1)
    for r in range(ROWS + 1):
        d.line([(0, r * chh), (1000, r * chh)], fill=(255, 0, 255), width=1)
    for r in range(0, ROWS, 4):
        d.text((4, r * chh + 2), str(r), fill=(255, 255, 0))
    for c in range(0, COLS, 5):
        d.text((c * cw + 2, 2), str(c), fill=(255, 255, 0))
    return im


def vote_mask(im):
    prompt = (
        f'This is a top-down 3/4 game scene divided into a {COLS}x{ROWS} tile grid '
        '(magenta lines; yellow row/column indices). Classify EVERY tile:\n'
        "'#' = blocked for walking (buildings, walls, the central pylon, glass tanks, "
        'market stalls, crates, machines, pipes on the ground, the canal water, railings, '
        'characters, any prop)\n'
        "'.' = open walkable floor (plaza plating, bare ground, the footbridge deck)\n"
        f'Return JSON only: {{"rows": ["40 chars", ... {ROWS} strings]}} — exactly '
        f'{ROWS} strings of exactly {COLS} characters each, top row first.'
    )
    votes = []
    for _ in range(3):
        resp = client.models.generate_content(
            model='gemini-3.1-pro-preview',
            contents=[im, prompt],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level='low'),
                max_output_tokens=8192,
            ),
        )
        text = resp.text or ''
        start = text.find('{')
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            rows = obj['rows']
            if len(rows) == ROWS and all(len(r) == COLS for r in rows):
                votes.append(rows)
            else:
                print(f'  vote rejected: {len(rows)} rows', file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f'  vote parse fail: {e}', file=sys.stderr)
    if len(votes) < 2:
        sys.exit('not enough valid votes')
    merged = []
    for r in range(ROWS):
        row = ''
        for c in range(COLS):
            blocked = sum(1 for v in votes if v[r][c] == '#')
            row += '#' if blocked * 2 > len(votes) else '.'
        merged.append(row)
    return merged


def main():
    plate = Image.open(PLATE)
    cache = os.path.join(ROOT, 'tools', 'art-pipeline', f'_room_{NAME}_votes.json')
    if os.path.exists(cache):
        rows = json.load(open(cache))
        print('using cached vote mask')
    else:
        im = grid_overlay(plate)
        print('voting on walkability (3 samples)...')
        rows = vote_mask(im)
        json.dump(rows, open(cache, 'w'))

    # force solid borders except the exit tile
    grid = [list(r) for r in rows]
    for c in range(COLS):
        grid[0][c] = '#'
        if c != EXIT_TILE[0]:
            grid[ROWS - 1][c] = '#'
    for r in range(ROWS):
        grid[r][0] = '#'
        grid[r][COLS - 1] = '#'
    grid[EXIT_TILE[1]][EXIT_TILE[0]] = '.'
    grid[SPAWN[1]][SPAWN[0]] = '.'

    # BFS gate: spawn -> exit
    seen = {SPAWN}
    q = [SPAWN]
    while q:
        x, y = q.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < COLS and 0 <= ny < ROWS and grid[ny][nx] == '.' and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    if EXIT_TILE not in seen:
        # carve the shortest L-corridor from the reachable region to the exit
        # (ensure-walkable-openings pattern) — visible in the debug overlay
        nearest = min(seen, key=lambda t: abs(t[0] - EXIT_TILE[0]) + abs(t[1] - EXIT_TILE[1]))
        x, y = nearest
        while x != EXIT_TILE[0]:
            x += 1 if EXIT_TILE[0] > x else -1
            grid[y][x] = '.'
        while y != EXIT_TILE[1]:
            y += 1 if EXIT_TILE[1] > y else -1
            grid[y][x] = '.'
        print(f'carved corridor from {nearest} to exit')
        seen = {SPAWN}
        q = [SPAWN]
        while q:
            cx0, cy0 = q.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx0 + dx, cy0 + dy
                if 0 <= nx < COLS and 0 <= ny < ROWS and grid[ny][nx] == '.' and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    q.append((nx, ny))
    assert EXIT_TILE in seen, 'exit still unreachable after carve'
    print(f'BFS ok: {len(seen)} walkable tiles reachable from spawn')

    # blocked components -> per-cell base row (lowest row of its component).
    # Use the PRE-border vote mask for grouping: the forced border ring would
    # otherwise weld every occluder into one giant component with base=27.
    raw = [list(r) for r in rows]
    comp = [[-1] * COLS for _ in range(ROWS)]
    bases = []
    cid = 0
    for r in range(ROWS):
        for c in range(COLS):
            if raw[r][c] == '#' and grid[r][c] == '#' and comp[r][c] < 0:
                stack = [(c, r)]
                comp[r][c] = cid
                cells = []
                while stack:
                    x, y = stack.pop()
                    cells.append((x, y))
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if (0 <= nx < COLS and 0 <= ny < ROWS and raw[ny][nx] == '#'
                                and grid[ny][nx] == '#' and comp[ny][nx] < 0):
                            comp[ny][nx] = cid
                            stack.append((nx, ny))
                base = max(y for _, y in cells)
                bases.append(base)
                cid += 1
    base_rows = [[(bases[comp[r][c]] if grid[r][c] == '#' else -1) for c in range(COLS)] for r in range(ROWS)]

    # emit room module + plate + debug overlay
    os.makedirs(os.path.join(ROOT, 'assets', 'rooms'), exist_ok=True)
    plate.convert('RGB').resize((COLS * 32, ROWS * 32), Image.LANCZOS).save(
        os.path.join(ROOT, 'assets', 'rooms', f'{NAME}.jpg'), quality=90)
    os.makedirs(os.path.join(ROOT, 'src', 'rooms'), exist_ok=True)
    with open(os.path.join(ROOT, 'src', 'rooms', f'{NAME}.js'), 'w') as f:
        f.write('// GENERATED by tools/art-pipeline/make_room.py — do not hand-edit.\n')
        f.write('// Plate room: walkability mask + per-cell occluder base rows,\n')
        f.write('// derived from the approved style-anchor scene by vision votes.\n')
        f.write(f'export const ROOM_{NAME.upper()} = {{\n')
        f.write(f"  id: '{NAME}',\n  plate: 'rooms/{NAME}.jpg',\n")
        f.write(f'  rows: {json.dumps(["".join(r) for r in grid])},\n')
        f.write(f'  baseRows: {json.dumps(base_rows)},\n')
        f.write(f'  spawn: {list(SPAWN)},\n  exit: {list(EXIT_TILE)},\n}};\n')

    dbg = plate.convert('RGB').resize((COLS * 32, ROWS * 32), Image.LANCZOS)
    dd = ImageDraw.Draw(dbg, 'RGBA')
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == '#':
                dd.rectangle([c * 32, r * 32, c * 32 + 31, r * 32 + 31], fill=(255, 40, 40, 70))
    dd.rectangle([SPAWN[0] * 32, SPAWN[1] * 32, SPAWN[0] * 32 + 31, SPAWN[1] * 32 + 31], outline=(0, 255, 0), width=3)
    dbg.save(os.path.join(ROOT, 'docs', 'art-options', f'{NAME}-mask-debug.png'))
    print('room emitted:', NAME, f'({cid} occluder components)')


if __name__ == '__main__':
    main()
