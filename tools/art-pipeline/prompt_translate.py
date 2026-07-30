#!/usr/bin/env python3
"""Translate geometric coverage paths into natural-language Veo prompts.

The coverage planner outputs pixel-coordinate paths. Veo needs natural
language descriptions of where walkers should go. This module bridges
that gap by mapping pixel regions to spatial language (left/right/top/
bottom/center, near specific objects).

Two modes:
  1. Waypoint mode: the plate has painted waypoints — prompt references them
  2. Natural language mode: describe the path using relative positions

Usage:
  python prompt_translate.py <paths.json> <plate_width> <plate_height>
"""
import math

BASE_PROMPT = (
    'Completely static locked-off camera: no camera movement, no zoom, '
    'no pan, no cuts. The pixel-art scene stays EXACTLY as shown in the '
    'reference image — same layout, same lighting, nothing redecorated. '
)

MAGENTA_COSTUME = 'wearing a bright magenta/hot-pink full-body suit'
WALK_SUFFIX = 'Crisp pixel-art animation, character scaled to the scene.'


def _horizontal_zone(x, width):
    frac = x / width
    if frac < 0.2:
        return 'far left'
    elif frac < 0.4:
        return 'left'
    elif frac < 0.6:
        return 'center'
    elif frac < 0.8:
        return 'right'
    else:
        return 'far right'


def _vertical_zone(y, height):
    frac = y / height
    if frac < 0.25:
        return 'far back'
    elif frac < 0.45:
        return 'back'
    elif frac < 0.65:
        return 'middle'
    elif frac < 0.85:
        return 'front'
    else:
        return 'foreground'


def _direction(x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    if abs(dx) < 20 and abs(dy) < 20:
        return 'stands still'
    angle = math.degrees(math.atan2(-dy, dx))
    if -22 < angle <= 22:
        return 'left to right'
    elif 22 < angle <= 67:
        return 'from front-left toward back-right'
    elif 67 < angle <= 112:
        return 'from front toward back'
    elif 112 < angle <= 157:
        return 'from front-right toward back-left'
    elif abs(angle) > 157:
        return 'right to left'
    elif -157 < angle <= -112:
        return 'from back-right toward front-left'
    elif -112 < angle <= -67:
        return 'from back toward front'
    else:
        return 'from back-left toward front-right'


def _depth_desc(y, height):
    frac = y / height
    if frac < 0.3:
        return 'far in the back of the scene'
    elif frac < 0.55:
        return 'in the middle depth'
    else:
        return 'close to the camera in the foreground'


def translate_path_natural(path, width, height):
    """Translate one merged coverage path to a natural language walk description."""
    if len(path) < 2:
        return None

    start = path[0]
    end = path[-1]
    h_start = _horizontal_zone(start[0], width)
    h_end = _horizontal_zone(end[0], width)
    v_zone = _vertical_zone((start[1] + end[1]) / 2, height)
    direction = _direction(start[0], start[1], end[0], end[1])
    depth = _depth_desc((start[1] + end[1]) / 2, height)

    span = abs(end[0] - start[0])
    if span > width * 0.6:
        coverage = 'across the full width of the scene'
    elif span > width * 0.3:
        coverage = 'across half the scene'
    else:
        coverage = 'a short distance'

    desc = (
        f'One villager {MAGENTA_COSTUME} walks {direction}, starting from '
        f'the {h_start} and ending at the {h_end}, {depth}. '
        f'The walker covers {coverage} at a steady pace.'
    )
    return desc


def translate_path_waypoint(path, markers, width, height):
    """Translate a path using painted waypoint markers as reference.

    markers: list of (number, x, y) from waypoint_paint.
    """
    if not markers:
        return translate_path_natural(path, width, height)

    relevant = []
    for n, mx, my in markers:
        for px, py in path:
            if abs(mx - px) < 60 and abs(my - py) < 60:
                relevant.append(n)
                break

    if len(relevant) < 2:
        return translate_path_natural(path, width, height)

    relevant.sort()
    if len(relevant) > 4:
        relevant = [relevant[0], relevant[len(relevant)//3],
                    relevant[2*len(relevant)//3], relevant[-1]]
    wp_text = ', '.join(f'waypoint {n}' for n in relevant)
    depth = _depth_desc((path[0][1] + path[-1][1]) / 2, height)
    direction = _direction(path[0][0], path[0][1], path[-1][0], path[-1][1])

    return (
        f'One villager {MAGENTA_COSTUME} walks {direction}, following the '
        f'numbered waypoints painted on the ground: {wp_text}. The walker '
        f'passes {depth}, stepping exactly through each numbered circle in order.'
    )


def generate_prompts(paths, width, height, markers=None, max_walkers_per_video=2):
    """Generate Veo prompts covering all paths.

    Groups nearby paths into multi-walker prompts where possible.
    Returns a list of complete prompt strings.
    """
    prompts = []
    used = set()

    for i, path in enumerate(paths):
        if i in used:
            continue
        used.add(i)

        if markers:
            desc = translate_path_waypoint(path, markers, width, height)
        else:
            desc = translate_path_natural(path, width, height)

        if desc is None:
            continue

        companions = []
        if max_walkers_per_video > 1:
            for j, other in enumerate(paths):
                if j in used or j == i:
                    continue
                y_i = (path[0][1] + path[-1][1]) / 2
                y_j = (other[0][1] + other[-1][1]) / 2
                if abs(y_i - y_j) > height * 0.3:
                    if markers:
                        comp = translate_path_waypoint(other, markers, width, height)
                    else:
                        comp = translate_path_natural(other, width, height)
                    if comp:
                        companions.append((j, comp))
                    if len(companions) >= max_walkers_per_video - 1:
                        break

        for j, _ in companions:
            used.add(j)

        if companions:
            all_descs = [desc] + [c[1] for c in companions]
            combined = ' Meanwhile, '.join(all_descs).rstrip('.')
            prompt = BASE_PROMPT + combined + '. ' + WALK_SUFFIX
        else:
            prompt = BASE_PROMPT + desc + ' ' + WALK_SUFFIX

        prompts.append(prompt)

    return prompts


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument('paths_json')
    parser.add_argument('width', type=int)
    parser.add_argument('height', type=int)
    parser.add_argument('--waypoint-mode', action='store_true')
    args = parser.parse_args()

    with open(args.paths_json) as f:
        paths = json.load(f)

    prompts = generate_prompts(paths, args.width, args.height)
    for i, p in enumerate(prompts):
        print(f'\n--- Prompt {i+1} ---')
        print(p)
