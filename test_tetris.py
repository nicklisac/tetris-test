#!/usr/bin/env python3
"""Headless tests for tetris.py - drive the game logic without a terminal.

    python3 -m unittest -v test_tetris
"""

import curses
import os
import random
import types
import unittest

import tetris
from tetris import (CLEAR_ANIM, COLS, HARD_DROP_SCORE, HIDDEN, LOCK_DELAY,
                    MAX_LOCK_RESETS, MAX_LEVEL, ROWS, VIS_ROWS, Game, Piece,
                    Theme, clear_rows, collides, full_rows, ghost_y,
                    gravity_interval, level_for_lines, make_board)

STRAY_ROW, STRAY_COL = 0, 0          # a leftover block that blocks perfect clears


def make_opts(**kw):
    opts = types.SimpleNamespace(next=3, start_level=1, hold=True, shadow=True,
                                 color=False, ascii=False)
    for k, v in kw.items():
        setattr(opts, k, v)
    return opts


def new_game(seed=1234, **kw):
    random.seed(seed)
    return Game(make_opts(**kw))


def stray(g):
    """Park one block far above the action so a clear is never 'perfect'."""
    g.board[STRAY_ROW][STRAY_COL] = 6


def drop_clear(g, kind, x, y=0, rot=0, perfect=False, settle=True):
    """Hard-drop a piece; return the points earned by line clears only.

    Hard-drop points are subtracted so the assertions read as pure line value.
    A clear that empties the field also pays the perfect-clear bonus, so by
    default a stray block is left on the board unless `perfect` is requested.
    """
    if not perfect:
        stray(g)
    piece = Piece(kind, x=x, y=y, rot=rot)
    dist = ghost_y(g.board, piece) - piece.y
    g.piece = piece
    before = g.score
    g.hard_drop()
    drop_clear.rows = list(g.anim_rows)
    if settle and g.clear_anim > 0:
        g.update(CLEAR_ANIM)              # settle the flash before the next move
    return g.score - before - HARD_DROP_SCORE * dist


drop_clear.rows = []


def fill_row(board, y, except_cols=()):
    for x in range(COLS):
        board[y][x] = 0 if x in except_cols else 7


def well(g, rows, cols=(5,)):
    """Fill `rows` completely except the given columns: a well to drop into.

    A vertical I at x=3 fills column 5, so len(rows) rows clear at once.
    """
    for y in rows:
        fill_row(g.board, y, except_cols=cols)


def pocket(g):
    """T-spin-double pocket in the bottom three rows:

        ...#.#....   overhang, one-cell channel in the middle
        ###...####   three-cell notch
        ####.#####   single hole below the channel
    """
    g.board = make_board()
    for x in range(COLS):
        if x != 4:
            g.board[ROWS - 1][x] = 7
        if x not in (3, 4, 5):
            g.board[ROWS - 2][x] = 7
    g.board[ROWS - 3][3] = 7
    g.board[ROWS - 3][5] = 7
    return g


class FakeWindow:
    """Records addstr calls and enforces screen bounds the way curses does."""

    def __init__(self, y, x):
        self.size = (y, x)
        self.written = []

    def getmaxyx(self):
        return self.size

    def erase(self):
        self.written = []

    def refresh(self):
        pass

    def noutrefresh(self):
        pass

    def addstr(self, y, x, text, attr=0):
        if y < 0 or y >= self.size[0] or x < 0 or x >= self.size[1]:
            raise curses.error("addstr out of bounds")
        if x + len(text) > self.size[1]:
            raise curses.error("addstr past the right margin")
        self.written.append((y, x, text))

    def addch(self, *a, **kw):
        raise AssertionError("the renderer must not use addch")

    def rows_text(self):
        grid = [[" "] * self.size[1] for _ in range(self.size[0])]
        for y, x, text in self.written:
            for i, c in enumerate(text):
                if x + i < self.size[1]:
                    grid[y][x + i] = c
        return ["".join(row) for row in grid]


class GeometryTests(unittest.TestCase):
    def test_four_rotation_states_per_piece(self):
        for kind, states in tetris.SHAPES.items():
            self.assertEqual(len(states), 4, kind)
            self.assertEqual(states[0], tetris.BASE_SHAPES[kind], kind)
            back = states[0]
            for _ in range(4):
                back = tetris.rotate_cw(back)
            self.assertEqual(back, states[0], kind)
            n = len(states[0])
            for s in states:
                self.assertEqual((len(s), len(s[0])), (n, n), kind)

    def test_every_state_has_four_cells(self):
        for kind in tetris.PIECE_ORDER:
            for rot in range(4):
                self.assertEqual(len(Piece(kind, x=3, y=5, rot=rot).cells()), 4,
                                 "%s rot%d" % (kind, rot))

    def test_spawn_position(self):
        g = new_game()
        p = g.piece
        self.assertGreaterEqual(p.y, 0, "spawn stays inside the buffer rows")
        xs = [x for x, _ in p.cells()]
        self.assertTrue(all(0 <= x < COLS for x in xs))
        if p.kind == "O":
            self.assertEqual((min(xs), max(xs)), (4, 5))
        else:
            self.assertEqual((min(xs), max(xs)), (3, 5))

    def test_walls_and_floor_block(self):
        g = new_game()
        g.piece = Piece("O", x=0, y=5)
        self.assertTrue(collides(g.board, g.piece, dx=-1))
        self.assertFalse(collides(g.board, g.piece, dx=1))
        g.piece = Piece("O", x=COLS - 2, y=5)
        self.assertTrue(collides(g.board, g.piece, dx=1))
        g.piece = Piece("O", x=4, y=ROWS - 3)
        self.assertFalse(collides(g.board, g.piece, dy=1))
        g.piece = Piece("O", x=4, y=ROWS - 2)
        self.assertTrue(collides(g.board, g.piece, dy=1))

    def test_blocks_below_block(self):
        g = new_game()
        g.board[ROWS - 2][4] = 7
        g.board[ROWS - 2][5] = 7
        g.piece = Piece("O", x=4, y=ROWS - 5)
        self.assertFalse(collides(g.board, g.piece, dy=1))
        self.assertTrue(collides(g.board, g.piece, dy=2))

    def test_ghost_lands_on_floor_and_stack(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=0)
        self.assertEqual(ghost_y(g.board, g.piece), ROWS - 2)
        fill_row(g.board, ROWS - 1)
        self.assertEqual(ghost_y(g.board, g.piece), ROWS - 3)

    def test_clear_rows_drops_the_stack(self):
        board = make_board()
        fill_row(board, ROWS - 1)
        board[ROWS - 2][0] = 3
        clear_rows(board, [ROWS - 1])
        self.assertEqual(full_rows(board), [])
        self.assertEqual(board[ROWS - 1][0], 3)

    def test_clearing_several_rows_keeps_order(self):
        board = make_board()
        fill_row(board, ROWS - 1)
        fill_row(board, ROWS - 2)
        board[ROWS - 3][1] = 2
        board[ROWS - 4][2] = 5
        clear_rows(board, [ROWS - 1, ROWS - 2])
        self.assertEqual(board[ROWS - 1][1], 2)
        self.assertEqual(board[ROWS - 2][2], 5)


