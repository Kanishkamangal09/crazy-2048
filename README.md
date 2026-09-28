# Crazy 2048

My take on the classic 2048 puzzle, made with Python and pygame.

Slide the tiles around. When two tiles with the same number touch, they join into one. Try to reach 2048!

## How to run

You need Python 3.10 or newer.

```bash
pip install pygame
python main.py
```

If you're using the included virtual environment:

```bash
.venv/bin/python main.py
```

## Controls

| Key | What it does |
| --- | --- |
| Arrow keys / WASD / mouse swipe | Move tiles |
| U | Undo |
| R | New game |
| Enter | Keep going after a win, or restart after losing |
| 1 / 2 / 3 | Easy / Classic / Hard |
| M | Sound on or off |
| Esc | Quit |

You can also use the buttons below the board.

## Features

- Tiles slide smoothly, and merges pop
- Board sizes from 3x3 to 6x6
- Three difficulty levels:
  - **Easy:** unlimited undo
  - **Classic:** 3 undos per game
  - **Hard:** no undo and more 4s
- A separate best score for each board size and difficulty
- Your game saves by itself, so you can close it and come back later
- Simple sound effects (no audio files needed)

## How it works

The code is split into two files:

- **`game_logic.py`**: the game rules. It handles sliding and merging tiles, scoring, undo, and checking for a win or game over. It doesn't use pygame at all, which makes it easy to test.
- **`main.py`**: everything you see and hear. It draws the board, runs the animations, reads your keys and mouse, plays sounds, and saves your progress to `save.json`.

Each move works like this:

1. Every row (or column) is squashed toward the side you pressed.
2. Equal neighbours merge once, and their total goes to your score.
3. A new 2 or 4 appears in a random empty cell.
4. If nothing can move any more, it's game over.

The rules code also records where every tile started and ended. `main.py` uses that to animate the tiles gliding into place.

## Tests

```bash
python -m unittest test_game_logic
```
