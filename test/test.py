#!/usr/bin/env python3
"""
Desktop Goose: a goose that waddles across your screen, walks up to a folder
icon on your desktop, shrinks into it, and leaves a hidden goose file inside
that folder. It pops back out and moves on, relocating the file each time.

Your job: find the hidden file (.goose.honk). When you open, move, edit or
delete it, the goose honks, a message prints, and the game ends.

Run:        python goose.py
First run:  python goose.py --calibrate
            Click each desktop folder's icon once so the goose knows exactly
            where they are. Do this if it ever walks to the wrong spot, and
            again whenever you rearrange your desktop icons.

Options:    --keep            leave the goose file behind when the game ends
            --no-file         animation only, never touch the file system
            --log FILE        also save each folder the goose enters to FILE
                              (it always prints them to the terminal too)
            --origin X Y      (estimates only) centre of the first desktop icon
            --cell W H        (estimates only) icon grid cell size in px
Quit:       right-click the goose (or Ctrl+C in the terminal)

Icon positions:
  Windows  pip install pywinauto   -> real positions of your desktop folders
  macOS    asks Finder for each folder's real position (allow the
           "Automation" permission prompt the first time)
  Linux    positions are estimated; tune with --origin / --cell

Tip: the file is hidden. Show hidden files (Cmd+Shift+. on macOS, View >
Hidden items on Windows, Ctrl+H on Linux) to hunt for it.
"""
import argparse
import atexit
import json
import math
import platform
import random
import subprocess
import time
import tkinter as tk
from pathlib import Path

SYSTEM = platform.system()
KEY = "#010203"          # colour treated as see-through
SIZE = 130               # goose window size in px
TICK = 33                # ms per frame (~30 fps)
SPEED = 4                # px per frame while walking
ENTER_FRAMES = 18        # frames for the shrink-in / grow-out animation
HIDE_TICKS = 90          # how long the goose stays inside a folder (~3 s)
WATCH_EVERY = 15         # check the goose file every N frames (~0.5 s)
FOUND_GRACE = 3.0        # seconds before "opened" (access time) counts
CELEBRATE_TICKS = 150    # how long the goose celebrates before the game ends
GOOSE_FILE = ".goose.honk"
GRID = {"origin": None, "cell": None}    # set from the command line
LOG = {"path": None}                     # set from --log
POS_FILE = Path.home() / ".goose_positions.json"   # written by --calibrate


