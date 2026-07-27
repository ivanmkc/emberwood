import { createInput } from './input.js';
import { createGame } from './game.js';
import { loadArt } from './assets.js';

const canvas = document.getElementById('game');
const input = createInput();
const art = await loadArt();
const game = createGame(canvas, input, art);

document.getElementById('new-game').addEventListener('click', () => {
  if (window.confirm('Start a new game? Your save will be erased.')) game.newGame();
});

game.start();
