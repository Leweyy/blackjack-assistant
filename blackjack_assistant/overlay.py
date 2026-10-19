"""Small always-on-top window that shows the current advice, plus a region picker."""

from __future__ import annotations

import queue
import tkinter as tk

from .advisor import Advice
from .capture import Region
from .strategy import Action

COLORS = {
    Action.HIT: "#2e7d32",
    Action.STAND: "#c62828",
    Action.DOUBLE: "#f9a825",
    Action.SPLIT: "#1565c0",
    Action.SURRENDER: "#6a1b9a",
    None: "#424242",
}


class Overlay:
    def __init__(self, updates: "queue.Queue[Advice | str]"):
        self.updates = updates
        self.root = tk.Tk()
        self.root.title("Blackjack Assistant")
        self.root.attributes("-topmost", True)
        self.root.geometry("+40+40")
        self.root.configure(bg=COLORS[None])

        self.headline = tk.Label(self.root, text="Starting…", font=("Helvetica", 36, "bold"),
                                 fg="white", bg=COLORS[None], padx=24, pady=8)
        self.headline.pack(fill="x")
        self.detail = tk.Label(self.root, text="", font=("Helvetica", 12), fg="white",
                               bg=COLORS[None], padx=12, pady=6, wraplength=420, justify="left")
        self.detail.pack(fill="x")
        self.status = tk.Label(self.root, text="", font=("Helvetica", 9), fg="#bbbbbb",
                               bg=COLORS[None], padx=12, pady=4)
        self.status.pack(fill="x")

        # Drag the window around by clicking anywhere on it.
        for w in (self.root, self.headline, self.detail, self.status):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag)
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

    def _start_drag(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _poll(self):
        try:
            while True:
                item = self.updates.get_nowait()
                if isinstance(item, Advice):
                    color = COLORS.get(item.action, COLORS[None])
                    self.headline.configure(text=item.headline, bg=color)
                    self.detail.configure(text=item.detail)
                    if item.action:
                        self.root.bell()
                else:
                    self.status.configure(text=item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def run(self):
        self._poll()
        self.root.mainloop()


def select_region() -> Region | None:
    """Full-screen translucent window; drag a rectangle around the game table."""
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.3)
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(root.winfo_screenwidth() // 2, 40, fill="white", font=("Helvetica", 20),
                       text="Drag around the blackjack table, then release. Esc to cancel.")
    state: dict = {}

    def down(e):
        state["x0"], state["y0"] = e.x_root, e.y_root
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)
        state["cx0"], state["cy0"] = e.x, e.y

    def move(e):
        canvas.coords(state["rect"], state["cx0"], state["cy0"], e.x, e.y)

    def up(e):
        x0, y0 = state["x0"], state["y0"]
        x1, y1 = e.x_root, e.y_root
        if abs(x1 - x0) > 20 and abs(y1 - y0) > 20:
            state["region"] = Region(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        root.destroy()

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", move)
    canvas.bind("<ButtonRelease-1>", up)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.mainloop()
    return state.get("region")
