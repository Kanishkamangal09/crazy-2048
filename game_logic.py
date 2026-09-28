"""Pure 2048 game rules.

Nothing in here touches pygame, so the rules can be unit tested on their own
(see test_game_logic.py). The UI in main.py only reads the state and the
MoveResult returned by Game.move() to drive its animations.
"""
import random
from dataclasses import dataclass, field

DIRECTIONS = ('UP', 'DOWN', 'LEFT', 'RIGHT')
SIZES = (3, 4, 5, 6)
# The tile you need to reach to win, per board size.
WIN_VALUES = {3: 512, 4: 2048, 5: 4096, 6: 8192}
MAX_HISTORY = 50


@dataclass(frozen=True)
class Difficulty:
    name: str
    four_chance: float  # probability that a spawned tile is a 4 instead of a 2
    undo_limit: int | None  # undos allowed per game, None means unlimited


DIFFICULTIES = {
    'easy': Difficulty('easy', 0.05, None),
    'classic': Difficulty('classic', 0.10, 3),
    'hard': Difficulty('hard', 0.25, 0),
}
DIFFICULTY_ORDER = list(DIFFICULTIES)


@dataclass
class MoveResult:
    """What happened during one move, in enough detail to animate it."""
    moved: bool = False
    gained: int = 0
    # (value before the move, from_cell, to_cell) for every tile on the board
    slides: list = field(default_factory=list)
    # cells that now hold a tile created by merging two tiles
    merged: set = field(default_factory=set)
    # values of the tiles created by those merges
    merged_values: list = field(default_factory=list)
    # cells where a new tile appeared
    spawned: list = field(default_factory=list)
    reached_win: bool = False

    @property
    def biggest_merge(self):
        return max(self.merged_values, default=0)


def slide_line(values):
    """Slide one line of tiles toward index 0, merging equal neighbours once.

    Returns (new_line, moves, merged_indices, gained) where moves is a list of
    (source_index, destination_index) for every non-empty tile.
    """
    result = []
    moves = []
    merged = set()
    gained = 0
    for src, value in enumerate(values):
        if value == 0:
            continue
        last = len(result) - 1
        if result and result[last] == value and last not in merged:
            result[last] *= 2
            gained += result[last]
            merged.add(last)
            moves.append((src, last))
        else:
            result.append(value)
            moves.append((src, len(result) - 1))
    result.extend([0] * (len(values) - len(result)))
    return result, moves, merged, gained


def lines_for(size, direction):
    """Every line of the board as a list of (row, col), starting at the edge tiles move toward."""
    idx = range(size)
    if direction == 'LEFT':
        return [[(r, c) for c in idx] for r in idx]
    if direction == 'RIGHT':
        return [[(r, c) for c in reversed(idx)] for r in idx]
    if direction == 'UP':
        return [[(r, c) for r in idx] for c in idx]
    if direction == 'DOWN':
        return [[(r, c) for r in reversed(idx)] for c in idx]
    raise ValueError(f'unknown direction: {direction!r}')


