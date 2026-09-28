import random
import unittest

from game_logic import Game, slide_line


def game_with(grid, difficulty='classic'):
    game = Game(len(grid), difficulty, rng=random.Random(0))
    game.grid = [row[:] for row in grid]
    game.over = not game.can_move()
    return game


class SlideLineTests(unittest.TestCase):
    def test_merges_pairs_once(self):
        self.assertEqual(slide_line([2, 2, 2, 2])[0], [4, 4, 0, 0])

    def test_merged_tile_does_not_merge_again(self):
        self.assertEqual(slide_line([2, 2, 4, 0])[0], [4, 4, 0, 0])

    def test_gaps_are_closed(self):
        self.assertEqual(slide_line([0, 4, 0, 4])[0], [8, 0, 0, 0])

    def test_score_and_moves(self):
        line, moves, merged, gained = slide_line([4, 0, 4, 2])
        self.assertEqual(line, [8, 2, 0, 0])
        self.assertEqual(moves, [(0, 0), (2, 0), (3, 1)])
        self.assertEqual(merged, {0})
        self.assertEqual(gained, 8)


class GameTests(unittest.TestCase):
    def test_new_game_has_two_tiles(self):
        game = Game(rng=random.Random(1))
        self.assertEqual(sum(v != 0 for row in game.grid for v in row), 2)

    def test_move_right_merges_and_spawns(self):
        game = game_with([[2, 2, 0, 0], [0] * 4, [0] * 4, [0] * 4])
        result = game.move('RIGHT')
        self.assertTrue(result.moved)
        self.assertEqual(game.grid[0][3], 4)
        self.assertEqual(game.score, 4)
        self.assertEqual(len(result.spawned), 1)
        self.assertIn((0, 3), result.merged)

    def test_invalid_move_changes_nothing(self):
        game = game_with([[2, 0, 0, 0], [0] * 4, [0] * 4, [0] * 4])
        result = game.move('LEFT')
        self.assertFalse(result.moved)
        self.assertEqual(game.moves, 0)
        self.assertEqual(game.history, [])

    def test_undo_restores_board_and_score(self):
        game = game_with([[2, 2, 0, 0], [0] * 4, [0] * 4, [0] * 4])
        before = [row[:] for row in game.grid]
        game.move('LEFT')
        self.assertTrue(game.undo())
        self.assertEqual(game.grid, before)
        self.assertEqual(game.score, 0)
        self.assertEqual(game.moves, 0)

    def test_undo_limits(self):
        game = game_with([[2, 0, 0, 0], [0] * 4, [0] * 4, [0] * 4], 'hard')
        game.move('RIGHT')
        self.assertFalse(game.undo())
        game = game_with([[2, 0, 0, 0], [0] * 4, [0] * 4, [0] * 4], 'classic')
        for _ in range(3):
            game.move('RIGHT')
            game.undo()
        game.move('RIGHT')
        self.assertEqual(game.undos_left, 0)
        self.assertFalse(game.undo())

    def test_win_blocks_until_continue(self):
        game = game_with([[1024, 1024, 0, 0], [0] * 4, [0] * 4, [0] * 4])
        result = game.move('LEFT')
        self.assertTrue(result.reached_win and game.won)
        self.assertFalse(game.move('RIGHT').moved)
        game.continue_after_win()
        self.assertTrue(game.accepting_moves)

    def test_game_over_detection(self):
        game = game_with([[2, 4, 2], [4, 2, 4], [2, 4, 2]])
        self.assertTrue(game.over)
        self.assertFalse(game.move('LEFT').moved)

    def test_save_round_trip(self):
        game = game_with([[2, 2, 0, 0], [0] * 4, [0] * 4, [0] * 4])
        game.move('LEFT')
        loaded = Game.from_dict(game.to_dict())
        self.assertEqual(loaded.grid, game.grid)
        self.assertEqual(loaded.score, game.score)
        self.assertTrue(loaded.undo())

    def test_bad_save_raises_value_error(self):
        with self.assertRaises(ValueError):
            Game.from_dict({'size': 4, 'difficulty': 'classic', 'grid': [[3]]})


if __name__ == '__main__':
    unittest.main()
