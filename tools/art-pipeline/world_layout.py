#!/usr/bin/env python3
"""Solve a planar (gx, gy) grid layout for exterior rooms from rooms.json exits.

Exit edges define grid adjacency:
  n → target at (gx, gy-1)   s → target at (gx, gy+1)
  e → target at (gx+1, gy)   w → target at (gx-1, gy)

The current graph is NOT planar-consistent — the cycle
  anchorroom →e→ repair-bay →s→ hydroponics →w→ canal-docks →n→ residential
returns to (0,0) with zero net displacement, colliding residential with
anchorroom and rooftops with repair-bay.

Fix: rewire the residential cluster by changing canal-docks.n→residential
to night-bazaar.n→residential.  This places residential/rooftops/observatory
in row y=-1 (above the main corridor) and keeps canal-docks at (0,1) directly
south of anchorroom.  All locks and connectivity are preserved.

Emits:
  - rooms.json "layout" section: {room: [gx, gy]} for exteriors
  - Updated rooms.json exits if conflicts are found and fixed
  - Regenerates src/rooms/index.js via gen_rooms_index
"""
import json
import os
import subprocess
import sys
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')

EDGE_DELTA = {'n': (0, -1), 's': (0, 1), 'e': (1, 0), 'w': (-1, 0)}
OPP = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}


def load_graph(cfg):
    """Build the exterior room graph from rooms.json."""
    graph = {}
    for name, room in cfg.get('rooms', {}).items():
        graph[name] = dict(room.get('exits', {}))
    for name, room in cfg.get('anchors', {}).items():
        graph[name] = dict(room.get('exits', {}))
    return graph


def try_embed(graph, origin='anchorroom'):
    """BFS embed the graph into a grid.  Returns (positions, conflicts)."""
    pos = {origin: (0, 0)}
    conflicts = []
    q = deque([origin])
    visited = {origin}
    while q:
        room = q.popleft()
        gx, gy = pos[room]
        for edge, target in graph[room].items():
            if edge not in EDGE_DELTA or target not in graph:
                continue
            dx, dy = EDGE_DELTA[edge]
            want = (gx + dx, gy + dy)
            if target in pos:
                if pos[target] != want:
                    conflicts.append((room, edge, target, want, pos[target]))
            else:
                occupied_by = {v: k for k, v in pos.items()}
                if want in occupied_by:
                    conflicts.append((room, edge, target, want,
                                      f'occupied by {occupied_by[want]}'))
                    pos[target] = want
                else:
                    pos[target] = want
            if target not in visited:
                visited.add(target)
                q.append(target)
    return pos, conflicts


def apply_fixes(cfg):
    """Apply the minimal rewiring to make the graph planar.

    The zero-displacement cycle is:
      anchorroom →e→ repair-bay →s→ hydroponics →w→ canal-docks →n→ residential

    Fix: disconnect canal-docks.n→residential and reconnect via
    night-bazaar.n→residential (residential.s→night-bazaar).
    """
    rooms = cfg['rooms']
    anchors = cfg['anchors']

    changes = []

    # 1. Remove canal-docks.n → residential
    cd = rooms.get('canal-docks', {}).get('exits', {})
    if cd.get('n') == 'residential':
        del cd['n']
        changes.append('canal-docks: removed exit n→residential')

    # 2. Add night-bazaar.n → residential
    nb = rooms.get('night-bazaar', {}).get('exits', {})
    if 'n' not in nb:
        nb['n'] = 'residential'
        changes.append('night-bazaar: added exit n→residential')

    # 3. Change residential.s from canal-docks to night-bazaar
    res = rooms.get('residential', {}).get('exits', {})
    if res.get('s') == 'canal-docks':
        res['s'] = 'night-bazaar'
        changes.append('residential: changed exit s→canal-docks to s→night-bazaar')

    return changes


