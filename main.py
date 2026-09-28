"""Crazy 2048: the classic sliding tile puzzle with smooth animations.

Controls
    Arrows / WASD / mouse swipe   move tiles
    U, Backspace or Ctrl+Z        undo
    R or N                        new game
    Enter                         keep going after a win / restart after game over
    1 / 2 / 3                     easy / classic / hard
    M                             toggle sound
    Esc                           quit

Game rules live in game_logic.py; this file is only rendering, input and sound.
"""
import array
import json
import math
from pathlib import Path

import pygame

from game_logic import DIFFICULTIES, DIFFICULTY_ORDER, SIZES, Game, MoveResult

# ---------------------------------------------------------------- layout & timing

WIDTH, HEIGHT = 460, 690
FPS = 60
MARGIN = 20
BOARD_TOP = 150
BOARD_SIZE = WIDTH - 2 * MARGIN
BUTTON_TOP = BOARD_TOP + BOARD_SIZE + 18
BUTTON_HEIGHT = 44
BUTTON_GAP = 10
HINT_TOP = BUTTON_TOP + BUTTON_HEIGHT + 20

SLIDE_TIME = 0.12  # seconds for tiles to glide to their new cell
POP_TIME = 0.15  # merged tiles briefly grow and shrink back
SPAWN_TIME = 0.18  # new tiles scale in with a small overshoot
FLOAT_TIME = 0.9  # "+score" text rising above the score box
OVERLAY_FADE_TIME = 0.4
SCORE_COUNT_SPEED = 12  # how quickly the displayed score catches up
MAX_QUEUED_MOVES = 2
SWIPE_THRESHOLD = 30

SAVE_PATH = Path(__file__).with_name('save.json')
LEGACY_HIGH_SCORE_PATH = Path(__file__).with_name('high_score')
FONT_NAME = 'freesansbold.ttf'

# ---------------------------------------------------------------- colours

COLORS = {
    'background': (250, 248, 239),
    'board': (187, 173, 160),
    'empty': (205, 193, 180),
    'text_dark': (119, 110, 101),
    'text_light': (249, 246, 242),
    'panel_label': (238, 228, 218),
    'button': (143, 122, 102),
    'button_hover': (166, 143, 120),
    'button_disabled': (214, 205, 196),
    'overlay_win': (237, 194, 46),
    'overlay_lose': (238, 228, 218),
    'score_float': (119, 110, 101),
}

TILE_COLORS = {
    2: (238, 228, 218),
    4: (237, 224, 200),
    8: (242, 177, 121),
    16: (245, 149, 99),
    32: (246, 124, 95),
    64: (246, 94, 59),
    128: (237, 207, 114),
    256: (237, 204, 97),
    512: (237, 200, 80),
    1024: (237, 197, 63),
    2048: (237, 194, 46),
}
SUPER_TILE_COLOR = (60, 58, 50)


# ---------------------------------------------------------------- helpers

def clamp01(t):
    return max(0.0, min(1.0, t))


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def ease_out_back(t):
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


_font_cache = {}


def get_font(size):
    size = max(8, int(size))
    if size not in _font_cache:
        _font_cache[size] = pygame.font.Font(FONT_NAME, size)
    return _font_cache[size]


def blit_centered(surface, text, size, color, center):
    rendered = get_font(size).render(text, True, color)
    surface.blit(rendered, rendered.get_rect(center=center))


def best_key(size, difficulty):
    return f'{size}x{size}-{difficulty}'


# ---------------------------------------------------------------- persistence

