"""A small tkinter GUI for the converter (stdlib only, matches the existing
hitmix tooling). Pick an input .als, choose source + target track, convert.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import sources
from .convert import CURRENT_TARGET, TARGETS, convert
from .cli import default_out


def launch() -> None:
    root = tk.Tk()
    root.title("hitdesigndmx")
    root.geometry("620x300")

    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)

    in_var = tk.StringVar()
    out_var = tk.StringVar()
    src_var = tk.StringVar(value="auto")
    src_track_var = tk.StringVar()
    tgt_track_var = tk.StringVar(value="dmx_note")
    tgt_var = tk.StringVar(value=CURRENT_TARGET)

    def sync_out(*_a: object) -> None:
        if in_var.get() and not out_var.get():
            out_var.set(str(default_out(Path(in_var.get()), tgt_var.get())))

    def pick_in() -> None:
        f = filedialog.askopenfilename(
            title="Source .als", filetypes=[("Ableton Live Set", "*.als")]
        )
        if f:
            in_var.set(f)
            out_var.set("")
            sync_out()

    def pick_out() -> None:
        f = filedialog.asksaveasfilename(
            title="Output .als", defaultextension=".als",
            filetypes=[("Ableton Live Set", "*.als")],
        )
        if f:
            out_var.set(f)

    rows = [
        ("Input .als", in_var, pick_in),
        ("Output .als", out_var, pick_out),
    ]
    for i, (label, var, cmd) in enumerate(rows):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=var).grid(row=i, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="…", width=3, command=cmd).grid(row=i, column=2, **pad)

    ttk.Label(frm, text="Source").grid(row=2, column=0, sticky="w", **pad)
    ttk.Combobox(
        frm, textvariable=src_var, values=["auto", *sources.SOURCES],
        state="readonly", width=14,
    ).grid(row=2, column=1, sticky="w", **pad)

    ttk.Label(frm, text="Source track").grid(row=3, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=src_track_var).grid(row=3, column=1, sticky="ew", **pad)

    ttk.Label(frm, text="Target track").grid(row=4, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=tgt_track_var).grid(row=4, column=1, sticky="ew", **pad)

    ttk.Label(frm, text="Target mapping").grid(row=5, column=0, sticky="w", **pad)
    ttk.Combobox(
        frm, textvariable=tgt_var, values=list(TARGETS), state="readonly", width=14,
    ).grid(row=5, column=1, sticky="w", **pad)

    status = tk.StringVar(value="Pick a source .als and convert.")
    ttk.Label(frm, textvariable=status, wraplength=560, foreground="#555").grid(
        row=7, column=0, columnspan=3, sticky="w", **pad
    )

    btn = ttk.Button(frm, text="Convert")
    btn.grid(row=6, column=1, sticky="e", **pad)

    def run() -> None:
        if not in_var.get():
            status.set("Choose an input .als first.")
            return
        out = out_var.get() or str(default_out(Path(in_var.get()), tgt_var.get()))
        btn.config(state="disabled")
        status.set("Converting…")

        def work() -> None:
            try:
                res = convert(
                    in_var.get(), out,
                    source=src_var.get(),
                    source_track=src_track_var.get() or None,
                    target_track=tgt_track_var.get() or "dmx_note",
                    target=tgt_var.get(),
                )
                msg = (
                    f"Done [{res.source} → {res.target}]: "
                    f"{res.clips_written}/{res.clips_in} clips, "
                    f"{res.notes_written} notes → {res.out_path}"
                )
            except Exception as e:  # surface the error in the GUI
                msg = f"Error: {e}"
            root.after(0, lambda: (status.set(msg), btn.config(state="normal")))

        threading.Thread(target=work, daemon=True).start()

    btn.config(command=run)
    tgt_var.trace_add("write", sync_out)
    root.mainloop()


if __name__ == "__main__":
    launch()
