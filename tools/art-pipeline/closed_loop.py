#!/usr/bin/env python3
"""Closed-loop adaptive coverage for the feet-conditioned layer estimator.

The loop:
  1. Run estimator on current videos
  2. Score per-part confidence
  3. Identify under-evidenced non-UNREACHABLE parts
  4. Run coverage planner targeting those parts
  5. Generate waypointed plate + translated prompts
  6. Evaluate stopping criterion

Stopping criterion: stop when either:
  - All scoreable parts are well-evidenced or adequate
  - Expected marginal gain from next video < threshold
  - Max iterations reached
  - All remaining unvisited parts are UNREACHABLE

The stopping criterion measures marginal improvement: the per-iteration
delta in classified_pct. When two consecutive iterations improve by less
than MARGINAL_GAIN_FLOOR, the loop emits a "diminishing returns" signal.

Usage:
  # Dry run (plan only, no Veo generation):
  python closed_loop.py plan <room> [--max-rounds 5]

  # Full loop with Veo generation (needs authorization):
  python closed_loop.py run <room> [--max-rounds 5]

  # Score existing results:
  python closed_loop.py score <estimator.json> <parts.npz>
"""
import argparse
import glob
import io
import json
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image

import confidence_score as cs
import prompt_translate as pt
import waypoint_paint as wp

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_ROUNDS = 8
MARGINAL_GAIN_FLOOR = 2.0
STOP_CLASSIFIED_PCT = 90.0
VEO_MODEL = 'veo-3.1-generate-001'
VEO_TIMEOUT = 900


def load_room_data(room, root=ROOT):
    """Load parts mask, ground, collision, and plate for a room."""
    parts = np.load(os.path.join(
        root, f'tools/art-pipeline/_srcmasks_{room}-parts.npz'))['inst']

    ground_path = os.path.join(root, f'docs/art-options/magenta-ground-{room}-nowires.png')
    if not os.path.exists(ground_path):
        ground_path = os.path.join(root, f'docs/art-options/magenta-ground-{room}.png')
    ground = np.asarray(Image.open(ground_path).convert('L')) > 127

    coll_path = os.path.join(root, f'assets/rooms/{room}.collision.png')
    coll = np.asarray(
        Image.open(coll_path).convert('L').resize(
            (parts.shape[1], parts.shape[0]), Image.Resampling.NEAREST)) > 127

    plate_path = os.path.join(root, f'docs/art-options/rooms/{room}/plate.png')
    plate = cv2.imread(plate_path)

    return parts, ground, coll, plate


def find_videos(room, root=ROOT):
    """Find existing stabilized walk videos for a room."""
    patterns = [
        os.path.join(root, f'docs/art-options/veo/{room}/*_stab.mp4'),
        os.path.join(root, f'docs/art-options/rooms-layers/{room}/*.mp4'),
    ]
    vids = []
    for pat in patterns:
        vids.extend(sorted(glob.glob(pat)))
    if not vids:
        base = os.path.join(root, f'docs/art-options/veo/')
        vids = sorted(glob.glob(os.path.join(base, f'{room}*.mp4')))
    return vids


def compute_base_y(parts):
    """Compute base_y for each part id (lowest row containing the part)."""
    pids = [int(p) for p in np.unique(parts) if p > 0]
    base_y = {}
    for pid in pids:
        m = parts == pid
        base_y[pid] = int(np.nonzero(m)[0].max())
    return base_y


def compute_collision_bands(parts, coll, ground):
    """Compute collision band rects for the coverage planner."""
    pids = [int(p) for p in np.unique(parts) if p > 0]
    bands = []
    for pid in pids:
        m = parts == pid
        nong = m & ~ground
        blocked = ~coll & nong
        if blocked.any():
            ys, xs = np.nonzero(blocked)
            bands.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
    return bands