class Storage:
    """Best scores, the sound setting and the in-progress game, kept in save.json."""

    def __init__(self, path):
        self.path = path
        self.best = {}
        self.saved_game = None
        self.sound_on = True
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        best = data.get('best', {})
        if isinstance(best, dict):
            self.best = {str(k): v for k, v in best.items() if isinstance(v, int)}
        self.saved_game = data.get('game')
        self.sound_on = bool(data.get('sound', True))
        self._migrate_legacy_high_score()

    def _migrate_legacy_high_score(self):
        # Older versions stored a single number in a file called "high_score".
        try:
            legacy = int(LEGACY_HIGH_SCORE_PATH.read_text(encoding='utf-8').strip() or 0)
        except (OSError, ValueError):
            return
        key = best_key(4, 'classic')
        self.best[key] = max(self.best.get(key, 0), legacy)

    def best_for(self, game):
        return self.best.get(best_key(game.size, game.difficulty), 0)

    def record_score(self, game):
        key = best_key(game.size, game.difficulty)
        if game.score > self.best.get(key, 0):
            self.best[key] = game.score

    def save(self, game):
        data = {'best': self.best, 'sound': self.sound_on, 'game': game.to_dict()}
        tmp = self.path.with_suffix('.tmp')
        try:
            tmp.write_text(json.dumps(data), encoding='utf-8')
            tmp.replace(self.path)
        except OSError:
            pass  # never let a full disk or read-only folder crash the game


# ---------------------------------------------------------------- sound

class SoundBank:
    """Tiny synthesised blips, so the game needs no audio files."""

    def __init__(self, enabled):
        self.enabled = enabled
        self.available = False
        self._cache = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self.rate, fmt, self.channels = pygame.mixer.get_init()
            self.available = fmt == -16
        except pygame.error:
            pass

    def _tone(self, freq, duration, volume):
        key = (round(freq), duration, volume)
        if key not in self._cache:
            frames = int(self.rate * duration)
            attack = max(1, int(self.rate * 0.005))
            data = array.array('h')
            for i in range(frames):
                envelope = min(1.0, i / attack) * (1 - i / frames)  # avoids clicks
                sample = int(32767 * volume * envelope * math.sin(2 * math.pi * freq * i / self.rate))
                data.extend([sample] * self.channels)
            self._cache[key] = pygame.mixer.Sound(buffer=data.tobytes())
        return self._cache[key]

    def play(self, name, value=0):
        if not (self.enabled and self.available):
            return
        if name == 'merge':
            # bigger merges sound higher
            freq = 330 * 2 ** (min(math.log2(max(value, 2)), 14) / 12)
            self._tone(freq, 0.07, 0.10).play()
        else:
            freq, duration, volume = {
                'move': (200, 0.04, 0.05),
                'bump': (110, 0.05, 0.06),
                'undo': (290, 0.06, 0.07),
                'new': (520, 0.08, 0.07),
                'win': (880, 0.30, 0.12),
                'over': (140, 0.35, 0.10),
            }[name]
            self._tone(freq, duration, volume).play()


# ---------------------------------------------------------------- board rendering