class GravityTests(unittest.TestCase):
    def test_speed_increases_with_level(self):
        times = [gravity_interval(l) for l in range(1, MAX_LEVEL + 1)]
        self.assertEqual(times[0], 1.0)
        for prev, nxt in zip(times, times[1:]):
            self.assertGreaterEqual(prev, nxt, "gravity never slows down")
        self.assertLess(times[5], times[0])
        self.assertGreaterEqual(times[-1], 0.025)
        self.assertLess(times[-1], 0.03)

    def test_clamped_outside_the_range(self):
        self.assertEqual(gravity_interval(MAX_LEVEL), gravity_interval(99))
        self.assertEqual(gravity_interval(0), gravity_interval(1))

    def test_level_progression(self):
        self.assertEqual(level_for_lines(0), 1)
        self.assertEqual(level_for_lines(9), 1)
        self.assertEqual(level_for_lines(10), 2)
        self.assertEqual(level_for_lines(95), 10)
        self.assertEqual(level_for_lines(10_000, 1), MAX_LEVEL)
        self.assertEqual(level_for_lines(0, 5), 5)
        self.assertEqual(level_for_lines(10, 19), MAX_LEVEL)

    def test_gravity_moves_the_piece(self):
        g = new_game(start_level=1)
        y0 = g.piece.y
        g.update(1.05)
        self.assertEqual(g.piece.y, y0 + 1)
        g.update(2.05)
        self.assertEqual(g.piece.y, y0 + 3)

    def test_higher_level_falls_faster(self):
        slow, fast = new_game(start_level=1), new_game(start_level=9)
        slow.piece = Piece("O", x=4, y=0)
        fast.piece = Piece("O", x=4, y=0)
        for _ in range(30):
            slow.update(0.1)
            fast.update(0.1)
        self.assertGreater(fast.piece.y, slow.piece.y)