def targeted_paths_from_report(report, target_pids):
    """Build walk paths from the planner report, targeting only specific pids.

    The planner report has per-pid, per-side positions: {pid: {side: {y, x0, x1}}}.
    We extract those for target pids and group them by y-level to produce
    a manageable set of merged walks (one walk per depth band, covering
    multiple parts if they share a similar y).
    """
    segments = []
    for pid_str, sides in report.items():
        pid = int(pid_str)
        if pid not in target_pids:
            continue
        for side, val in sides.items():
            if val == 'UNREACHABLE':
                continue
            segments.append({
                'pid': pid, 'side': side,
                'y': val['y'], 'x0': val['x0'], 'x1': val['x1'],
            })

    segments.sort(key=lambda s: s['y'])
    merged = []
    for seg in segments:
        if merged and abs(merged[-1]['y'] - seg['y']) <= 20:
            grp = merged[-1]
            grp['x0'] = min(grp['x0'], seg['x0'])
            grp['x1'] = max(grp['x1'], seg['x1'])
            grp['pids'].add(seg['pid'])
        else:
            merged.append({
                'y': seg['y'],
                'x0': seg['x0'], 'x1': seg['x1'],
                'pids': {seg['pid']},
            })

    return [[(g['x0'], g['y']), (g['x1'], g['y'])] for g in merged]


def plan_round(room, estimator_json, parts, ground, coll, plate,
               walker_w=30, walker_h=70, out_dir=None):
    """Plan one round of adaptive coverage.

    Returns:
      - paths: list of coverage paths for under-evidenced parts
      - prompts: translated Veo prompts
      - waypointed_plate: plate with painted waypoints
      - scores: per-part confidence scores
      - summary: room-level confidence summary
      - report: coverage planner report
    """
    from synth_scene_family import plan_coverage_paths

    scores = cs.score_room(estimator_json, parts, walker_w)
    summary = cs.summarize(scores)
    needs_work = cs.under_evidenced_pids(scores)

    if not needs_work:
        return None, [], None, scores, summary, {}

    base_y = compute_base_y(parts)
    bands = compute_collision_bands(parts, coll, ground)

    target_pids = set(int(p) for p in needs_work)
    merged, report = plan_coverage_paths(parts, base_y, walker_w, walker_h, bands)

    target_report = {}
    reachable_targets = set()
    for pid_str, sides in report.items():
        pid = int(pid_str)
        if pid in target_pids:
            target_report[pid_str] = sides
            for side_name, side_val in sides.items():
                if side_val != 'UNREACHABLE':
                    reachable_targets.add(pid)

    paths = targeted_paths_from_report(report, target_pids)
    if not paths:
        paths = [seg for seg in merged]

    h, w = plate.shape[:2]
    waypointed, markers = wp.paint_waypoints(plate, paths, spacing=120)
    prompts = pt.generate_prompts(paths, w, h, markers=markers)

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        cv2.imwrite(os.path.join(out_dir, 'waypointed_plate.png'), waypointed)
        with open(os.path.join(out_dir, 'paths.json'), 'w') as f:
            json.dump(paths, f, indent=1)
        with open(os.path.join(out_dir, 'prompts.json'), 'w') as f:
            json.dump(prompts, f, indent=1)
        with open(os.path.join(out_dir, 'confidence.json'), 'w') as f:
            json.dump({'scores': scores, 'summary': summary,
                       'under_evidenced': needs_work,
                       'reachable_targets': sorted(reachable_targets),
                       'coverage_report': {k: v for k, v in target_report.items()}},
                      f, indent=1)

    return paths, prompts, waypointed, scores, summary, report


def should_stop(history, max_rounds=MAX_ROUNDS):
    """Evaluate the stopping criterion.

    history: list of per-round summaries (from cs.summarize)

    Returns (stop: bool, reason: str)
    """
    if len(history) >= max_rounds:
        return True, f'max rounds ({max_rounds}) reached'

    latest = history[-1]
    if latest['unvisited'] == 0 and latest['under_evidenced'] == 0:
        return True, 'all parts classified'

    if latest['classified_pct'] >= STOP_CLASSIFIED_PCT:
        return True, f'classified_pct {latest["classified_pct"]}% >= {STOP_CLASSIFIED_PCT}%'

    if len(history) >= 2:
        prev = history[-2]
        gain = latest['classified_pct'] - prev['classified_pct']
        if gain < MARGINAL_GAIN_FLOOR:
            if len(history) >= 3:
                prev2 = history[-3]
                gain2 = prev['classified_pct'] - prev2['classified_pct']
                if gain2 < MARGINAL_GAIN_FLOOR:
                    return True, (f'diminishing returns: last two gains '
                                  f'{gain2:.1f}%, {gain:.1f}% < {MARGINAL_GAIN_FLOOR}%')

    return False, 'continue'