class Game:
    def __init__(self, size=4, difficulty='classic', rng=None):
        if size not in SIZES:
            raise ValueError(f'unsupported board size: {size}')
        if difficulty not in DIFFICULTIES:
            raise ValueError(f'unknown difficulty: {difficulty!r}')
        self.size = size
        self.difficulty = difficulty
        self.rng = rng or random.Random()
        self.new_game()

    # ------------------------------------------------------------ state

    def new_game(self):
        """Reset the board and return the cells of the two starting tiles."""
        self.grid = [[0] * self.size for _ in range(self.size)]
        self.score = 0
        self.moves = 0
        self.won = False
        self.keep_playing = False
        self.over = False
        self.undos_used = 0
        self.history = []
        return [self.spawn_tile(), self.spawn_tile()]

    @property
    def win_value(self):
        return WIN_VALUES[self.size]

    @property
    def max_tile(self):
        return max(max(row) for row in self.grid)

    @property
    def accepting_moves(self):
        """False while the game is over or the win screen is waiting for an answer."""
        return not self.over and (not self.won or self.keep_playing)

    @property
    def undos_left(self):
        limit = DIFFICULTIES[self.difficulty].undo_limit
        return None if limit is None else max(0, limit - self.undos_used)

    @property
    def can_undo(self):
        return bool(self.history) and self.undos_left != 0

    def empty_cells(self):
        return [(r, c) for r in range(self.size) for c in range(self.size) if self.grid[r][c] == 0]

    def spawn_tile(self):
        empty = self.empty_cells()
        if not empty:
            return None
        r, c = self.rng.choice(empty)
        four = self.rng.random() < DIFFICULTIES[self.difficulty].four_chance
        self.grid[r][c] = 4 if four else 2
        return (r, c)

    def can_move(self):
        n = self.size
        for r in range(n):
            for c in range(n):
                value = self.grid[r][c]
                if value == 0:
                    return True
                if r + 1 < n and self.grid[r + 1][c] == value:
                    return True
                if c + 1 < n and self.grid[r][c + 1] == value:
                    return True
        return False

    # ------------------------------------------------------------ actions

    def move(self, direction):
        result = MoveResult()
        if not self.accepting_moves:
            return result

        new_grid = [[0] * self.size for _ in range(self.size)]
        for cells in lines_for(self.size, direction):
            values = [self.grid[r][c] for r, c in cells]
            new_values, moves, merged, gained = slide_line(values)
            for (r, c), value in zip(cells, new_values):
                new_grid[r][c] = value
            for src, dst in moves:
                result.slides.append((values[src], cells[src], cells[dst]))
                if src != dst:
                    result.moved = True
            for i in merged:
                result.merged.add(cells[i])
                result.merged_values.append(new_values[i])
            result.gained += gained

        if not result.moved:
            return result

        self._push_history()
        self.grid = new_grid
        self.score += result.gained
        self.moves += 1
        if not self.won and result.biggest_merge >= self.win_value:
            self.won = True
            result.reached_win = True
        spawned = self.spawn_tile()
        if spawned:
            result.spawned.append(spawned)
        self.over = not self.can_move()
        return result

    def undo(self):
        if not self.can_undo:
            return False
        snapshot = self.history.pop()
        self.grid = [row[:] for row in snapshot['grid']]
        self.score = snapshot['score']
        self.moves = snapshot['moves']
        self.won = snapshot['won']
        self.keep_playing = snapshot['keep_playing']
        self.over = not self.can_move()
        self.undos_used += 1
        return True

    def continue_after_win(self):
        self.keep_playing = True

    def _push_history(self):
        self.history.append({
            'grid': [row[:] for row in self.grid],
            'score': self.score,
            'moves': self.moves,
            'won': self.won,
            'keep_playing': self.keep_playing,
        })
        del self.history[:-MAX_HISTORY]

    # ------------------------------------------------------------ persistence

    def to_dict(self):
        return {
            'size': self.size,
            'difficulty': self.difficulty,
            'grid': self.grid,
            'score': self.score,
            'moves': self.moves,
            'won': self.won,
            'keep_playing': self.keep_playing,
            'undos_used': self.undos_used,
            'history': self.history,
        }

    @classmethod
    def from_dict(cls, data, rng=None):
        """Rebuild a saved game. Raises ValueError if the data is malformed."""
        try:
            game = cls(int(data['size']), str(data['difficulty']), rng)
            grid = _validated_grid(data['grid'], game.size)
            history = [dict(s, grid=_validated_grid(s['grid'], game.size)) for s in data.get('history', [])]
            for snapshot in history:
                for key in ('score', 'moves'):
                    snapshot[key] = int(snapshot[key])
                for key in ('won', 'keep_playing'):
                    snapshot[key] = bool(snapshot[key])
            game.grid = grid
            game.score = int(data['score'])
            game.moves = int(data['moves'])
            game.won = bool(data['won'])
            game.keep_playing = bool(data['keep_playing'])
            game.undos_used = int(data.get('undos_used', 0))
            game.history = history[-MAX_HISTORY:]
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f'invalid saved game: {exc}') from exc
        game.over = not game.can_move()
        return game


def _validated_grid(grid, size):
    if len(grid) != size or any(len(row) != size for row in grid):
        raise ValueError('grid has the wrong shape')
    clean = [[int(v) for v in row] for row in grid]
    for row in clean:
        for v in row:
            if v != 0 and (v < 2 or v & (v - 1)):
                raise ValueError(f'invalid tile value: {v}')
    return clean