def log(msg):
    """Print a timestamped line, and append it to the --log file if given."""
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG["path"]:
        try:
            with open(LOG["path"], "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------- targets ---

def enable_dpi_awareness():
    """Windows: make tk coordinates match real screen pixels."""
    if SYSTEM == "Windows":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def load_saved(sw, sh):
    """Icon positions the player taught the goose with --calibrate."""
    try:
        data = json.loads(POS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if data.get("screen") != [sw, sh]:
        return []                       # screen size changed: positions are stale
    by_name = {p.name: p for p in desktop_folders()}
    return [(int(x), int(y), by_name[n])
            for n, (x, y) in data.get("icons", {}).items() if n in by_name]


def calibrate():
    """Click each desktop folder's icon once; the goose remembers the spots."""
    folders = desktop_folders()
    if not folders:
        print(f"No folders found in {desktop_dir()}.")
        return
    enable_dpi_awareness()
    root = tk.Tk()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.15)          # nearly invisible, but catches clicks
    root.geometry(f"{sw}x{sh}+0+0")
    root.config(bg="black", cursor="crosshair")
    banner = tk.Toplevel(root)
    banner.overrideredirect(True)
    banner.attributes("-topmost", True)
    label = tk.Label(banner, bg="#fffbe0", fg="black", bd=2, relief="solid",
                     font=("Helvetica", 16, "bold"), padx=16, pady=8)
    label.pack()
    icons, idx = {}, [0]

    def show():
        if idx[0] >= len(folders):
            if icons:
                POS_FILE.write_text(json.dumps({"screen": [sw, sh], "icons": icons}),
                                    encoding="utf-8")
                print(f"Saved {len(icons)} icon position(s) to {POS_FILE}")
            else:
                print("Nothing saved (every folder was skipped).")
            root.destroy()
            return
        label.config(text=f'Click the icon for "{folders[idx[0]].name}"   '
                          f'({idx[0] + 1}/{len(folders)}, right-click to skip)')
        banner.update_idletasks()
        banner.geometry(f"+{max(0, (sw - banner.winfo_reqwidth()) // 2)}+40")
        banner.lift()

    def click(e):
        icons[folders[idx[0]].name] = [e.x_root, e.y_root]
        idx[0] += 1
        show()

    def skip(e):
        idx[0] += 1
        show()

    root.bind("<Button-1>", click)
    for b in ("<Button-2>", "<Button-3>"):
        root.bind(b, skip)
    show()
    try:
        root.mainloop()
    except KeyboardInterrupt:
        root.destroy()


def desktop_dir():
    if SYSTEM == "Windows":
        try:  # the real Desktop, even when OneDrive redirects it
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    return Path.home() / "Desktop"


def desktop_folders():
    d = desktop_dir()
    if not d.is_dir():
        return []
    try:
        return sorted(
            (p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def uia_targets():
    """Windows: ask the shell for the real on-screen rectangle of each icon."""
    from pywinauto import Desktop  # optional dependency

    by_name = {p.name: p for p in desktop_folders()}
    found = []
    desk = Desktop(backend="uia")
    for cls in ("Progman", "WorkerW"):
        for win in desk.windows(class_name=cls):
            for item in win.descendants(control_type="ListItem"):
                name = item.window_text()
                if name in by_name:
                    r = item.rectangle()
                    if r.right > r.left and r.bottom > r.top:
                        found.append(((r.left + r.right) // 2,
                                      (r.top + r.bottom) // 2,
                                      by_name[name]))
    return found


def mac_position(folder):
    """macOS: ask Finder where this folder's icon sits on the desktop."""
    name = folder.name.replace("\\", "\\\\").replace('"', '\\"')
    script = ('tell application "Finder" to get desktop position of '
              f'folder "{name}" of desktop')
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        x, y = (int(float(v)) for v in r.stdout.strip().split(","))
        return x, y
    except Exception:
        return None


def fallback_targets(sw, sh):
    """Guess icon positions from the default desktop grid layout."""
    mac = SYSTEM == "Darwin"
    cell_w, cell_h = GRID["cell"] or ((100, 100) if mac else (80, 95))
    if GRID["origin"]:
        ox, oy = GRID["origin"]
    else:
        ox = sw - cell_w / 2 - 10 if mac else cell_w / 2 + 5
        oy = (40 if mac else 10) + cell_h / 2
    rows = max(1, int((sh - (oy - cell_h / 2) - 60) // cell_h))
    out = []
    for i, folder in enumerate(desktop_folders()):
        col, row = divmod(i, rows)
        x = ox - col * cell_w if mac else ox + col * cell_w
        out.append((int(x), int(oy + row * cell_h), folder))
    return out


# ----------------------------------------------------------------- goose ---

class Goose:
    def __init__(self, write_files=True, keep=False):
        self.write_files = write_files
        self.keep = keep
        self.goose_file = None
        self.baseline = None
        self.dropped_at = 0.0
        self.bubble = None
        self.warned = False
        self.n = 0

        self.source = "?"
        enable_dpi_awareness()

        self.root = root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        bg = KEY
        try:
            if SYSTEM == "Darwin":
                root.attributes("-transparent", True)
                bg = "systemTransparent"
            else:
                root.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass  # Linux without a compositor: goose gets a flat background
        root.config(bg=bg)
        self.cv = tk.Canvas(root, width=SIZE, height=SIZE, bg=bg,
                            highlightthickness=0)
        self.cv.pack()
        for btn in ("<Button-2>", "<Button-3>"):
            self.cv.bind(btn, lambda e: self.quit())

        self.sw = root.winfo_screenwidth()
        self.sh = root.winfo_screenheight()
        log(f"Screen {self.sw}x{self.sh}; Desktop folder: {desktop_dir()} "
            f"({len(desktop_folders())} subfolders)")
        self.x, self.y = 0.0, float(self.sh - 10)   # feet position on screen
        self.scale, self.facing, self.phase = 1.0, 1, 0.0
        self.state, self.frame, self.wait = "walk", 0, 0
        self.target = None
        self.pick_target()
        atexit.register(self.cleanup)

    # -- targets --
    def warn_estimated(self):
        if self.warned:
            return
        self.warned = True
        print("Note: couldn't read your real icon positions, so the goose is "
              "guessing where folders are, and it will probably miss them.\n"
              "      Fix: run `python goose.py --calibrate` and click each "
              "folder's icon once.")

    def find_target(self, avoid):
        folders = [p for p in desktop_folders() if p != avoid] or desktop_folders()
        if not folders:
            return None

        def usable(t):                  # (0, 0) is what a failed lookup looks like
            return t[0] > 1 or t[1] > 1

        saved = [t for t in load_saved(self.sw, self.sh) if usable(t)]
        pool = [t for t in saved if t[2] != avoid] or saved
        if pool:
            self.source = "calibrated"
            return random.choice(pool)
        if SYSTEM == "Windows":
            try:
                found = [t for t in uia_targets() if usable(t)]
            except Exception:
                found = []
            pool = [t for t in found if t[2] != avoid] or found
            if pool:
                self.source = "Windows UI Automation"
                return random.choice(pool)
        elif SYSTEM == "Darwin":
            random.shuffle(folders)
            for p in folders[:5]:
                pos = mac_position(p)
                if pos and usable(pos):
                    self.source = "Finder"
                    return (pos[0], pos[1], p)
        self.warn_estimated()
        self.source = "estimated"
        est = fallback_targets(self.sw, self.sh)
        pool = [t for t in est if t[2] != avoid] or est
        return random.choice(pool) if pool else None

    def pick_target(self):
        t = self.find_target(self.target[2] if self.target else None)
        if t is None:
            print("No folders found on your Desktop for the goose to enter.")
            self.quit()
            return
        self.target = t
        self.state = "walk"

    # -- the game part: hide the goose file, notice when it's found --
    def drop_goose(self, folder):
        if not self.write_files:
            return
        if self.goose_file and self.file_touched():     # found just before it moved
            self.found()
            return
        self.remove_goose_file()
        try:
            f = folder / GOOSE_FILE
            f.write_text("honk\n")
            if SYSTEM == "Windows":
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(f), 0x02)  # hidden
            st = f.stat()
            self.baseline = (st.st_mtime_ns, st.st_atime_ns)
            self.dropped_at = time.time()
            self.goose_file = f
        except OSError:
            self.goose_file = None

    def file_touched(self):
        """True once the file is opened, edited, renamed, moved or deleted."""
        f = self.goose_file
        if not f or not self.baseline:
            return False
        try:
            st = f.stat()
        except OSError:
            return True
        mtime, atime = self.baseline
        if st.st_mtime_ns != mtime:
            return True
        return (time.time() - self.dropped_at > FOUND_GRACE
                and st.st_atime_ns > atime + 1_000_000_000)

    def found(self):
        folder = self.goose_file.parent
        secs = int(time.time() - self.dropped_at)
        log(f"HONK! You found the goose in {folder} "
            f"(it had been there {secs}s). Nice work!")
        self.cleanup()
        self.goose_file = None
        if self.state in ("hidden", "enter", "emerge") and self.target:
            self.x, self.y = float(self.target[0]), float(self.target[1] + 22)
        self.scale, self.state, self.wait = 1.0, "celebrate", CELEBRATE_TICKS
        self.show_bubble("HONK! You found me!")

    def show_bubble(self, text):
        try:
            b = tk.Toplevel(self.root)
            b.overrideredirect(True)
            b.attributes("-topmost", True)
            tk.Label(b, text=text, bg="#fffbe0", fg="black",
                     font=("Helvetica", 14, "bold"), padx=12, pady=6,
                     bd=2, relief="solid").pack()
            b.update_idletasks()
            w = b.winfo_reqwidth()
            b.geometry(f"+{max(0, int(self.x - w / 2))}"
                       f"+{max(0, int(self.y - SIZE - 30))}")
            self.bubble = b
        except tk.TclError:
            pass

    def remove_goose_file(self):
        if self.goose_file:
            try:
                self.goose_file.unlink()
            except OSError:
                pass
            self.goose_file = None

    def cleanup(self):
        if not self.keep:
            self.remove_goose_file()

    def quit(self):
        self.cleanup()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # -- drawing --
    def draw(self, visible=True):
        c = self.cv
        c.delete("all")
        if visible:
            self._draw_goose(c)
        self.root.geometry(
            f"{SIZE}x{SIZE}+{int(self.x - SIZE / 2)}+{int(self.y - (SIZE - 8))}")

    def _draw_goose(self, c):
        s, f = self.scale, self.facing
        cx, base = SIZE / 2, SIZE - 8
        walking = self.state == "walk"
        bob = (abs(math.sin(self.phase)) * 4 * s
               if self.state in ("walk", "celebrate") else 0)

        def P(x, y, b=bob):
            return (cx + f * x * s, base - y * s - b)

        def oval(x0, y0, x1, y1, **kw):
            ax, ay = P(x0, y0)
            bx, by = P(x1, y1)
            c.create_oval(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), **kw)

        def poly(pts, **kw):
            c.create_polygon(*[v for p in pts for v in P(*p)], **kw)

        orange, gray = "#ff9a1f", "#b8b8b8"
        swing = math.sin(self.phase) * 7 if walking else 0
        for dx in (swing, -swing):                       # legs + feet
            c.create_line(*P(dx, 18), *P(dx, 3, 0), fill=orange, width=max(1, 3 * s))
            poly([(dx - 4, 0), (dx + 11, 0), (dx, 6)], fill=orange)
        poly([(-30, 30), (-48, 40), (-28, 43)], fill="white", outline=gray)  # tail
        oval(-32, 14, 26, 46, fill="white", outline=gray)                    # body
        oval(-22, 20, 10, 40, fill="#eeeeee", outline=gray)                  # wing
        c.create_line(*P(16, 36), *P(30, 70), fill=gray, width=max(1, 14 * s),
                      capstyle="round")
        c.create_line(*P(16, 36), *P(30, 70), fill="white", width=max(1, 11 * s),
                      capstyle="round")                                      # neck
        oval(22, 66, 43, 87, fill="white", outline=gray)                     # head
        poly([(41, 79), (58, 75), (41, 70)], fill=orange)                    # beak
        oval(33, 78, 37, 82, fill="black")                                   # eye

    # -- animation loop --
    def tick(self):
        self.n += 1
        if (self.state != "celebrate" and self.goose_file
                and self.n % WATCH_EVERY == 0 and self.file_touched()):
            self.found()

        st = self.state
        if st == "walk":
            tx, ty, _ = self.target
            ty += 22                                  # stand on the icon
            dx, dy = tx - self.x, ty - self.y
            dist = math.hypot(dx, dy)
            if abs(dx) > 2:
                self.facing = 1 if dx > 0 else -1
            if dist <= SPEED:
                self.x, self.y = tx, ty
                self.state, self.frame = "enter", 0
                log(f"Goose is entering: {self.target[2]} "
                    f"(at x={tx}, y={self.target[1]}; position from: {self.source})")
            else:
                self.x += dx / dist * SPEED
                self.y += dy / dist * SPEED
                self.phase += 0.5
            self.draw()
        elif st == "enter":                           # shrink into the folder
            self.frame += 1
            self.scale = max(0.05, 1 - self.frame / ENTER_FRAMES)
            self.y += 1.5
            self.draw()
            if self.frame >= ENTER_FRAMES:
                self.drop_goose(self.target[2])
                if self.state == "enter":
                    self.state, self.wait = "hidden", HIDE_TICKS
                    self.draw(visible=False)
        elif st == "hidden":
            self.wait -= 1
            if self.wait <= 0:
                self.state, self.frame = "emerge", 0
        elif st == "emerge":                          # pop back out
            self.frame += 1
            self.scale = min(1.0, 0.05 + self.frame / ENTER_FRAMES)
            self.y -= 1.5
            self.draw()
            if self.frame >= ENTER_FRAMES:
                self.scale = 1.0
                self.pick_target()
        elif st == "celebrate":                       # hop and honk, then done
            self.phase += 0.6
            self.wait -= 1
            self.draw()
            if self.wait <= 0:
                self.quit()
                return
        try:
            self.root.after(TICK, self.tick)
        except tk.TclError:
            pass

    def run(self):
        self.root.after(TICK, self.tick)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.quit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A goose that enters your desktop folders.")
    ap.add_argument("--keep", action="store_true", help="keep the goose file on exit")
    ap.add_argument("--no-file", action="store_true", help="animation only")
    ap.add_argument("--origin", type=int, nargs=2, metavar=("X", "Y"),
                    help="estimates only: centre of the first desktop icon")
    ap.add_argument("--cell", type=int, nargs=2, metavar=("W", "H"),
                    help="estimates only: icon grid cell size")
    ap.add_argument("--log", metavar="FILE",
                    help="also append the goose's movements to this file")
    ap.add_argument("--calibrate", action="store_true",
                    help="click each desktop folder icon once so the goose "
                         "knows exactly where they are, then exit")
    a = ap.parse_args()
    if a.calibrate:
        calibrate()
        raise SystemExit
    GRID["origin"], GRID["cell"] = a.origin, a.cell
    LOG["path"] = a.log
    Goose(write_files=not a.no_file, keep=a.keep).run()