def generate_video(plate_bgr, prompt, out_path):
    """Generate one Veo video from a plate + prompt. Returns True on success."""
    from google import genai
    from google.genai import errors as genai_errors, types

    plate_pil = Image.fromarray(cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2RGB))
    plate_pil.thumbnail((1280, 1280))
    buf = io.BytesIO()
    plate_pil.save(buf, format='PNG')

    client = genai.Client(vertexai=True, project='adk-coding-agents',
                          location='us-central1')

    try:
        op = client.models.generate_videos(
            model=VEO_MODEL, prompt=prompt,
            image=types.Image(image_bytes=buf.getvalue(), mime_type='image/png'),
            config=types.GenerateVideosConfig(aspect_ratio='16:9',
                                              number_of_videos=1))
    except (genai_errors.APIError, ValueError) as e:
        print(f'Veo launch error: {e}')
        return False

    deadline = time.time() + VEO_TIMEOUT
    while time.time() < deadline:
        time.sleep(20)
        try:
            op = client.operations.get(op)
        except genai_errors.APIError as e:
            print(f'Veo poll error: {e}')
            continue
        if op.done:
            vids = getattr(op.response, 'generated_videos', None) or []
            if not vids:
                print(f'Veo done but empty: {op.error or op.response}')
                return False
            with open(out_path, 'wb') as f:
                f.write(vids[0].video.video_bytes)
            print(f'Saved {os.path.getsize(out_path) // 1024}KB to {out_path}')
            return True

    print('Veo timeout')
    return False


def run_estimator(parts, ground, coll, plate, videos, out_prefix,
                  view_wh=(1200, 675)):
    """Run the v4 estimator on videos."""
    import veo_layers_v4 as v4
    return v4.estimate(parts, ground, coll, plate, videos, out_prefix, view_wh)


def cmd_plan(args):
    """Plan one round of adaptive coverage without generating videos."""
    room = args.room
    parts, ground, coll, plate = load_room_data(room)
    vids = find_videos(room)

    out_prefix = os.path.join(ROOT, f'docs/art-options/rooms-layers/{room}')
    estimator_json = out_prefix + '.json'

    if not os.path.exists(estimator_json):
        if not vids:
            print(f'No existing videos or estimator output for {room}')
            return
        print(f'Running estimator on {len(vids)} existing videos...')
        run_estimator(parts, ground, coll, plate, vids, out_prefix)

    out_dir = os.path.join(ROOT, f'docs/art-options/rooms-layers/{room}-adaptive')
    paths, prompts, waypointed, scores, summary, report = plan_round(
        room, estimator_json, parts, ground, coll, plate, out_dir=out_dir)

    print(f'\nRoom: {room}')
    print(f'Summary: {json.dumps(summary, indent=2)}')
    print(f'\n{len(prompts)} prompts generated:')
    for i, p in enumerate(prompts):
        print(f'\n--- Prompt {i+1} ---')
        print(p[:200] + '...' if len(p) > 200 else p)

    if waypointed is not None:
        wp_path = os.path.join(out_dir, 'waypointed_plate.png')
        print(f'\nWaypointed plate saved to: {wp_path}')

    stop, reason = should_stop([summary])
    print(f'\nStopping criterion (round 1): stop={stop}, reason={reason}')


