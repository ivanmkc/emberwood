#!/usr/bin/env python3
"""Final gate: judge the in-game verification screenshots against the style
anchor and write VERIFICATION.md summarizing every gate in the pipeline.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge import judge_vote  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ANCHOR = os.path.join(ROOT, 'docs', 'art-options', 'nbp-scifi-anchor.png')
VERDICTS = os.path.join(HERE, 'verdicts.json')


def main(shots_dir):
    verdicts = json.load(open(VERDICTS)) if os.path.exists(VERDICTS) else {}
    fails = []
    for f in sorted(os.listdir(shots_dir)):
        if not f.startswith('final-') or not f.endswith('.png'):
            continue
        scene = f[6:-4]
        jv = judge_vote([ANCHOR, os.path.join(shots_dir, f)], 'screenshot',
                        context=f'scene: {scene}. This is a real playable game frame (HUD, '
                                'smaller viewport and simpler density than the concept anchor are '
                                'expected); judge style direction, perspective and glaring breakage, '
                                'not concept-art polish.')
        passed = bool(jv.get('style_score', 0) >= 6 and jv.get('perspective_ok'))
        verdicts[f'screenshot:{scene}'] = {'pass': passed, 'judge': jv}
        print(f'{"PASS" if passed else "FAIL"} screenshot:{scene} judge={jv}')
        if not passed:
            fails.append(scene)
    json.dump(verdicts, open(VERDICTS, 'w'), indent=1)

    # write the verification matrix
    lines = ['# Verification matrix\n',
             'Every gate: deterministic checks + Gemini rubric (median-of-3 vote).\n']
    for section, prefix in [('Props', 'asset:'), ('Terrain tiles', 'tile:'),
                            ('Characters', 'char:'), ('In-game screenshots', 'screenshot:')]:
        lines.append(f'\n## {section}\n')
        for k in sorted(verdicts):
            if not k.startswith(prefix):
                continue
            v = verdicts[k]
            j = v.get('judge', {})
            issues = str(j.get('issues', j.get('regressions', ''))).strip()
            lines.append(f'- {"✅" if v["pass"] else "❌"} `{k[len(prefix):]}` — ' +
                         ', '.join(f'{kk}={j[kk]}' for kk in
                                   ['style_match', 'style_score', 'tileable', 'perspective_ok',
                                    'theme_fit'] if kk in j) +
                         (f' — {issues[:110]}' if issues and issues.lower() not in ('none', '') else ''))
    open(os.path.join(HERE, 'VERIFICATION.md'), 'w').write('\n'.join(lines) + '\n')
    print(f'\n{len(fails)} screenshot failures' if fails else '\nSCREENSHOT GATES PASS')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/emberwood-verify')
