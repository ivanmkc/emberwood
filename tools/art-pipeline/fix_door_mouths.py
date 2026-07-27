#!/usr/bin/env python3
"""Door-mouth thresholds: doors painted into plates after mask generation
have wall-blocked thresholds. Carve a standable mouth under each door in the
device-res collision (door center +/-12 logical, from just above the door
base down to the first standable row + hitbox), so a player can reach the
trigger. Verifies box-standability after carving.
"""
import json
import os

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AP = os.path.join(ROOT, 'tools', 'art-pipeline')

doors = json.load(open(os.path.join(AP, 'doors.json')))
for parent, dl in doors.items():
    cp = os.path.join(ROOT, 'assets', 'rooms', f'{parent}.collision.png')
    img = Image.open(cp).convert('L')
    col = np.asarray(img).copy()  # device res 1280x896 (logical *2)
    changed = False
    for d in dl:
        x0, y0, x1, y1 = d['rect']  # logical
        cx = (x0 + x1) // 2
        # find first standable row below door base (box 8x8 logical = 16x16 dev)
        walk = col > 127
        foot = None
        for y in range(max(8, y1 - 6), min(447, y1 + 90)):
            if walk[(y - 8) * 2:(y + 1) * 2, (cx - 4) * 2:(cx + 5) * 2].all():
                foot = y
                break
        import cv2
        walkb = col > 127
        n_, lab_ = cv2.connectedComponents(walkb.astype(np.uint8))
        sizes = [(lab_ == i).sum() for i in range(1, n_)]
        main = 1 + int(np.argmax(sizes)) if sizes else 0
        # standable AND connected to the main component?
        ok_connected = False
        if foot is not None and foot <= y1 + 12 and main:
            zone = lab_[max(0, (foot - 8) * 2):(foot + 1) * 2, (cx - 4) * 2:(cx + 5) * 2]
            ok_connected = (zone == main).any()
        if ok_connected:
            continue
        if foot is None:
            foot = min(446, y1 + 60)
        # carve mouth box + a corridor to the nearest main-component pixel
        ya, yb = max(0, (y1 - 16) * 2), min(895, (foot + 4) * 2)
        xa, xb = max(0, (cx - 12) * 2), min(1279, (cx + 12) * 2)
        col[ya:yb, xa:xb] = 255
        if main:
            ys_, xs_ = np.where(lab_ == main)
            my, mx = (ya + yb) // 2, (xa + xb) // 2
            k_ = ((ys_ - my) ** 2 + (xs_ - mx) ** 2).argmin()
            ty_, tx_ = int(ys_[k_]), int(xs_[k_])
            # L-corridor 24 device px wide
            w2 = 22  # corridor half-width in device px: 11 logical, wider than the hitbox
            x_lo, x_hi = sorted((mx, tx_))
            y_lo, y_hi = sorted((my, ty_))
            col[my - w2:my + w2, x_lo:x_hi + 1] = 255
            col[y_lo:y_hi + 1, tx_ - w2:tx_ + w2] = 255
        changed = True
        print(f'[{parent}] mouth+corridor carved for door -> {d["to"]}')
    if changed:
        Image.fromarray(col).save(cp)
print('done')
