#!/usr/bin/env python3
"""Render a real tetris.py frame: run it in a pty, feed keys, emulate the screen.

    python3 render_frame.py [rows] [cols] [key script]

Key script uses letters: l=left r=right d=down u=rotate-up z=ccw c=hold
space=hard drop p=pause h=help. Default feeds a short scripted opening.
"""

import os
import pty
import re
import select
import signal
import struct
import sys
import termios
import fcntl
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = {"l": "\033[D", "r": "\033[C", "d": "\033[B", "u": "\033[A", "z": "z",
        "c": "c", "s": " ", "p": "p", "h": "h", "R": "r", "_": " "}


class Vt100:
    """Small cursor-addressing terminal emulator (enough for curses output)."""

    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.grid = [[" "] * cols for _ in range(rows)]
        self.cy = self.cx = 0
        self.saved = (0, 0)

    def put(self, ch):
        if self.cy < self.rows and self.cx < self.cols:
            self.grid[self.cy][self.cx] = ch
        self.cx += 1
        if self.cx >= self.cols:
            self.cx = self.cols - 1

    def feed(self, data):
        i, n = 0, len(data)
        while i < n:
            c = data[i]
            if c == "\x1b":
                m = re.match(r"\x1b\[([0-9;?]*)([A-Za-z@])", data[i:])
                if m:
                    self.csi(m.group(1), m.group(2))
                    i += m.end()
                    continue
                m = re.match(r"\x1b[()][A-Za-z0-9]", data[i:])
                if m:
                    i += m.end()
                    continue
                m = re.match(r"\x1b[#][0-9]|\x1b[=>78MNDE]", data[i:])
                if m:
                    i += m.end()
                    continue
                m = re.match(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)", data[i:])
                if m:
                    i += m.end()
                    continue
                i += 1
                continue
            if c == "\n":
                self.cy += 1
                self.cx = 0
            elif c == "\r":
                self.cx = 0
            elif c == "\b":
                self.cx = max(0, self.cx - 1)
            elif c == "\t":
                self.cx = min(self.cols - 1, (self.cx // 8 + 1) * 8)
            elif c >= " " or ord(c) > 127:
                self.put(c)
            i += 1

    def csi(self, params, cmd):
        nums = [int(x) for x in params.split(";") if x.isdigit()]
        get = lambda k, d=1: nums[k] if len(nums) > k else d
        if cmd == "H" or cmd == "f":
            self.cy, self.cx = get(0) - 1, get(1) - 1
        elif cmd == "A":
            self.cy = max(0, self.cy - get(0))
        elif cmd == "B":
            self.cy = min(self.rows - 1, self.cy + get(0))
        elif cmd == "C":
            self.cx = min(self.cols - 1, self.cx + get(0))
        elif cmd == "D":
            self.cx = max(0, self.cx - get(0))
        elif cmd == "G":
            self.cx = get(0) - 1
        elif cmd == "d":
            self.cy = get(0) - 1
        elif cmd == "J":
            mode = get(0, 0)
            if mode == 2:
                self.grid = [[" "] * self.cols for _ in range(self.rows)]
            elif mode == 0:
                for x in range(self.cx, self.cols):
                    self.grid[self.cy][x] = " "
                for y in range(self.cy + 1, self.rows):
                    self.grid[y] = [" "] * self.cols
            elif mode == 1:
                for y in range(self.cy):
                    self.grid[y] = [" "] * self.cols
                for x in range(self.cx + 1):
                    self.grid[self.cy][x] = " "
        elif cmd == "K":
            mode = get(0, 0)
            row = self.grid[self.cy] if self.cy < self.rows else None
            if row:
                if mode == 2:
                    self.grid[self.cy] = [" "] * self.cols
                elif mode == 1:
                    for x in range(min(self.cx + 1, self.cols)):
                        row[x] = " "
                else:
                    for x in range(self.cx, self.cols):
                        row[x] = " "
        elif cmd == "s":
            self.saved = (self.cy, self.cx)
        elif cmd == "u":
            self.cy, self.cx = self.saved

    def text(self):
        return "\n".join("".join(row).rstrip() for row in self.grid)


def main():
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 28
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    script = sys.argv[3] if len(sys.argv) > 3 else "lrruzs_d_d_c_s_s"
    keys = [KEYS[ch] for ch in script if ch in KEYS]

    pid, master = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, "tetris.py")])
        os._exit(1)
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    term = Vt100(rows, cols)

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
            if chunk:
                term.feed(chunk.decode("utf-8", "replace"))

    pump(1.2)
    for k in keys:
        os.write(master, k.encode())
        pump(0.08)
    pump(1.0)
    print(term.text())
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass
    os.close(master)


if __name__ == "__main__":
    main()