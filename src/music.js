// Ambient dusk music: soft detuned pad + sparse pentatonic plucks, tinted
// per area. Pure WebAudio, starts on first user gesture, M toggles mute.

const SCENES = {
  overworld: { root: 110, mode: [0, 3, 5, 7, 10], pluckEvery: 2.6, bright: 900 },
  biodome: { root: 98, mode: [0, 2, 5, 7, 9], pluckEvery: 3.2, bright: 1400 },
  cave: { root: 55, mode: [0, 3, 7], pluckEvery: 4.5, bright: 500 },
  mine2: { root: 55, mode: [0, 3, 7, 10], pluckEvery: 4.0, bright: 500 },
  house: { root: 131, mode: [0, 4, 7, 9], pluckEvery: 3.0, bright: 1100 },
  home: { root: 131, mode: [0, 4, 7, 9], pluckEvery: 3.0, bright: 1100 },
};

export function createMusic() {
  let ac = null;
  let master = null;
  let padOsc = [];
  let padGain = null;
  let filter = null;
  let muted = false;
  let scene = 'overworld';
  let pluckTimer = null;
  let step = 0;

  function ensure() {
    if (ac) return true;
    try {
      ac = new (window.AudioContext || window.webkitAudioContext)();
      master = ac.createGain();
      master.gain.value = 0.05;
      master.connect(ac.destination);
      filter = ac.createBiquadFilter();
      filter.type = 'lowpass';
      filter.frequency.value = 900;
      filter.connect(master);
      padGain = ac.createGain();
      padGain.gain.value = 0.5;
      padGain.connect(filter);
      for (const [mult, detune] of [[1, -4], [1, 4], [1.5, 0]]) {
        const o = ac.createOscillator();
        o.type = 'triangle';
        o.frequency.value = 110 * mult;
        o.detune.value = detune;
        o.connect(padGain);
        o.start();
        padOsc.push({ o, mult });
      }
      // slow breathing on the pad
      const lfo = ac.createOscillator();
      const lfoGain = ac.createGain();
      lfo.frequency.value = 0.07;
      lfoGain.gain.value = 0.18;
      lfo.connect(lfoGain).connect(padGain.gain);
      lfo.start();
      schedulePlucks();
      applyScene();
      return true;
    } catch {
      ac = null;
      return false;
    }
  }

  function applyScene() {
    if (!ac) return;
    const s = SCENES[scene] || SCENES.overworld;
    const t = ac.currentTime;
    for (const { o, mult } of padOsc) {
      o.frequency.exponentialRampToValueAtTime(Math.max(20, s.root * mult), t + 2.5);
    }
    filter.frequency.exponentialRampToValueAtTime(s.bright, t + 2.5);
    if (pluckTimer) clearInterval(pluckTimer);
    schedulePlucks();
  }

  function schedulePlucks() {
    const s = SCENES[scene] || SCENES.overworld;
    pluckTimer = setInterval(() => {
      if (!ac || muted || document.hidden) return;
      step += 1;
      if (step % 3 === 0) return; // leave holes — sparseness is the mood
      const deg = s.mode[(step * 7) % s.mode.length];
      const oct = (step % 5 === 0) ? 4 : 2;
      const freq = s.root * oct * Math.pow(2, deg / 12);
      const o = ac.createOscillator();
      const gn = ac.createGain();
      o.type = 'sine';
      o.frequency.value = freq;
      gn.gain.setValueAtTime(0.12, ac.currentTime);
      gn.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 1.6);
      o.connect(gn).connect(filter);
      o.start();
      o.stop(ac.currentTime + 1.7);
    }, (s.pluckEvery || 3) * 1000);
  }

  return {
    start() { ensure(); },
    setScene(id) {
      scene = id;
      applyScene();
    },
    toggle() {
      muted = !muted;
      if (master) master.gain.value = muted ? 0 : 0.05;
      return muted;
    },
  };
}
