// Keyboard + touch input. Exposes held directions and edge-triggered action.

export function createInput() {
  const held = { up: false, down: false, left: false, right: false };
  let actionHeld = false;
  let actionQueued = false; // edge-triggered, consumed by game
  let newGameQueued = false;

  const KEYMAP = {
    ArrowUp: 'up', KeyW: 'up',
    ArrowDown: 'down', KeyS: 'down',
    ArrowLeft: 'left', KeyA: 'left',
    ArrowRight: 'right', KeyD: 'right',
  };

  window.addEventListener('keydown', (e) => {
    const dir = KEYMAP[e.code];
    if (dir) { held[dir] = true; e.preventDefault(); }
    if (e.code === 'Space' || e.code === 'Enter') {
      if (!actionHeld) actionQueued = true;
      actionHeld = true;
      e.preventDefault();
    }
    if (e.code === 'KeyN') newGameQueued = true;
  });

  window.addEventListener('keyup', (e) => {
    const dir = KEYMAP[e.code];
    if (dir) held[dir] = false;
    if (e.code === 'Space' || e.code === 'Enter') actionHeld = false;
  });

  // Touch controls: elements carry data-dir="up|down|left|right" or data-action.
  for (const el of document.querySelectorAll('[data-dir]')) {
    const dir = el.dataset.dir;
    const on = (e) => { held[dir] = true; e.preventDefault(); };
    const off = (e) => { held[dir] = false; e.preventDefault(); };
    el.addEventListener('touchstart', on, { passive: false });
    el.addEventListener('touchend', off, { passive: false });
    el.addEventListener('touchcancel', off, { passive: false });
    el.addEventListener('mousedown', on);
    el.addEventListener('mouseup', off);
    el.addEventListener('mouseleave', () => { held[dir] = false; });
  }
  for (const el of document.querySelectorAll('[data-action]')) {
    const on = (e) => { actionQueued = true; actionHeld = true; e.preventDefault(); };
    const off = (e) => { actionHeld = false; e.preventDefault(); };
    el.addEventListener('touchstart', on, { passive: false });
    el.addEventListener('touchend', off, { passive: false });
    el.addEventListener('mousedown', on);
    el.addEventListener('mouseup', off);
  }

  return {
    held,
    consumeAction() {
      const a = actionQueued;
      actionQueued = false;
      return a;
    },
    consumeNewGame() {
      const n = newGameQueued;
      newGameQueued = false;
      return n;
    },
  };
}
