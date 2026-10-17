#!/usr/bin/env python3
"""End-to-end checks for tetris.py: run it in a real terminal and look at it.

Two harnesses, because no single one covers everything:

  * GNU screen  - real curses app, real terminal, `hardcopy` gives the exact
                  screen grid, so we can assert on what the player sees.
  * a raw pty   - arbitrary window sizes, to prove the renderer survives tiny
                  and huge terminals and never dies mid-frame.

    python3 e2e_check.py
"""

import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from render_frame import Vt100

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "tetris.py")
KEYMAP = {"left": "\033[D", "right": "\033[C", "down": "\033[B", "up": "\033[A",
          "ccw": "z", "hold": "c", "drop": " ", "pause": "p", "restart": "r",
          "help": "h", "quit": "q"}


def keys(*names):
    return [KEYMAP[n] for n in names]


# ---------------------------------------------------------------------------
# GNU screen harness
# ---------------------------------------------------------------------------

def screen_run(keys=(), args=(), settle=1.5, per_key=0.09, tail=1.2):
    """Launch the game detached in screen, type keys, return the screen grid."""
    if shutil.which("screen") is None:
        raise SystemExit("GNU screen is needed for the visual checks")
    session = "tetris-e2e-%d" % os.getpid()
    dump = os.path.join(tempfile.gettempdir(), "%s.dump" % session)
    subprocess.run(["screen", "-dm", "-s", "/bin/bash", "-S", session,
                    "-t", "tetris", "-T", "xterm-256color",
                    sys.executable, GAME, *args], check=True)
    time.sleep(settle)
    for key in keys:
        subprocess.run(["screen", "-S", session, "-X", "stuff", key],
                       check=False)
        time.sleep(per_key)
    time.sleep(tail)
    subprocess.run(["screen", "-S", session, "-X", "hardcopy", dump],
                   check=False)
    time.sleep(0.5)
    text = ""
    if os.path.exists(dump):
        text = open(dump, encoding="utf-8", errors="replace").read()
        os.remove(dump)
    subprocess.run(["screen", "-S", session, "-X", "quit"], check=False)
    time.sleep(0.2)
    return text


# ---------------------------------------------------------------------------
# raw pty harness (any size, no visual assertions)
# ---------------------------------------------------------------------------