def verify_connectivity(cfg, graph):
    """BFS from anchorroom; assert all rooms reachable and lock invariant holds."""
    all_rooms = set(graph.keys())
    adj = {}
    for name in graph:
        adj[name] = []
        for edge, target in graph[name].items():
            if target in graph:
                adj[name].append(target)
    # interiors connect to parents and vice versa
    for name, room in cfg.get('interiors', {}).items():
        parent = room.get('parent')
        if parent and parent in adj:
            adj.setdefault(name, []).append(parent)
            adj[parent].append(name)
        else:
            adj.setdefault(name, [])

    seen = {'anchorroom'}
    q = deque(['anchorroom'])
    while q:
        cur = q.popleft()
        for nb in adj.get(cur, []):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)

    missing = all_rooms - seen
    if missing:
        print(f'WARNING: {len(missing)} rooms unreachable: {missing}')
    else:
        print(f'connectivity: all {len(seen)} exterior rooms reachable from anchorroom')

    # lock invariant: grant rooms reachable without their flag
    locks = cfg.get('locks', [])
    locked_edges = {(lk['room'], lk['edge']) for lk in locks}
    open_adj = {}
    for name in graph:
        open_adj[name] = []
        for edge, target in graph[name].items():
            if target in graph and (name, edge) not in locked_edges:
                open_adj[name].append(target)
    for name, room in cfg.get('interiors', {}).items():
        parent = room.get('parent')
        if parent and parent in open_adj:
            open_adj.setdefault(name, []).append(parent)
            open_adj[parent].append(name)

    open_seen = {'anchorroom'}
    q2 = deque(['anchorroom'])
    while q2:
        cur = q2.popleft()
        for nb in open_adj.get(cur, []):
            if nb not in open_seen:
                open_seen.add(nb)
                q2.append(nb)

    for lk in locks:
        grant = lk['grant_room']
        if grant not in open_seen:
            print(f'LOCK INVARIANT VIOLATED: {lk["flag"]} grant room '
                  f'{grant} unreachable without its flag!')
            sys.exit(1)
    print(f'lock invariant: all {len(locks)} grant rooms reachable '
          f'without their flags ({len(open_seen)} rooms in open world)')


def main():
    cfg_path = os.path.join(AP, 'rooms.json')
    cfg = json.load(open(cfg_path))

    # Step 1: try embedding the original graph
    graph = load_graph(cfg)
    pos, conflicts = try_embed(graph)
    if conflicts:
        print(f'original graph has {len(conflicts)} conflict(s):')
        for c in conflicts:
            print(f'  {c[0]}.{c[1]}→{c[2]}: wants {c[3]}, but {c[4]}')
        print()

        # Step 2: apply fixes
        changes = apply_fixes(cfg)
        for ch in changes:
            print(f'FIX: {ch}')

        # Step 3: re-embed
        graph = load_graph(cfg)
        pos, conflicts = try_embed(graph)
        if conflicts:
            print(f'\nSTILL {len(conflicts)} conflict(s) after fixes:')
            for c in conflicts:
                print(f'  {c[0]}.{c[1]}→{c[2]}: wants {c[3]}, but {c[4]}')
            sys.exit(1)
        print('\nfixes resolved all conflicts')
    else:
        print('graph is already planar-consistent')

    # Step 4: verify connectivity + lock invariant
    verify_connectivity(cfg, graph)

    # Step 5: emit layout section
    layout = {}
    for room, (gx, gy) in sorted(pos.items()):
        layout[room] = [gx, gy]
    cfg['layout'] = layout

    print(f'\nlayout ({len(layout)} exterior rooms):')
    # print as grid
    min_x = min(gx for gx, gy in pos.values())
    max_x = max(gx for gx, gy in pos.values())
    min_y = min(gy for gx, gy in pos.values())
    max_y = max(gy for gx, gy in pos.values())
    rev = {v: k for k, v in pos.items()}
    for gy in range(min_y, max_y + 1):
        row = []
        for gx in range(min_x, max_x + 1):
            name = rev.get((gx, gy), '')
            row.append(f'{name:>18s}')
        print(f'  y={gy:+d}: {"".join(row)}')

    # Step 6: write updated rooms.json
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f'\nwrote {cfg_path}')

    # Step 7: re-run gen_rooms_index.py
    print('\nrunning gen_rooms_index.py...')
    result = subprocess.run(
        [sys.executable, os.path.join(AP, 'gen_rooms_index.py')],
        capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f'gen_rooms_index FAILED:\n{result.stderr}')
        sys.exit(1)


if __name__ == '__main__':
    main()
