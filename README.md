# Tetris

A terminal Tetris in one Python file. Nothing to install, nothing to build:

```sh
./tetris.py          # or: python3 tetris.py
```

Requires Python 3.8+ on Linux. It uses only the standard library, and `curses`
ships with CPython on Linux, so there are no dependencies to fetch.

Minimum terminal size is 44 columns by 23 rows (24 rows show the title too).
Smaller terminals get a "resize" message instead of a broken layout.

## Controls

| Key                | Action                          |
| ------------------ | ------------------------------- |
| Left / Right, A / D | move                           |
| Down, S            | soft drop (+1 per cell)         |
| Space, Enter       | hard drop (+2 per cell)         |
| Up, X, W           | rotate clockwise                |
| Z                  | rotate counter-clockwise        |
| C, Tab             | hold / swap piece (once per drop) |
| P                  | pause and resume                |
| R                  | restart                         |
| H or ?             | controls and scoring            |
| Q                  | quit                            |

Holding a movement key repeats at your terminal's own key-repeat rate, which is
what you configured it for. The game never invents repeats of its own: a
terminal reports a press but not a release, so synthesised repeats cannot tell a
tap from a held key and a single press would slide the piece across the field.
Desktop terminals repeat arrow keys by default; if yours does not, tap the key
once per cell you want the piece to move.

## Options

```
--no-color        monochrome rendering
--ascii           ASCII glyphs only (no box drawing or block characters)
--next N          number of next-piece previews, 1-5 (default 3)
--start-level N   start at level N, 1-20 (default 1)
--no-hold         disable the HOLD slot
--no-shadow       disable the ghost piece showing where a piece will land
--seed N          seed the randomiser, for repeatable piece sequences
```

Glyphs follow the locale: under an ASCII locale (`LANG=C`) the game draws with
`[]` and `+--+` because curses silently discards non-ASCII bytes there and
pieces would otherwise be invisible. `--ascii` forces it either way.

## Rules

Standard 10x20 field, 7-bag randomiser (every seven pieces contains one of each
tetromino), SRS rotation with wall kicks, hold, ghost piece, lock delay of 0.5 s
with up to 15 move/rotate resets, and game over when a piece locks entirely
above the visible field.

Gravity follows the guideline curve: 1.0 s per row at level 1, 0.79 s at level
2, 0.36 s at level 5, 0.06 s at level 10, and it bottoms out at 0.025 s from
level 15 onwards. The level rises every 10 lines, up to level 20.

Scoring, all multiplied by the current level:

| Event                    | Points |
| ------------------------ | ------ |
| 1 / 2 / 3 lines          | 100 / 300 / 500 |
| TETRIS (4 lines)         | 800    |
| T-spin (no lines)        | 400    |
| T-spin single / double / triple | 800 / 1200 / 1600 |
| T-spin mini (0 / 1 / 2 lines)  | 100 / 200 / 400 |
| Back-to-back difficult clear   | x1.5   |
| Combo                    | +50 per step in the chain |
| Perfect clear            | +2000  |

A T-spin is recognised with the 3-corner rule: three of the four cells diagonal
to the T are occupied and the piece was rotated into place as its last action.
The fifth wall-kick slot promotes a mini to a full spin.

## Tests

```sh
python3 -m unittest test_tetris -v   # 108 logic tests, no terminal needed
python3 e2e_check.py                 # 39 checks driving the real game
```

`test_tetris.py` drives the game model directly with a fake window that enforces
screen bounds, so the renderer is checked for clipping as well as for rules.

`e2e_check.py` runs the actual program: once inside GNU `screen` (whose
`hardcopy` gives the exact screen contents, so it can assert on what a player
sees) and once inside a raw pty at many terminal sizes and locales. It reports
`GNU screen is needed for the visual checks` if `screen` is missing.

`render_frame.py` is a debugging aid rather than a test: it runs the game in a
pty, types a key script, and prints the resulting screen as text.

```sh
python3 render_frame.py 28 90 "lllru_s_d_dl_z_s"   # l r = move, s = hard drop
```

## Files

| File             | Purpose                                            |
| ---------------- | -------------------------------------------------- |
| `tetris.py`      | the game; standalone, executable, no dependencies  |
| `test_tetris.py` | unit tests for rules, scoring, layout, input |
| `e2e_check.py`   | end-to-end checks against the running game         |
| `render_frame.py`| prints a rendered frame for eyeballing             |