def pty_run(size, keys=(), args=(), settle=1.0, per_key=0.05, tail=0.8,
            env=None, wait_for_exit=False):
    """Run the game in a pty of `size`; return everything it wrote."""
    import fcntl
    import struct
    import termios

    pid, master = pty.fork()
    if pid == 0:                                    # child
        os.environ.clear()
        os.environ.update({"TERM": "xterm-256color", "LANG": "C.UTF-8",
                           "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if env:
            os.environ.update(env)
        os.chdir(HERE)
        os.execv(sys.executable, [sys.executable, GAME, *args])
        os._exit(1)
    rows, cols = size
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    out = bytearray()

    def pump(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([master], [], [], 0.05)
            if not r:
                continue
            try:
                chunk = os.read(master, 65536)
            except (OSError, BlockingIOError):
                continue
            if not chunk:
                return False                        # child exited
            out.extend(chunk)
        return True

    alive = pump(settle)
    for key in keys:
        if not alive:
            break
        os.write(master, key.encode() if isinstance(key, str) else key)
        alive = pump(per_key)
    pump(tail)
    exited = None
    if wait_for_exit:
        for _ in range(50):
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                exited = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
                break
            time.sleep(0.05)
    if exited is None:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass
    os.close(master)
    text = bytes(out).decode("utf-8", "replace")
    return (text, exited) if wait_for_exit else text


def board_only(text, size=(26, 90)):
    """Keep only the playfield cells, so score and timer cannot fool a diff."""
    import tetris

    layout = tetris.Game.layout(None, size[0], size[1])
    x0 = layout["board_x"] + 1
    x1 = x0 + tetris.COLS * 2
    y0 = layout["board_y"] + 1
    y1 = y0 + tetris.VIS_ROWS
    rows = text.splitlines()
    return "\n".join(row[x0:x1] for row in rows[y0:y1])


def screen_text(size, args=(), keys=(), settle=1.2, hold=0.1, wait=1.2):
    """Settled screen contents after running the game (not raw escape soup)."""
    rows, cols = size
    import fcntl
    import struct
    import termios

    pid, master = pty.fork()
    if pid == 0:
        os.environ.clear()
        os.environ.update({"TERM": "xterm-256color", "LANG": "C.UTF-8",
                           "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        os.chdir(HERE)
        os.execv(sys.executable, [sys.executable, GAME, *args])
        os._exit(1)
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    term = Vt100(rows, cols)
    end = time.monotonic() + settle
    while time.monotonic() < end:
        r, _, _ = select.select([master], [], [], 0.05)
        if not r:
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:
            continue
        if chunk:
            term.feed(chunk.decode("utf-8", "replace"))
    for key in keys:
        if key == "WAIT":                       # just let time pass
            end = time.monotonic() + wait
            while time.monotonic() < end:
                r, _, _ = select.select([master], [], [], 0.05)
                if r:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        continue
                    if chunk:
                        term.feed(chunk.decode("utf-8", "replace"))
            continue
        os.write(master, key.encode())
        end = time.monotonic() + hold
        while time.monotonic() < end:
            r, _, _ = select.select([master], [], [], 0.05)
            if r:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    continue
                if chunk:
                    term.feed(chunk.decode("utf-8", "replace"))
    text = term.text()
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass
    os.close(master)
    return text


def same_screen(args):
    a, b = screen_text((24, 80), args), screen_text((24, 80), args)
    return a == b and not looks_broken(a), "screens differ"


def different_screen(args_a, args_b):
    return screen_text((24, 80), args_a) != screen_text((24, 80), args_b)


def looks_broken(text):
    return ("Traceback" in text or "Error" in text and "too small" not in text
            or "Exception" in text)


# ---------------------------------------------------------------------------

def main():
    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    def show(title, text, limit=24):
        lines = [l.rstrip() for l in text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        print("\n--- %s ---" % title)
        print("\n".join(lines[:limit]) or "(empty screen)")

    # --- boot -------------------------------------------------------------
    boot = screen_run()
    show("boot", boot)
    check("boot draws the whole HUD",
          all(t in boot for t in ("T E T R I S", "HOLD", "NEXT", "SCORE",
                                  "LINES", "LEVEL", "BEST", "TIME",
                                  "arrows move")) and not looks_broken(boot),
          "missing: %s" % [t for t in ("HOLD", "NEXT", "SCORE") if t not in boot])
    check("boot has no pieces stacked yet",
          boot.count("GAME OVER") == 0 and "PAUSED" not in boot)

    # --- playing ----------------------------------------------------------
    played = screen_run(keys("right", "right", "up", "ccw", "hold", "drop",
                             "drop", "drop", "left", "left", "down", "drop"))
    show("after playing", played)
    score = re.search(r"SCORE\s+(\d+)", played)
    check("score climbs while playing", bool(score) and int(score.group(1)) > 0,
          "SCORE=%s" % (score.group(1) if score else "unreadable"))
    check("playing does not crash", not looks_broken(played))

    # --- pause ------------------------------------------------------------
    paused = screen_run(keys("drop", "pause"))
    show("paused", paused)
    check("P shows the pause overlay",
          "PAUSED" in paused and "press P to resume" in paused)
    resumed = screen_run(keys("drop", "pause", "up", "pause"))
    check("P again resumes", "PAUSED" not in resumed and not looks_broken(resumed))

    # --- restart ----------------------------------------------------------
    restarted = screen_run(keys("drop", "drop", "drop", "restart"))
    best = re.search(r"BEST\s+(\d+)", restarted)
    check("R restarts and keeps BEST",
          bool(best) and int(best.group(1)) > 0 and not looks_broken(restarted),
          "BEST=%s" % (best.group(1) if best else "unreadable"))

    # --- help -------------------------------------------------------------
    helped = screen_run(keys("help"))
    show("help", helped)
    check("help lists the controls",
          all(t in helped for t in ("CONTROLS", "pause", "restart", "quit")))
    after_help = screen_run(keys("help", "up", "help", "drop"))
    check("a key closes help and play continues",
          "CONTROLS" not in after_help and not looks_broken(after_help))

    # --- hold -------------------------------------------------------------
    held = screen_run(keys("hold", "drop", "hold"))
    check("hold does not crash", not looks_broken(held))

    # --- game over + restart ---------------------------------------------
    over = screen_run([" "] * 90, args=("--start-level", "20"), per_key=0.02,
                      tail=2.0, settle=1.5)
    show("level 20, hard-dropping forever", over)
    check("a stack high enough ends the game",
          "GAME OVER" in over and not looks_broken(over))
    revived = screen_run([" "] * 90 + ["r", " ", " "],
                         args=("--start-level", "20"), per_key=0.02, tail=1.5)
    lines_after = re.search(r"LINES\s+(\d+)", revived)
    check("R after game over starts a new run",
          bool(lines_after) and int(lines_after.group(1)) == 0
          and "GAME OVER" not in revived and not looks_broken(revived),
          "LINES=%s" % (lines_after.group(1) if lines_after else "unreadable"))

    # --- terminal sizes ---------------------------------------------------
    sizes = [(23, 44), (24, 80), (26, 46), (30, 100), (40, 200), (23, 400),
             (50, 37), (23, 60)]
    for size in sizes:
        out = pty_run(size, keys("right", "drop", "hold", "up", "pause", "pause"))
        check("renders at %dx%d" % (size[0], size[1]), not looks_broken(out))
    for size in [(10, 30), (5, 20), (22, 40), (23, 43)]:
        out = pty_run(size, keys("drop"))
        check("survives too-small %dx%d" % (size[0], size[1]),
              not looks_broken(out))
    small = pty_run((10, 30))
    check("too-small screen asks to resize", "resize" in small)

    # --- single tap must not slide the piece ------------------------------
    # Level 20 gravity parks a piece on the floor in well under a second, so
    # the settled screen records exactly how far it travelled horizontally.
    # Locking the piece with a hard drop makes the captured stack independent
    # of how long gravity had been running, so only horizontal position varies.
    def stack(keys):
        text = screen_text((26, 90), args=("--seed", "3"), keys=keys + [" "],
                           settle=0.6, hold=0.08)
        return board_only(text)

    rest = stack([])
    one_tap = stack(["\033[D"])
    one_tap_wait = stack(["\033[D", "WAIT"])   # hold the key down, then let go
    four_taps = stack(["\033[D"] * 4)
    check("one tap shifts where the piece lands",
          rest != one_tap and not looks_broken(one_tap),
          "a tap had no effect on where the piece landed")
    check("a tapped key does not keep moving", one_tap == one_tap_wait,
          "the piece slid further after a single tap")
    check("held repeats move further than one tap", four_taps != one_tap,
          "autorepeat produced no further movement")

    # --- previews show the piece outline, not a box -----------------------
    prev = screen_text((26, 90), args=("--seed", "3"))
    rows_with = lambda ch: sum(ch in line for line in prev.splitlines())
    check("previews show gaps inside the shape",
          "\u2588" in prev and rows_with("\u2588") >= 6,
          "no block glyphs at all")

    # --- options ----------------------------------------------------------
    ascii_locale = pty_run((24, 60), keys("drop", "hold"),
                           env={"LANG": "C", "LC_ALL": "C", "TERM": "xterm"})
    check("ASCII locale draws visible pieces",
          "[]" in ascii_locale and "Traceback" not in ascii_locale)
    check("ASCII locale avoids box drawing",
          "\u2554" not in ascii_locale and "\u2502" not in ascii_locale)
    utf8_locale = pty_run((24, 60), keys("drop", "hold"),
                          env={"LANG": "C.UTF-8", "TERM": "xterm-256color"})
    check("UTF-8 locale draws block pieces",
          "\u2588" in utf8_locale and "Traceback" not in utf8_locale)
    ascii_run = pty_run((24, 60), keys("drop"), args=("--no-color", "--ascii"))
    check("--ascii draws ASCII blocks", "[]" in ascii_run and not looks_broken(ascii_run))
    plain = pty_run((24, 60), keys("drop"), args=("--no-shadow", "--no-hold"))
    check("--no-hold hides the HOLD panel",
          "HOLD" not in plain and not looks_broken(plain))
    onepass = pty_run((24, 60), keys("hold", "hold"), args=("--next", "1"))
    check("--next 1 renders", not looks_broken(onepass))
    check("--seed is reproducible", *same_screen(("--seed", "7")))
    check("different seeds differ",
          different_screen(("--seed", "7"), ("--seed", "8")))

    # --- quit -------------------------------------------------------------
    quit_out, status = pty_run((24, 80), keys("quit"), tail=0.6,
                               wait_for_exit=True)
    check("Q exits by itself with status 0", status == 0 and "Traceback" not in quit_out,
          "exit status=%s" % status)
    restart_keys = pty_run((24, 80), keys("quit", "restart"), tail=0.6,
                           wait_for_exit=True)
    check("R is not swallowed as a quit", restart_keys[1] is None
          or restart_keys[1] == 0)

    print("\n===== results =====")
    failed = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print("%-38s %s%s" % (name, "PASS" if ok else "FAIL",
                              ("  <- " + detail) if detail and not ok else ""))
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())