def cmd_run(args):
    """Run the full closed loop with Veo generation."""
    room = args.room
    max_rounds = args.max_rounds
    parts, ground, coll, plate = load_room_data(room)
    vids = find_videos(room)

    out_base = os.path.join(ROOT, f'docs/art-options/rooms-layers')
    out_prefix = os.path.join(out_base, room)
    history = []

    for round_n in range(1, max_rounds + 1):
        print(f'\n{"="*60}')
        print(f'ROUND {round_n}/{max_rounds}')
        print(f'{"="*60}')

        estimator_json = out_prefix + '.json'
        if vids:
            print(f'Running estimator on {len(vids)} videos...')
            run_estimator(parts, ground, coll, plate, vids, out_prefix)
        elif not os.path.exists(estimator_json):
            print('No videos yet — generating initial untargeted walks...')
            initial_prompt = (
                pt.BASE_PROMPT +
                'Two villagers walk slowly through the scene on different paths, '
                'exploring the entire space. One walks from the left edge to the '
                'right, the other walks from the foreground toward the back. '
                + pt.WALK_SUFFIX
            )
            vid_path = os.path.join(out_base, f'{room}', f'adaptive_r{round_n}.mp4')
            os.makedirs(os.path.dirname(vid_path), exist_ok=True)
            ok = generate_video(plate, initial_prompt, vid_path)
            if ok:
                vids.append(vid_path)
                run_estimator(parts, ground, coll, plate, vids, out_prefix)
            else:
                print('Initial video generation failed, stopping.')
                break

        round_dir = os.path.join(out_base, f'{room}-adaptive', f'round{round_n}')
        paths, prompts, waypointed, scores, summary, report = plan_round(
            room, estimator_json, parts, ground, coll, plate,
            out_dir=round_dir)

        history.append(summary)
        print(f'Round {round_n} summary: {json.dumps(summary, indent=2)}')

        stop, reason = should_stop(history, max_rounds)
        if stop:
            print(f'\nSTOPPING: {reason}')
            break

        if not prompts:
            print('No prompts generated (all parts classified or unreachable)')
            break

        print(f'\nGenerating {len(prompts)} targeted videos...')
        use_waypoints = waypointed is not None
        plate_for_veo = waypointed if use_waypoints else plate

        new_vids = []
        for i, prompt in enumerate(prompts[:3]):
            vid_path = os.path.join(out_base, f'{room}',
                                    f'adaptive_r{round_n}_p{i}.mp4')
            os.makedirs(os.path.dirname(vid_path), exist_ok=True)
            ok = generate_video(plate_for_veo, prompt, vid_path)
            if ok:
                new_vids.append(vid_path)

        if not new_vids:
            print('All video generations failed this round.')
            break

        vids.extend(new_vids)
        print(f'Generated {len(new_vids)} new videos, total now {len(vids)}')

    print(f'\n{"="*60}')
    print('CLOSED LOOP COMPLETE')
    print(f'{"="*60}')
    print(f'Rounds: {len(history)}')
    for i, h in enumerate(history):
        print(f'  Round {i+1}: classified {h["classified_pct"]}%, '
              f'unvisited {h["unvisited"]}, under-evidenced {h["under_evidenced"]}')

    with open(os.path.join(out_base, f'{room}-adaptive', 'loop_history.json'), 'w') as f:
        json.dump(history, f, indent=2)


def cmd_score(args):
    """Score existing estimator output."""
    scores = cs.score_room(args.estimator_json, args.parts_npz,
                           walker_w_plate=args.walker_width)
    summary = cs.summarize(scores)
    print(json.dumps(summary, indent=2))

    needs_work = cs.under_evidenced_pids(scores)
    if needs_work:
        print(f'\n{len(needs_work)} parts need more evidence')
        for pid in needs_work[:10]:
            s = scores[pid]
            print(f'  pid {pid}: {s["layer"]}, evidence_ratio={s["evidence_ratio"]}, '
                  f'margin={s["margin"]}, tier={s["tier"]}')


def main():
    parser = argparse.ArgumentParser(description='Closed-loop adaptive coverage')
    sub = parser.add_subparsers(dest='cmd')

    p_plan = sub.add_parser('plan', help='Plan one round (no Veo generation)')
    p_plan.add_argument('room')
    p_plan.set_defaults(func=cmd_plan)

    p_run = sub.add_parser('run', help='Full loop with Veo generation')
    p_run.add_argument('room')
    p_run.add_argument('--max-rounds', type=int, default=MAX_ROUNDS)
    p_run.set_defaults(func=cmd_run)

    p_score = sub.add_parser('score', help='Score existing results')
    p_score.add_argument('estimator_json')
    p_score.add_argument('parts_npz')
    p_score.add_argument('--walker-width', type=float, default=30.0)
    p_score.set_defaults(func=cmd_score)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()