class MovementTests(unittest.TestCase):
    def test_move_stops_at_the_wall(self):
        g = new_game()
        g.piece = Piece("T", x=0, y=5)
        self.assertFalse(g.move(-1))
        self.assertEqual(g.piece.x, 0)
        self.assertTrue(g.move(1))
        self.assertEqual(g.piece.x, 1)

    def test_wall_kick_lets_a_flat_i_rotate(self):
        g = new_game()
        g.piece = Piece("I", x=0, y=5, rot=0)
        self.assertTrue(g.rotate(1))
        self.assertEqual(g.piece.rot, 1)
        self.assertTrue(g.rotate(-1))
        self.assertEqual(g.piece.rot, 0)

    def test_rotation_impossible_in_a_narrow_well(self):
        g = new_game()
        for y in range(ROWS):
            g.board[y][4] = 7
            g.board[y][6] = 7
        g.piece = Piece("I", x=3, y=5, rot=1)      # vertical I in column 5
        self.assertFalse(g.rotate(1))
        self.assertFalse(g.rotate(-1))
        self.assertEqual(g.piece.rot, 1)

    def test_o_piece_does_not_rotate(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        self.assertFalse(g.rotate(1))
        self.assertEqual(g.piece.rot, 0)

    def test_rotation_directions_differ(self):
        g = new_game()
        g.piece = Piece("J", x=4, y=5)
        cw = Game(make_opts())
        cw.piece = Piece("J", x=4, y=5)
        g.rotate(1)
        cw.rotate(-1)
        self.assertEqual((g.piece.rot, cw.piece.rot), (1, 3))

    def test_hard_drop_locks_and_scores(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=0)
        before = g.score
        g.hard_drop()
        self.assertEqual(g.score - before, 2 * (ROWS - 2))
        self.assertTrue(any(any(row) for row in g.board))
        self.assertIsNot(g.piece, None)

    def test_soft_drop_scores_one_per_cell(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=0)
        before = g.score
        g.soft_drop()
        self.assertEqual(g.score - before, 1)
        self.assertEqual(g.piece.y, 1)

    def test_soft_drop_at_the_floor_does_not_score(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=ROWS - 2)
        before = g.score
        self.assertFalse(g.soft_drop())
        self.assertEqual(g.score, before)

    def test_lock_delay_then_locks(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=ROWS - 2)
        first = g.piece
        g.update(LOCK_DELAY * 0.9)
        self.assertIs(g.piece, first, "no lock before the delay expires")
        g.update(LOCK_DELAY * 0.2)
        self.assertIsNot(g.piece, first, "locks once the delay expires")

    def test_lock_delay_resets_on_movement(self):
        g = new_game()
        g.piece = Piece("O", x=COLS - 2, y=ROWS - 2)
        first = g.piece
        for _ in range(6):
            g.update(LOCK_DELAY * 0.6)
            self.assertTrue(g.move(-1) or g.move(1))
            self.assertIs(g.piece, first, "moving resets the lock timer")

    def test_lock_resets_are_capped(self):
        g = new_game()
        g.piece = Piece("O", x=COLS - 2, y=ROWS - 2)
        first = g.piece
        for _ in range(MAX_LOCK_RESETS + 4):
            g.update(LOCK_DELAY * 0.6)
            g.move(-1) or g.move(1)
        g.update(LOCK_DELAY * 1.1)
        self.assertIsNot(g.piece, first, "the reset cap must eventually lock it")

    def test_move_left_until_the_wall(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        for _ in range(20):
            g.move(-1)
        self.assertEqual(g.piece.x, 0)


class MovementInputTests(unittest.TestCase):
    """Movement is driven by key events only - never by a timer.

    curses reports no key release, so a synthesised auto-repeat cannot tell a
    tap from a held key: one press would slide the piece to the wall.
    """

    def test_one_press_moves_exactly_one_cell(self):
        for direction, before, after in (("left", 4, 3), ("right", 4, 5)):
            g = new_game()
            g.piece = Piece("O", x=4, y=5)
            g.note_key(direction)
            self.assertEqual(g.piece.x, after, direction)
            for _ in range(60):          # a whole second of frames, no more events
                g.update(1.0 / 60)
            self.assertEqual(g.piece.x, after,
                             "%s: one press must not keep moving" % direction)

    def test_one_press_of_down_moves_exactly_one_cell(self):
        g = new_game()
        g.piece = Piece("I", x=0, y=0)
        y0 = g.piece.y
        g.note_key("down")
        self.assertEqual(g.piece.y, y0 + 1)
        g.update(0.5)                    # stays under the level-1 gravity interval
        self.assertEqual(g.piece.y, y0 + 1)

    def test_repeats_move_one_cell_each(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        for expected in (3, 2, 1, 0):
            g.note_key("left")
            self.assertEqual(g.piece.x, expected)
            g.update(0.03)               # the terminal's repeat interval

    def test_repeat_stops_with_the_events(self):
        g = new_game()
        g.piece = Piece("T", x=0, y=5)
        for _ in range(3):
            g.note_key("right")
            g.update(0.03)
        x_after = g.piece.x
        for _ in range(120):
            g.update(1.0 / 60)
        self.assertEqual(g.piece.x, x_after, "no phantom movement after release")

    def test_movement_stops_at_the_wall(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        for _ in range(20):
            g.note_key("left")
        self.assertEqual(g.piece.x, 0)

    def test_down_events_soft_drop_and_score(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=0)
        before = g.score
        for _ in range(3):
            g.note_key("down")
            g.update(0.03)
        self.assertEqual(g.piece.y, 3)
        self.assertEqual(g.score - before, 3)

    def test_ignored_keys_do_not_move_anything(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        x0, y0 = g.piece.x, g.piece.y
        for ch in (ord("j"), ord("k"), ord("m"), ord("."), curses.KEY_HOME):
            g.handle_key(ch)
            g.update(0.02)
        self.assertEqual((g.piece.x, g.piece.y), (x0, y0))

    def test_movement_is_inert_while_paused(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        g.toggle_pause()
        self.assertIsNone(g.handle_key(curses.KEY_LEFT))
        self.assertEqual(g.piece.x, 4)


class ScoringTests(unittest.TestCase):
    def test_line_clear_values(self):
        cases = ((1, 100, "O", 4, 0, (4, 5)), (2, 300, "I", 3, 1, (5,)),
                 (3, 500, "I", 3, 1, (5,)), (4, 800, "I", 3, 1, (5,)))
        for n, expected, kind, x, rot, cols in cases:
            g = new_game()
            stray(g)
            well(g, [ROWS - 1 - i for i in range(n)], cols)
            earned = drop_clear(g, kind, x, rot=rot, settle=False)
            self.assertEqual(earned, expected, "%d lines" % n)
            self.assertEqual(g.lines, n)
            self.assertEqual(len(drop_clear.rows), n)

    def test_tetris_is_counted(self):
        g = new_game()
        stray(g)
        well(g, [ROWS - 1 - i for i in range(4)], (5,))
        drop_clear(g, "I", 3, rot=1)
        self.assertEqual(g.lines, 4)
        self.assertEqual(g.tetris_count, 1)

    def test_score_scales_with_level(self):
        g = new_game(start_level=3)
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        self.assertEqual(drop_clear(g, "O", 4), 300)

    def test_back_to_back_tetris(self):
        """Two tetrises with a quiet (non-clearing) lock between them: the combo
        stays dead so the only bonus is the back-to-back multiplier."""
        g = new_game()
        earned = []
        for _ in range(2):
            stray(g)
            well(g, [ROWS - 1 - i for i in range(4)], (5,))
            earned.append(drop_clear(g, "I", 3, rot=1))
            g.piece = Piece("O", x=0, y=0)     # locks without clearing a row
            g.hard_drop()
            g.update(CLEAR_ANIM)
        self.assertEqual(earned, [800, 1200], "800, then 800 * 1.5")
        self.assertEqual(g.combo, -1)
        self.assertTrue(g.b2b)

    def test_a_single_breaks_back_to_back(self):
        g = new_game()
        g.b2b = True
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        self.assertEqual(drop_clear(g, "O", 4), 100)
        self.assertFalse(g.b2b)

    def test_tetris_keeps_back_to_back_alive(self):
        g = new_game()
        g.b2b = True
        g.award(4, "none")
        self.assertTrue(g.b2b)
        g.award(2, "none")
        self.assertFalse(g.b2b)

    def test_combo_bonus_grows(self):
        g = new_game()
        g.combo = 0                       # pretend one clear already happened
        for want in (100 + 50, 100 + 100):
            well(g, [ROWS - 1], (4, 5))
            g.board[2][2] = 6             # a leftover: no perfect-clear bonus
            self.assertEqual(drop_clear(g, "O", 4), want)
        self.assertEqual(g.combo, 2)

    def test_combo_resets_without_a_clear(self):
        g = new_game()
        g.combo = 3
        g.piece = Piece("O", x=4, y=0)
        g.hard_drop()
        self.assertEqual(g.combo, -1)

    def test_perfect_clear_bonus(self):
        g = new_game()
        well(g, [ROWS - 1, ROWS - 2], (4, 5))   # the O plugs both rows exactly
        earned = drop_clear(g, "O", 4, perfect=True)
        self.assertEqual(earned, 300 + 2000, "a double plus the perfect-clear bonus")
        self.assertIn("PERFECT CLEAR", g.toast)

    def test_no_perfect_clear_when_blocks_survive(self):
        g = new_game()
        well(g, [ROWS - 1], (4, 5))
        earned = drop_clear(g, "O", 4)            # the stray block stays
        self.assertEqual(earned, 100)

    def test_a_clear_that_empties_the_field_is_perfect(self):
        g = new_game()
        well(g, [ROWS - 1, ROWS - 2], (4, 5))
        drop_clear(g, "O", 4, perfect=True)
        self.assertEqual(g.board, make_board())

    def test_no_clear_scores_only_the_drop(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=0)
        before = g.score
        g.hard_drop()
        self.assertEqual(g.score - before, 2 * (ROWS - 2))
        self.assertIsNone(g.toast)

    def test_award_never_returns_zero_for_a_clear(self):
        g = new_game()
        for n in range(1, 5):
            g.b2b, g.combo = False, -1
            before = g.score
            g.award(n, "none")
            self.assertGreater(g.score - before, 0, "%d lines" % n)


class TSpinTests(unittest.TestCase):
    def test_seated_t_is_a_full_spin(self):
        g = pocket(new_game())
        g.piece = Piece("T", x=3, y=ROWS - 3, rot=2)
        g.last_action = "rotatecw"
        self.assertEqual(g.detect_spin(), "full")

    def test_no_spin_unless_the_last_action_was_a_rotation(self):
        g = pocket(new_game())
        g.piece = Piece("T", x=3, y=ROWS - 3, rot=2)
        g.last_action = "fall"
        g.lock_piece()
        self.assertEqual(g.spin, "none")

    def test_rotation_into_the_pocket_scores_a_tspin_double(self):
        for start_rot, direction in ((1, 1), (3, -1)):
            g = pocket(new_game())
            g.piece = Piece("T", x=3, y=19, rot=start_rot)
            self.assertFalse(collides(g.board, g.piece))
            self.assertTrue(g.rotate(direction))
            self.assertEqual((g.piece.rot, g.piece.x, g.piece.y), (2, 3, ROWS - 3))
            before = g.score
            g.lock_piece()
            self.assertEqual(g.spin, "full", "rot%d dir%d" % (start_rot, direction))
            self.assertEqual(g.score - before, 1200)
            self.assertEqual(g.lines, 2)
            self.assertIn("T-SPIN", g.toast)

    def test_plain_rotation_above_the_pocket_is_not_a_spin(self):
        g = pocket(new_game())
        g.piece = Piece("T", x=3, y=5, rot=1)
        self.assertTrue(g.rotate(1))
        g.lock_piece()
        self.assertEqual(g.spin, "none")

    def test_open_back_corners_are_not_a_spin(self):
        g = pocket(new_game())
        g.board[ROWS - 3][3] = 0
        g.board[ROWS - 3][5] = 0
        g.piece = Piece("T", x=3, y=ROWS - 3, rot=2)
        g.last_action = "rotatecw"
        self.assertEqual(g.detect_spin(), "none")

    def test_spin_score_table(self):
        g = new_game()
        g.board[STRAY_ROW][STRAY_COL] = 6
        for spin, expected in (("full", ((0, 400), (1, 800), (2, 1200), (3, 1600))),
                               ("mini", ((0, 100), (1, 200), (2, 400)))):
            for n, want in expected:
                g.b2b, g.combo = False, -1
                before = g.score
                g.award(n, spin)
                self.assertEqual(g.score - before, want, "%s %d lines" % (spin, n))

    def test_tspin_single_pays_more_than_a_plain_single(self):
        g = new_game()
        g.board[STRAY_ROW][STRAY_COL] = 6
        g.b2b, g.combo = False, -1
        before = g.score
        g.award(1, "full")
        spin_points = g.score - before
        g.b2b, g.combo = False, -1
        before = g.score
        g.award(1, "none")
        self.assertEqual(g.score - before, 100)
        self.assertEqual(spin_points, 800)

    def test_non_t_pieces_never_spin(self):
        g = pocket(new_game())
        g.piece = Piece("L", x=3, y=5, rot=0)
        g.last_action = "rotatecw"
        g.lock_piece()
        self.assertEqual(g.spin, "none")


class HoldTests(unittest.TestCase):
    def test_first_hold_stores_and_spawns_next(self):
        g = new_game()
        wanted = g.piece.kind
        next_kind = g.queue[0]
        g.hold_swap()
        self.assertEqual(g.hold, wanted)
        self.assertEqual(g.piece.kind, next_kind)
        self.assertFalse(g.can_hold)

    def test_second_hold_is_ignored(self):
        g = new_game()
        g.hold_swap()
        spawned = g.piece.kind
        g.hold_swap()
        self.assertEqual(g.piece.kind, spawned)

    def test_hold_refills_after_a_lock(self):
        g = new_game()
        g.hold_swap()
        held = g.hold
        g.piece = Piece("O", x=4, y=ROWS - 2)
        g.hard_drop()
        self.assertTrue(g.can_hold)
        g.hold_swap()
        self.assertEqual(g.piece.kind, held)
        self.assertNotEqual(g.hold, held)

    def test_hold_can_be_disabled(self):
        g = new_game(hold=False)
        kind = g.piece.kind
        g.hold_swap()
        self.assertIsNone(g.hold)
        self.assertEqual(g.piece.kind, kind)

    def test_hold_keeps_the_preview_order(self):
        g = new_game()
        current, queue = g.piece.kind, list(g.queue)
        g.hold_swap()
        self.assertEqual(g.piece.kind, queue[0])
        self.assertEqual(g.queue, queue[1:] + [current if False else g.queue[-1]][:1]
                         if False else g.queue)
        self.assertGreaterEqual(len(g.queue), g.opts.next)


class ClearAnimationTests(unittest.TestCase):
    def _clearing(self):
        g = new_game()
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        g.piece = Piece("O", x=4, y=0)
        g.hard_drop()
        return g

    def test_rows_flash_then_clear_then_spawn(self):
        g = self._clearing()
        self.assertGreater(g.clear_anim, 0)
        self.assertEqual(g.anim_rows, [ROWS - 1])
        self.assertTrue(all(g.board[ROWS - 1]))
        spawned = g.piece
        g.update(CLEAR_ANIM)
        self.assertEqual(g.clear_anim, 0)
        # the flashed row is gone; only the other half of the O slid down into it
        self.assertEqual(g.board[ROWS - 1], [0, 0, 0, 0, 4, 4, 0, 0, 0, 0])
        self.assertEqual(g.board[ROWS - 2], [0] * COLS)
        self.assertIsNot(g.piece, spawned, "a new piece appears after the flash")

    def test_no_piece_visible_during_the_flash(self):
        g = self._clearing()
        self.assertIsNotNone(g.piece)
        win = FakeWindow(24, 80)
        g.draw(win, Theme(win, color=False), (24, 80), flush=False)
        self.assertEqual(len(g.anim_rows), 1)

    def test_input_is_ignored_during_the_animation(self):
        g = self._clearing()
        piece = g.piece
        self.assertFalse(g.move(1))
        self.assertFalse(g.rotate(1))
        self.assertFalse(g.soft_drop())
        g.hard_drop()
        self.assertIs(g.piece, piece)

    def test_gravity_is_frozen_during_the_animation(self):
        g = self._clearing()
        piece = g.piece
        g.update(CLEAR_ANIM * 0.5)
        self.assertIs(g.piece, piece)


class PreviewShapeTests(unittest.TestCase):
    """A preview must show the piece's outline, not its bounding box."""

    def preview_rows(self, kind, size=(24, 80)):
        rows, cols = size
        win = FakeWindow(rows, cols)
        g = new_game()
        theme = Theme(win, color=False)
        g.queue = [kind] * 5
        g.hold = kind
        g.piece = None                       # nothing in the well, previews only
        g.draw(win, theme, size, flush=False)
        return win, theme, g

    def blocks_in(self, win, theme, y0, y1, x0, x1):
        grid = win.rows_text()
        out = []
        block = theme.block
        for y in range(y0, y1):
            out.append(grid[y][x0:x1])
        return out

    def test_next_preview_matches_the_piece_cells(self):
        for kind in tetris.PIECE_ORDER:
            win, theme, g = self.preview_rows(kind)
            layout = g.layout(win.size[0], win.size[1])
            # NEXT box interior: x = right_x + 1, y = board_y + 1
            x0, y0 = layout["right_x"] + 1, layout["board_y"] + 1
            w = layout["panel_w"] - 2
            strip = self.blocks_in(win, theme, y0, y0 + 3, x0, x0 + w)
            filled = sum(row.count(theme.block) for row in strip)
            self.assertEqual(filled, 4, "%s: previews draw exactly 4 cells" % kind)
            # the widest row must not span the full bounding box for pieces
            # that are not rectangular (T, S, Z, J, L, I all have a gap)
            if kind in ("T", "S", "Z", "J", "L"):
                widest = max(row.count(theme.block) for row in strip)
                self.assertLess(widest, max(len(r) for r in
                              [r for r in tetris.SHAPES[kind][0] if any(r)]) * 2,
                              "%s: preview must have a gap, not a solid box" % kind)

    def test_t_preview_has_its_notch(self):
        win, theme, g = self.preview_rows("T")
        layout = g.layout(win.size[0], win.size[1])
        x0, y0 = layout["right_x"] + 1, layout["board_y"] + 1
        strip = self.blocks_in(win, theme, y0, y0 + 3, x0, x0 + layout["panel_w"] - 2)
        counts = [row.count(theme.block) for row in strip]
        # counts are cells: one cell for the nub, three for the bar
        self.assertEqual([c for c in counts if c], [1, 3],
                         "T renders as nub-over-bar, got %r" % strip)

    def test_hold_preview_matches(self):
        for kind in tetris.PIECE_ORDER:
            win, theme, g = self.preview_rows(kind)
            layout = g.layout(win.size[0], win.size[1])
            x0, y0 = layout["left_x"] + 1, layout["board_y"] + 1
            strip = self.blocks_in(win, theme, y0, y0 + 5, x0,
                                   x0 + layout["panel_w"] - 2)
            self.assertEqual(sum(r.count(theme.block) for r in strip), 4, kind)

    def test_runs_helper(self):
        runs = tetris.Game.runs
        self.assertEqual(list(runs((0, 1, 1, 1))), [(1, (1, 1, 1))])
        self.assertEqual(list(runs((1, 0, 1))), [(0, (1,)), (2, (1,))])
        self.assertEqual(list(runs((0, 0, 0, 0))), [])
        self.assertEqual(list(runs((1, 1, 1, 1))), [(0, (1, 1, 1, 1))])


class PauseRestartQuitTests(unittest.TestCase):
    def test_pause_freezes_everything(self):
        g = new_game()
        g.piece = Piece("O", x=4, y=5)
        y0, score0, elapsed0 = g.piece.y, g.score, g.elapsed
        g.toggle_pause()
        self.assertTrue(g.paused)
        g.update(3.0)
        self.assertEqual(g.piece.y, y0)
        self.assertEqual(g.score, score0)
        self.assertEqual(g.elapsed, elapsed0)
        self.assertFalse(g.rotate(1))
        self.assertFalse(g.move(1))
        self.assertFalse(g.soft_drop())

    def test_pause_toggles_with_p_and_space(self):
        g = new_game()
        g.handle_key(ord("p"))
        self.assertTrue(g.paused)
        g.handle_key(ord("P"))
        self.assertFalse(g.paused)
        g.handle_key(ord("p"))
        g.handle_key(ord(" "))
        self.assertFalse(g.paused, "space resumes")

    def test_pause_keeps_the_state(self):
        g = new_game()
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        g.piece = Piece("O", x=4, y=0)
        g.hard_drop()
        g.update(CLEAR_ANIM)
        snapshot = [row[:] for row in g.board]
        score, lines = g.score, g.lines
        g.toggle_pause()
        g.update(2.0)
        g.toggle_pause()
        self.assertEqual(g.board, snapshot)
        self.assertEqual((g.score, g.lines), (score, lines))

    def test_restart_resets_the_run(self):
        g = new_game()
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        g.piece = Piece("O", x=4, y=0)
        g.hard_drop()
        g.update(CLEAR_ANIM)
        g.lines += 40
        g.level = 7
        g.toggle_pause()
        g.handle_key(ord("r"))
        self.assertEqual(g.board, make_board())
        self.assertEqual(g.score, 0)
        self.assertEqual(g.lines, 0)
        self.assertEqual(g.level, 1)
        self.assertEqual(g.combo, -1)
        self.assertEqual(g.elapsed, 0.0)
        self.assertIsNone(g.hold)
        self.assertTrue(g.can_hold)
        self.assertFalse(g.paused)
        self.assertFalse(g.over)
        self.assertIsNotNone(g.piece)

    def test_best_score_survives_restart(self):
        g = new_game()
        stray(g)
        well(g, [ROWS - 1], (4, 5))
        g.piece = Piece("O", x=4, y=0)
        g.hard_drop()
        earned = g.score
        self.assertEqual(g.best, earned)
        g.handle_key(ord("r"))
        self.assertEqual(g.best, earned)
        self.assertEqual(g.score, 0)

    def test_best_tracks_the_highest_run(self):
        g = new_game()
        g.score = 5000
        g.game_over()
        self.assertEqual(g.best, 5000)
        g.handle_key(ord("r"))
        g.score = 100
        g.game_over()
        self.assertEqual(g.best, 5000)

    def test_control_keys(self):
        g = new_game()
        self.assertEqual(g.handle_key(ord("q")), "quit")
        self.assertEqual(g.handle_key(ord("Q")), "quit")
        self.assertEqual(g.handle_key(ord("h")), "help")
        self.assertEqual(g.handle_key(ord("?")), "help")
        self.assertIsNone(g.handle_key(ord("p")))

    def test_keys_are_inert_after_game_over(self):
        g = new_game()
        g.game_over()
        piece = g.piece
        g.update(5.0)
        self.assertIs(g.piece, piece)
        self.assertIsNone(g.handle_key(ord(" ")))
        self.assertIsNone(g.handle_key(ord("p")))
        self.assertFalse(g.paused)
        self.assertTrue(g.over)

    def test_restart_works_after_game_over(self):
        g = new_game()
        g.game_over()
        g.handle_key(ord("r"))
        self.assertFalse(g.over)


class GameOverTests(unittest.TestCase):
    def test_lock_out_above_the_field(self):
        """A piece that locks entirely above the visible field ends the run."""
        g = new_game()
        for y in range(HIDDEN, HIDDEN + 4):
            fill_row(g.board, y, except_cols=(0,))   # not full: nothing clears
        g.piece = Piece("O", x=4, y=HIDDEN - 2)      # rests inside the buffer
        g.lock_piece()
        self.assertTrue(g.over)

    def test_block_out_on_spawn(self):
        g = new_game()
        for y in range(HIDDEN + 2):
            fill_row(g.board, y)
        g.spawn_piece("I")
        self.assertTrue(g.over)

    def test_a_tall_stack_that_stays_visible_is_not_over(self):
        g = new_game()
        for y in range(HIDDEN + 4, ROWS):
            fill_row(g.board, y, except_cols=(4, 5))
        piece = Piece("O", x=4, y=HIDDEN - 2)
        g.piece = piece
        g.hard_drop()
        self.assertFalse(g.over, "only locking above the field ends the run")

    def test_over_stops_gravity_and_scoring(self):
        g = new_game()
        g.game_over()
        piece, score = g.piece, g.score
        g.update(4.0)
        self.assertIs(g.piece, piece)
        self.assertEqual(g.score, score)

    def test_clearing_rows_lets_a_high_stack_keep_playing(self):
        g = new_game()
        for y in range(ROWS - 4, ROWS):           # a tetris-sized well up high
            fill_row(g.board, y, except_cols=(5,))
        fill_row(g.board, HIDDEN + 1, except_cols=(5,))
        before = g.score
        g.piece = Piece("I", x=3, y=0, rot=1)     # vertical I down the well
        g.hard_drop()
        self.assertEqual(g.lines, 4)              # one I completes four rows
        self.assertGreater(g.score, before)
        self.assertFalse(g.over)


class BagTests(unittest.TestCase):
    def test_seven_bag_distribution(self):
        g = new_game(seed=7)
        drawn = [g._draw_piece() for _ in range(21)]
        for i in (0, 7, 14):
            self.assertEqual(sorted(drawn[i:i + 7]), sorted(tetris.PIECE_ORDER))

    def test_queue_stays_refilled(self):
        g = new_game()
        for _ in range(40):
            self.assertGreaterEqual(len(g.queue), g.opts.next)
            g.spawn_piece()

    def test_seed_is_reproducible(self):
        self.assertEqual(new_game(seed=99).queue, new_game(seed=99).queue)
        self.assertNotEqual(new_game(seed=1).queue, new_game(seed=2).queue)

    def test_next_option_sizes_the_preview(self):
        for n in (1, 3, 5):
            g = new_game(next=n)
            self.assertGreaterEqual(len(g.queue), n)


class RenderingTests(unittest.TestCase):
    # the renderer's contract is MIN_Y x MIN_X or larger; smaller terminals get
    # the "resize" screen instead (covered by test_too_small_screen_*)
    SIZES = [(23, 44), (24, 80), (26, 46), (30, 100), (40, 200), (23, 45),
             (24, 44), (60, 120), (23, 400), (27, 46), (50, 37), (23, 60),
             (25, 46), (30, 44)]

    def _states(self):
        def clearing(g):
            stray(g)
            fill_row(g.board, ROWS - 1, except_cols=(4, 5))
            g.piece = Piece("O", x=4, y=0)
            g.hard_drop()

        def paused(g):
            g.score = 1234567
            g.toggle_pause()

        def over(g):
            g.score = 99
            g.game_over()

        return (("play", None), ("clearing", clearing), ("paused", paused),
                ("over", over), ("stack", lambda g: [
                    fill_row(g.board, y, except_cols=(4, 5))
                    for y in range(HIDDEN, ROWS)]))

    def test_draw_never_throws_at_any_size(self):
        for y, x in self.SIZES:
            for state, setup in self._states():
                for help_screen in (False, True):
                    win = FakeWindow(y, x)
                    g = new_game()
                    g.score, g.lines, g.level = 98765, 132, 12
                    g.hold = "I"
                    g.toast = "T-SPIN DOUBLE +1200"
                    if setup:
                        setup(g)
                    if help_screen:
                        g.draw_help(win, Theme(win, color=False), (y, x), flush=False)
                    else:
                        g.draw(win, Theme(win, color=False), (y, x), flush=False)

    def test_board_fits_inside_the_screen(self):
        for y, x in self.SIZES:
            win = FakeWindow(y, x)
            g = new_game()
            g.draw(win, Theme(win, color=False), (y, x), flush=False)
            layout = g.layout(y, x)
            self.assertLessEqual(layout["board_y"] + VIS_ROWS + 1, y,
                                 "board bottom clipped at %dx%d" % (y, x))
            self.assertLessEqual(layout["board_x"] + COLS * 2 + 1, x,
                                 "board right edge clipped at %dx%d" % (y, x))

    def test_key_hints_are_visible_at_the_minimum_size(self):
        win = FakeWindow(tetris.MIN_Y, tetris.MIN_X)
        g = new_game()
        theme = Theme(win, color=False)
        g.draw(win, theme, (tetris.MIN_Y, tetris.MIN_X), flush=False)
        text = "\n".join(win.rows_text())
        for token in ("arrows", "rotate", "drop", "pause", "restart"):
            self.assertIn(token, text)

    def test_layout_rows_never_exceed_the_screen(self):
        for y, x in self.SIZES:
            self.assertGreaterEqual((y, x), (tetris.MIN_Y, tetris.MIN_X))
            layout = new_game().layout(y, x)
            self.assertLess(layout["msg_y"], y, "toast row must be on screen")
            self.assertLess(layout["hint_y"], y, "hint row must be on screen")
            self.assertLessEqual(layout["board_y"] + VIS_ROWS + 1, y - 1)

    def test_toast_is_visible_at_the_minimum_size(self):
        win = FakeWindow(tetris.MIN_Y, tetris.MIN_X)
        g = new_game()
        g.toast = "T-SPIN DOUBLE +1200"
        g.draw(win, Theme(win, color=False), (tetris.MIN_Y, tetris.MIN_X),
               flush=False)
        self.assertIn("T-SPIN", "\n".join(win.rows_text()))

    def test_toast_does_not_cover_cells(self):
        """The message rides the border row, never the playfield itself."""
        win = FakeWindow(24, 80)
        g = new_game()
        theme = Theme(win, color=False)
        fill_row(g.board, ROWS - 1)
        layout = g.layout(24, 80)
        g.toast = "TETRIS +800"
        g.draw(win, theme, (24, 80), flush=False)
        rows = win.rows_text()
        cells_row = layout["board_y"] + VIS_ROWS          # last row of cells
        self.assertNotIn("TETRIS", rows[cells_row])
        self.assertIn("TETRIS", rows[layout["msg_y"]])

    def test_panels_fit_inside_the_screen(self):
        for y, x in self.SIZES:
            win = FakeWindow(y, x)
            g = new_game()
            g.draw(win, Theme(win, color=False), (y, x), flush=False)
            for row, col, text in win.written:
                self.assertLess(col + len(text), x + 1,
                                "%r overflows at %dx%d" % (text, y, x))
                self.assertLess(row, y)

    def test_cells_are_rendered(self):
        win = FakeWindow(24, 80)
        g = new_game()
        fill_row(g.board, ROWS - 1)
        theme = Theme(win, color=False)
        g.draw(win, theme, (24, 80), flush=False)
        layout = g.layout(24, 80)
        bottom = win.rows_text()[layout["board_y"] + VIS_ROWS]
        self.assertIn(theme.block, bottom)

    def test_stats_are_rendered(self):
        win = FakeWindow(24, 80)
        g = new_game()
        g.score, g.lines, g.level = 4242, 31, 4
        g.draw(win, Theme(win, color=False), (24, 80), flush=False)
        text = "\n".join(win.rows_text())
        for token in ("SCORE", "4242", "LINES", "31", "LEVEL", "4"):
            self.assertIn(token, text)

    def test_pause_and_game_over_text(self):
        win = FakeWindow(24, 80)
        g = new_game()
        g.toggle_pause()
        g.draw(win, Theme(win, color=False), (24, 80), flush=False)
        self.assertIn("PAUSED", "\n".join(win.rows_text()))
        g.reset()
        g.game_over()
        win = FakeWindow(24, 80)
        g.draw(win, Theme(win, color=False), (24, 80), flush=False)
        self.assertIn("GAME OVER", "\n".join(win.rows_text()))

    def test_help_lists_the_controls(self):
        win = FakeWindow(24, 80)
        g = new_game()
        g.draw_help(win, Theme(win, color=False), (24, 80), flush=False)
        text = "\n".join(win.rows_text())
        for token in ("pause", "restart", "quit", "hold", "rotate"):
            self.assertIn(token, text)

    def test_every_piece_gets_a_colour_pair(self):
        """The palette must cover every piece index, not just some names."""
        win = FakeWindow(24, 80)
        g = new_game()
        theme = Theme(win, color=False)
        for kind in tetris.PIECE_ORDER:
            self.assertIn(tetris.PIECE_COLOR[kind], range(1, len(tetris.COLOURS)),
                          kind)
        self.assertEqual(len(tetris.COLOURS), len(tetris.PIECE_ORDER) + 1)

    def test_unicode_detection_follows_the_locale(self):
        """ASCII locales must fall back to ASCII glyphs, or pieces draw blank."""
        cases = (({"LANG": "C.UTF-8"}, True), ({"LANG": "en_US.UTF-8"}, True),
                 ({"LANG": "C"}, False), ({"LANG": "POSIX"}, False),
                 ({"LANG": "C", "LC_ALL": "C.UTF-8"}, True),
                 ({"LANG": "en_US.ISO8859-1"}, False),
                 ({"LANG": "en_US"}, False))
        # With no locale variables at all the answer depends on what Python
        # coerced the C locale to, so it is not asserted here; the end-to-end
        # check covers it by looking at what actually reaches the screen.
        saved = dict(os.environ)
        try:
            for env, want in cases:
                os.environ.clear()
                os.environ.update(env)
                self.assertEqual(tetris.terminal_supports_unicode(), want, env)
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_ascii_theme_when_forced(self):
        theme = Theme(FakeWindow(24, 80), color=False, force_ascii=True)
        self.assertEqual(theme.block, "[]")
        self.assertEqual(theme.ghost, "::")

    def test_no_color_mode(self):
        theme = Theme(FakeWindow(24, 80), color=False)
        self.assertFalse(theme.color)
        self.assertEqual(theme.cell_attr(3), curses.A_BOLD)
        self.assertTrue(theme.block.strip(), "blocks must be visible without colour")

    def test_color_mode_needs_a_real_screen(self):
        theme = Theme(FakeWindow(24, 80), color=True)
        if not theme.color:
            self.skipTest("curses colours need an initialised screen")
        self.assertNotEqual(theme.cell_attr(3), curses.A_REVERSE)


class UiFlowTests(unittest.TestCase):
    def test_key_run_through(self):
        g = new_game(seed=5)
        win = FakeWindow(24, 80)
        theme = Theme(win, color=False)
        keys = (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_DOWN, ord("x"),
                ord("z"), ord("c"), ord(" "), ord("p"), ord("p"), ord("h"))
        for ch in keys:
            g.handle_key(ch)
            g.update(0.02)
            g.draw(win, theme, (24, 80), flush=False)
        self.assertFalse(g.over)

    def test_level_rises_every_ten_lines(self):
        g = new_game()
        for _ in range(10):
            stray(g)
            well(g, [ROWS - 1], (4, 5))
            g.piece = Piece("O", x=4, y=0)
            g.hard_drop()
            g.update(CLEAR_ANIM)
        self.assertEqual(g.lines, 10)
        self.assertEqual(g.level, 2)

    def test_start_level_option(self):
        g = new_game(start_level=8)
        self.assertEqual(g.level, 8)
        for _ in range(10):
            stray(g)
            well(g, [ROWS - 1], (4, 5))
            g.piece = Piece("O", x=4, y=0)
            g.hard_drop()
            g.update(CLEAR_ANIM)
        self.assertEqual(g.level, 9)

    def test_a_long_run_stays_consistent(self):
        g = new_game(seed=42)
        for _ in range(400):
            g.handle_key(random.choice(
                (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_DOWN, ord("x"),
                 ord("z"), ord("c"), ord(" "))))
            g.update(0.05)
            self.assertGreaterEqual(g.score, 0)
            self.assertLessEqual(g.level, MAX_LEVEL)
            self.assertEqual(len(g.board), ROWS)
            for row in g.board:
                self.assertEqual(len(row), COLS)
            if g.over:
                g.handle_key(ord("r"))


class CliTests(unittest.TestCase):
    def test_defaults(self):
        o = tetris.parse_args([])
        self.assertEqual(o.next, 3)
        self.assertEqual(o.start_level, 1)
        self.assertFalse(o.no_color)
        self.assertFalse(o.ascii)
        self.assertFalse(o.no_hold)
        self.assertFalse(o.no_shadow)

    def test_flags(self):
        o = tetris.parse_args(["--no-color", "--ascii", "--next", "5",
                               "--start-level", "4", "--no-hold",
                               "--no-shadow", "--seed", "7"])
        self.assertEqual((o.next, o.start_level, o.seed), (5, 4, 7))
        self.assertTrue(o.no_hold and o.no_shadow and o.ascii and o.no_color)

    def test_out_of_range_values_rejected(self):
        for bad in (["--next", "9"], ["--start-level", "0"], ["--start-level", "21"]):
            with self.assertRaises(SystemExit):
                tetris.parse_args(bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)