class BoardView:
    """Converts board cells to pixels and draws (cached) tile surfaces."""

    def __init__(self, size):
        self.rect = pygame.Rect(MARGIN, BOARD_TOP, BOARD_SIZE, BOARD_SIZE)
        self.set_size(size)

    def set_size(self, size):
        self.size = size
        self.gap = {3: 15, 4: 14, 5: 11, 6: 10}[size]
        self.cell = (BOARD_SIZE - self.gap * (size + 1)) / size
        self._tiles = {}

    def cell_center(self, row, col):
        step = self.cell + self.gap
        return (self.rect.x + self.gap + col * step + self.cell / 2,
                self.rect.y + self.gap + row * step + self.cell / 2)

    def _tile_surface(self, value):
        if value not in self._tiles:
            side = round(self.cell)
            surf = pygame.Surface((side, side), pygame.SRCALPHA)
            color = TILE_COLORS.get(value, SUPER_TILE_COLOR)
            pygame.draw.rect(surf, color, surf.get_rect(), border_radius=max(4, side // 12))

            text_color = COLORS['text_dark'] if value <= 4 else COLORS['text_light']
            digits = len(str(value))
            font_size = side * {1: 0.5, 2: 0.5, 3: 0.42, 4: 0.34}.get(digits, 0.28)
            text = get_font(font_size).render(str(value), True, text_color)
            while text.get_width() > side * 0.86 and font_size > 10:
                font_size -= 2
                text = get_font(font_size).render(str(value), True, text_color)
            surf.blit(text, text.get_rect(center=(side / 2, side / 2)))
            self._tiles[value] = surf
        return self._tiles[value]

    def draw_background(self, screen):
        pygame.draw.rect(screen, COLORS['board'], self.rect, border_radius=10)
        radius = max(4, round(self.cell) // 12)
        for r in range(self.size):
            for c in range(self.size):
                x, y = self.cell_center(r, c)
                rect = pygame.Rect(0, 0, round(self.cell), round(self.cell))
                rect.center = (round(x), round(y))
                pygame.draw.rect(screen, COLORS['empty'], rect, border_radius=radius)

    def draw_tile(self, screen, value, center, scale=1.0):
        if scale <= 0.05:
            return
        surf = self._tile_surface(value)
        if abs(scale - 1.0) > 0.01:
            side = max(1, round(surf.get_width() * scale))
            surf = pygame.transform.smoothscale(surf, (side, side))
        screen.blit(surf, surf.get_rect(center=(round(center[0]), round(center[1]))))


# ---------------------------------------------------------------- buttons

class Button:
    def __init__(self, rect, label, action, enabled=lambda: True):
        self.rect = pygame.Rect(rect)
        self.label = label  # a string or a function returning one
        self.action = action
        self.enabled = enabled

    def text(self):
        return self.label() if callable(self.label) else self.label

    def draw(self, screen, mouse_pos, color=None, text_color=None):
        if not self.enabled():
            fill, fg = COLORS['button_disabled'], COLORS['panel_label']
        elif self.rect.collidepoint(mouse_pos):
            fill, fg = COLORS['button_hover'], COLORS['text_light']
        else:
            fill, fg = color or COLORS['button'], text_color or COLORS['text_light']
        pygame.draw.rect(screen, fill, self.rect, border_radius=8)
        blit_centered(screen, self.text(), 17, fg, self.rect.center)


# ---------------------------------------------------------------- the app

class App:
    def __init__(self):
        pygame.display.set_caption('Crazy 2048')
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.storage = Storage(SAVE_PATH)
        self.sounds = SoundBank(self.storage.sound_on)

        self.game = self._load_or_create_game()
        self.board = BoardView(self.game.size)
        self.display_score = float(self.game.score)

        self.anim = None  # MoveResult currently being animated
        self.anim_start = 0.0
        self.floaters = []  # (text, start_time) for the rising "+N" labels
        self.pending_moves = []
        self.overlay_kind = None
        self.overlay_start = 0.0
        self.overlay_buttons = []
        self.swipe_start = None
        self.pressed_button = None

        self.buttons = self._make_buttons()
        self._animate_appear(self._all_tile_cells())

    # ------------------------------------------------------------ setup

    def _load_or_create_game(self):
        if self.storage.saved_game:
            try:
                return Game.from_dict(self.storage.saved_game)
            except ValueError:
                pass
        return Game()

    def _make_buttons(self):
        width = (BOARD_SIZE - 3 * BUTTON_GAP) / 4

        def rect(i):
            return (round(MARGIN + i * (width + BUTTON_GAP)), BUTTON_TOP, round(width), BUTTON_HEIGHT)

        def undo_label():
            left = self.game.undos_left
            return 'Undo' if left is None else f'Undo ({left})'

        return [
            Button(rect(0), undo_label, self.undo, lambda: self.game.can_undo),
            Button(rect(1), 'New Game', self.new_game),
            Button(rect(2), lambda: self.game.difficulty.title(), self.cycle_difficulty),
            Button(rect(3), lambda: f'{self.game.size}x{self.game.size}', self.cycle_size),
        ]

    # ------------------------------------------------------------ actions

    @staticmethod
    def now():
        return pygame.time.get_ticks() / 1000

    def _all_tile_cells(self):
        n = self.game.size
        return [(r, c) for r in range(n) for c in range(n) if self.game.grid[r][c]]

    def _animate_appear(self, cells):
        """Scale tiles in without a slide phase (new game, undo, loading)."""
        self.anim = MoveResult(moved=True, spawned=[c for c in cells if c])
        self.anim_start = self.now() - SLIDE_TIME
        self.pending_moves.clear()

    def _after_state_change(self):
        self.storage.record_score(self.game)
        self.storage.save(self.game)

    def queue_move(self, direction):
        if len(self.pending_moves) < MAX_QUEUED_MOVES:
            self.pending_moves.append(direction)

    def apply_move(self, direction):
        if not self.game.accepting_moves:
            return
        result = self.game.move(direction)
        if not result.moved:
            self.sounds.play('bump')
            return

        self.anim = result
        self.anim_start = self.now()
        if result.gained:
            self.floaters.append((f'+{result.gained}', self.now()))
            self.sounds.play('merge', result.biggest_merge)
        else:
            self.sounds.play('move')
        if result.reached_win:
            self.sounds.play('win')
        elif self.game.over:
            self.sounds.play('over')
        self._after_state_change()

    def undo(self):
        if self.game.undo():
            self.sounds.play('undo')
            self.display_score = float(self.game.score)
            self._animate_appear(self._all_tile_cells())
            self._after_state_change()
        else:
            self.sounds.play('bump')

    def new_game(self):
        self.storage.record_score(self.game)
        cells = self.game.new_game()
        self.display_score = 0.0
        self.floaters.clear()
        self.sounds.play('new')
        self._animate_appear(cells)
        self._after_state_change()

    def _restart_with(self, size, difficulty):
        self.storage.record_score(self.game)
        self.game = Game(size, difficulty)
        self.board.set_size(size)
        self.display_score = 0.0
        self.floaters.clear()
        self.sounds.play('new')
        self._animate_appear(self._all_tile_cells())
        self._after_state_change()

    def set_difficulty(self, difficulty):
        self._restart_with(self.game.size, difficulty)

    def cycle_difficulty(self):
        i = DIFFICULTY_ORDER.index(self.game.difficulty)
        self.set_difficulty(DIFFICULTY_ORDER[(i + 1) % len(DIFFICULTY_ORDER)])

    def cycle_size(self):
        i = SIZES.index(self.game.size)
        self._restart_with(SIZES[(i + 1) % len(SIZES)], self.game.difficulty)

    def keep_going(self):
        self.game.continue_after_win()
        self._after_state_change()

    def toggle_sound(self):
        self.sounds.enabled = not self.sounds.enabled
        self.storage.sound_on = self.sounds.enabled
        self.storage.save(self.game)

    # ------------------------------------------------------------ input

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            self.handle_key(event)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.pressed_button = self._button_at(event.pos)
            self.swipe_start = None if self.pressed_button else event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.pressed_button:
                if self.pressed_button.rect.collidepoint(event.pos) and self.pressed_button.enabled():
                    self.pressed_button.action()
            elif self.swipe_start:
                dx = event.pos[0] - self.swipe_start[0]
                dy = event.pos[1] - self.swipe_start[1]
                if max(abs(dx), abs(dy)) >= SWIPE_THRESHOLD:
                    if abs(dx) > abs(dy):
                        self.queue_move('LEFT' if dx < 0 else 'RIGHT')
                    else:
                        self.queue_move('UP' if dy < 0 else 'DOWN')
            self.pressed_button = None
            self.swipe_start = None

    def handle_key(self, event):
        key = event.key
        directions = {
            pygame.K_UP: 'UP', pygame.K_w: 'UP',
            pygame.K_DOWN: 'DOWN', pygame.K_s: 'DOWN',
            pygame.K_LEFT: 'LEFT', pygame.K_a: 'LEFT',
            pygame.K_RIGHT: 'RIGHT', pygame.K_d: 'RIGHT',
        }
        difficulties = {pygame.K_1: 'easy', pygame.K_2: 'classic', pygame.K_3: 'hard'}

        if key in directions:
            self.queue_move(directions[key])
        elif key in (pygame.K_u, pygame.K_BACKSPACE) or (key == pygame.K_z and event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META)):
            self.undo()
        elif key in (pygame.K_r, pygame.K_n):
            self.new_game()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            if self.overlay_kind == 'win':
                self.keep_going()
            elif self.overlay_kind == 'over':
                self.new_game()
        elif key in difficulties:
            self.set_difficulty(difficulties[key])
        elif key == pygame.K_m:
            self.toggle_sound()
        elif key == pygame.K_ESCAPE:
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _button_at(self, pos):
        # Overlay buttons sit on top of the board, so check them first.
        for button in self.overlay_buttons + self.buttons:
            if button.rect.collidepoint(pos):
                return button
        return None

    # ------------------------------------------------------------ update

    def is_sliding(self, now):
        return self.anim is not None and now - self.anim_start < SLIDE_TIME

    def update(self, dt, now):
        if self.pending_moves and not self.is_sliding(now):
            self.apply_move(self.pending_moves.pop(0))

        if self.anim and now - self.anim_start > SLIDE_TIME + max(POP_TIME, SPAWN_TIME):
            self.anim = None

        # Let the score roll up instead of jumping.
        diff = self.game.score - self.display_score
        self.display_score += diff * min(1.0, dt * SCORE_COUNT_SPEED)
        if abs(diff) < 0.5:
            self.display_score = float(self.game.score)

        self.floaters = [f for f in self.floaters if now - f[1] < FLOAT_TIME]

        # A new overlay only appears once the board has finished animating;
        # an existing one disappears as soon as the game accepts moves again.
        if self.game.accepting_moves:
            kind = None
        elif self.anim is not None:
            kind = self.overlay_kind
        elif self.game.won and not self.game.keep_playing:
            kind = 'win'
        else:
            kind = 'over'
        if kind != self.overlay_kind:
            self.overlay_kind = kind
            self.overlay_start = now
            self.overlay_buttons = self._make_overlay_buttons(kind)

    def _make_overlay_buttons(self, kind):
        cx = self.board.rect.centerx
        y = self.board.rect.centery + 40
        if kind == 'win':
            return [Button((cx - 150, y, 140, 44), 'Keep going', self.keep_going),
                    Button((cx + 10, y, 140, 44), 'New game', self.new_game)]
        if kind == 'over':
            buttons = [Button((cx - 70, y, 140, 44), 'Try again', self.new_game)]
            if self.game.can_undo:
                buttons = [Button((cx - 150, y, 140, 44), 'Undo', self.undo),
                           Button((cx + 10, y, 140, 44), 'Try again', self.new_game)]
            return buttons
        return []

    # ------------------------------------------------------------ drawing

    def draw(self, now):
        self.screen.fill(COLORS['background'])
        mouse = pygame.mouse.get_pos()
        self.draw_header(now)
        self.board.draw_background(self.screen)
        self.draw_tiles(now)
        self.draw_overlay(now, mouse)
        for button in self.buttons:
            button.draw(self.screen, mouse)
        sound = 'on' if self.sounds.enabled else 'off'
        blit_centered(self.screen, f'Arrows / WASD / swipe  -  U undo  -  R new  -  1-3 mode  -  M sound {sound}',
                      12, COLORS['text_dark'], (WIDTH / 2, HINT_TOP))
        pygame.display.flip()

    def draw_header(self, now):
        title = get_font(60).render('2048', True, COLORS['text_dark'])
        self.screen.blit(title, (MARGIN, 26))

        box_w, box_h, top = 96, 58, 32
        best_rect = pygame.Rect(WIDTH - MARGIN - box_w, top, box_w, box_h)
        score_rect = best_rect.move(-(box_w + 8), 0)
        best = max(self.storage.best_for(self.game), self.game.score)
        for rect, label, value in ((score_rect, 'SCORE', round(self.display_score)), (best_rect, 'BEST', best)):
            pygame.draw.rect(self.screen, COLORS['board'], rect, border_radius=6)
            blit_centered(self.screen, label, 13, COLORS['panel_label'], (rect.centerx, rect.y + 16))
            size = 24 if value < 100000 else 18
            blit_centered(self.screen, str(value), size, COLORS['text_light'], (rect.centerx, rect.y + 40))

        for text, start in self.floaters:
            t = clamp01((now - start) / FLOAT_TIME)
            label = get_font(22).render(text, True, COLORS['score_float'])
            label.set_alpha(round(255 * (1 - t)))
            y = score_rect.y + 6 - 30 * ease_out_cubic(t)
            self.screen.blit(label, label.get_rect(center=(score_rect.centerx, y)))

        mode = DIFFICULTIES[self.game.difficulty]
        undo_text = 'unlimited undo' if mode.undo_limit is None else f'{mode.undo_limit} undos' if mode.undo_limit else 'no undo'
        info = f'{self.game.size}x{self.game.size}  -  {mode.name.title()} ({undo_text})  -  Moves: {self.game.moves}'
        self.screen.blit(get_font(15).render(info, True, COLORS['text_dark']), (MARGIN, 100))
        goal = f'Join the tiles, get to {self.game.win_value}!'
        self.screen.blit(get_font(15).render(goal, True, COLORS['text_dark']), (MARGIN, 122))

    def draw_tiles(self, now):
        anim = self.anim
        elapsed = now - self.anim_start if anim else 0.0

        if anim and elapsed < SLIDE_TIME:
            t = ease_out_cubic(clamp01(elapsed / SLIDE_TIME))
            # Draw stationary tiles first so moving ones glide over them.
            slides = sorted(anim.slides, key=lambda s: s[1] != s[2])
            for value, src, dst in slides:
                x0, y0 = self.board.cell_center(*src)
                x1, y1 = self.board.cell_center(*dst)
                self.board.draw_tile(self.screen, value, (lerp(x0, x1, t), lerp(y0, y1, t)))
            return

        after = elapsed - SLIDE_TIME
        n = self.game.size
        for r in range(n):
            for c in range(n):
                value = self.game.grid[r][c]
                if not value:
                    continue
                scale = 1.0
                if anim and (r, c) in anim.spawned:
                    scale = ease_out_back(clamp01(after / SPAWN_TIME))
                elif anim and (r, c) in anim.merged:
                    scale = 1 + 0.18 * math.sin(math.pi * clamp01(after / POP_TIME))
                self.board.draw_tile(self.screen, value, self.board.cell_center(r, c), scale)

    def draw_overlay(self, now, mouse):
        if not self.overlay_kind:
            return
        alpha = ease_out_cubic(clamp01((now - self.overlay_start) / OVERLAY_FADE_TIME))
        rect = self.board.rect
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        if self.overlay_kind == 'win':
            color, fg = COLORS['overlay_win'], COLORS['text_light']
            title, subtitle = 'You win!', f'You reached {self.game.win_value}.'
        else:
            color, fg = COLORS['overlay_lose'], COLORS['text_dark']
            title, subtitle = 'Game over!', f'Final score: {self.game.score}'
        pygame.draw.rect(layer, (*color, 200), layer.get_rect(), border_radius=10)
        blit_centered(layer, title, 48, fg, (rect.width / 2, rect.height / 2 - 60))
        blit_centered(layer, subtitle, 20, fg, (rect.width / 2, rect.height / 2 - 15))
        for button in self.overlay_buttons:
            local = button.rect.move(-rect.x, -rect.y)
            hovered = button.rect.collidepoint(mouse)
            pygame.draw.rect(layer, COLORS['button_hover'] if hovered else COLORS['button'], local, border_radius=8)
            blit_centered(layer, button.text(), 17, COLORS['text_light'], local.center)
        layer.set_alpha(round(255 * alpha))
        # Slide the panel up slightly as it fades in.
        self.screen.blit(layer, (rect.x, rect.y + round(12 * (1 - alpha))))

    # ------------------------------------------------------------ main loop

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000
            now = self.now()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                else:
                    self.handle_event(event)
            self.update(dt, now)
            self.draw(now)
        self.storage.record_score(self.game)
        self.storage.save(self.game)


def main():
    pygame.mixer.pre_init(22050, -16, 1, 512)
    pygame.init()
    try:
        App().run()
    finally:
        pygame.quit()


if __name__ == '__main__':
    main()
