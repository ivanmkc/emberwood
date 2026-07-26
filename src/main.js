import { createInput } from './input.js';
import { createGame } from './game.js';

const canvas = document.getElementById('game');
const input = createInput();
const game = createGame(canvas, input);

document.getElementById('new-game').addEventListener('click', () => {
  if (window.confirm('Start a new game? Your save will be erased.')) game.newGame();
});

game.start();
