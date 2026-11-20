"""Tkinter user interface."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import __version__
from .app_logic import click_boundaries
from .audio import SUPPORTED_EXTENSIONS, Audio, WaveformEnvelope
from .export import format_timestamp, write_export
from .model import Segment, Structure
from .neural import check_python, find_python
from .player import PlaybackError, Player
from .render import BACKGROUND, PLAYHEAD, draw_structure, render_png
from .settings import load_settings, save_settings

APP_NAME = "SongStructurer"
STANDARD_LABELS = (
    "Intro",
    "Verse",
    "Pre-Chorus",
    "Chorus",
    "Post-Chorus",
    "Bridge",
    "Solo",
    "Break",
    "Interlude",
    "Outro",
    "Silence",
)
MIN_VIEW_SECONDS = 0.5
POLL_MS = 30
#: How close (in pixels) the pointer must be to a boundary to grab it.
GRAB_PIXELS = 6


class LabelDialog(tk.Toplevel):
    """Asks for a label; offers the usual section names and the current ones."""

    def __init__(
        self, parent: tk.Misc, title: str, initial: str, choices: list[str], offer_group: bool
    ):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result: tuple[str, bool] | None = None

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Etichetta:").grid(row=0, column=0, sticky="w")
        self._value = tk.StringVar(value=initial)
        self._combo = ttk.Combobox(body, textvariable=self._value, values=choices, width=28)
        self._combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        self._group = tk.BooleanVar(value=False)
        if offer_group:
            ttk.Checkbutton(
                body,
                text="Applica a tutte le sezioni uguali",
                variable=self._group,
            ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(body, text="OK", command=self._accept).grid(row=3, column=0, sticky="e", padx=4)
        ttk.Button(body, text="Annulla", command=self.destroy).grid(row=3, column=1, sticky="w")

        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self._combo.focus_set()
        self._combo.selection_range(0, tk.END)
        self.grab_set()

    def _accept(self) -> None:
        value = self._value.get().strip()
        if value:
            self.result = (value, bool(self._group.get()))
            self.destroy()


class App(tk.Tk):
    """Main window."""

    def __init__(self, player: Player | None = None):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x720")
        self.minsize(820, 480)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

        self.player = player or Player()
        self.audio: Audio | None = None
        self.envelope: WaveformEnvelope | None = None
        self.structure: Structure | None = None
        self.metadata: dict[str, Any] = {}
        self.analysis: Any | None = None
        self.stems: dict[str, Path] = {}
        self.settings = load_settings()
        self.engine = tk.StringVar(value=self.settings["engine"])
        self.view: tuple[float, float] = (0.0, 1.0)
        self.playhead_time = 0.0

        self._events: queue.Queue[tuple] = queue.Queue()
        self._busy = False
        self._drag_boundary: int | None = None
        self._redraw_scheduled = False
        self._background = None
        self._playhead_artist = None
        self._was_playing = False
        self._closing = False
        self._updating_tree = False

        self._build_menu()
        self._build_toolbar()
        self._build_canvas()
        self._build_table()
        self._build_statusbar()
        self._bind_keys()
        self._refresh_actions()
        self._redraw()
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ build

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Apri…", accelerator="Ctrl+O", command=self.open_dialog)
        self._export_menu = tk.Menu(file_menu, tearoff=False)
        self._export_menu.add_command(
            label="Segmenti CSV…", command=lambda: self.export_dialog(".csv")
        )
        self._export_menu.add_command(
            label="Segmenti JSON…", command=lambda: self.export_dialog(".json")
        )
        self._export_menu.add_command(
            label="Etichette Audacity (TXT)…", command=lambda: self.export_dialog(".txt")
        )
        self._export_menu.add_command(
            label="Immagine PNG…", command=lambda: self.export_dialog(".png")
        )
        self._export_menu.add_command(
            label="Traccia guida con beep (MP3/WAV)…", command=self.export_click_track
        )
        self._export_menu.add_command(label="Accordi (TXT Audacity)…", command=self.export_chords)
        self._export_menu.add_command(label="MIDI di melodia e basso…", command=self.export_midi)
        self._export_menu.add_command(label="Stem separati (Demucs)…", command=self.export_stems)
        file_menu.add_cascade(label="Esporta", menu=self._export_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Esci", command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        edit = tk.Menu(menubar, tearoff=False)
        edit.add_command(label="Annulla", accelerator="Ctrl+Z", command=self.undo)
        edit.add_command(label="Ripeti", accelerator="Ctrl+Y", command=self.redo)
        edit.add_separator()
        edit.add_command(label="Dividi al cursore", accelerator="S", command=self.split_at_playhead)
        edit.add_command(label="Unisci selezionati", accelerator="M", command=self.merge_selected)
        edit.add_command(label="Rinomina…", accelerator="F2", command=self.rename_selected)
        self._edit_menu = edit
        menubar.add_cascade(label="Modifica", menu=edit)

        analysis = tk.Menu(menubar, tearoff=False)
        analysis.add_command(label="Analizza struttura", command=self.analyze)
        analysis.add_separator()
        analysis.add_radiobutton(
            label="Motore classico (integrato, veloce)",
            variable=self.engine,
            value="classic",
            command=self._on_engine_changed,
        )
        analysis.add_radiobutton(
            label="Motore neurale (allin1, Python esterno)",
            variable=self.engine,
            value="neural",
            command=self._on_engine_changed,
        )
        analysis.add_command(
            label="Configura Python per il motore neurale…", command=self.configure_neural
        )
        self._analysis_menu = analysis
        menubar.add_cascade(label="Analisi", menu=analysis)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Informazioni", command=self.show_about)
        menubar.add_cascade(label="Aiuto", menu=help_menu)
        self.config(menu=menubar)

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(side=tk.TOP, fill=tk.X)

        def button(text: str, command: Callable[[], None], width: int | None = None) -> ttk.Button:
            widget = ttk.Button(bar, text=text, command=command)
            if width:
                widget.configure(width=width)
            widget.pack(side=tk.LEFT, padx=2)
            return widget

        def separator() -> None:
            ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        self.btn_open = button("Apri…", self.open_dialog)
        self.btn_analyze = button("Analizza", self.analyze)
        separator()
        self.btn_play = button("Play", self.toggle_play, width=9)
        self.btn_play_segment = button("Sezione", self.play_selected)
        self.btn_stop = button("Stop", self.stop)
        self.time_label = ttk.Label(bar, text="00:00.0 / 00:00.0", width=18, anchor="center")
        self.time_label.pack(side=tk.LEFT, padx=6)
        separator()
        self.btn_split = button("Dividi", self.split_at_playhead)
        self.btn_merge = button("Unisci", self.merge_selected)
        self.btn_rename = button("Rinomina", self.rename_selected)
        separator()
        self.btn_zoom_out = button("−", lambda: self.zoom(1 / 1.6), width=3)
        self.btn_zoom_in = button("+", lambda: self.zoom(1.6), width=3)
        self.btn_zoom_all = button("Tutto", self.zoom_all)

    def _build_canvas(self) -> None:
        frame = ttk.Frame(self)
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8)
        self.figure = Figure(figsize=(10, 3), dpi=100, facecolor=BACKGROUND)
        self.ax = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.005, right=0.995, top=0.98, bottom=0.12)
        self.canvas = FigureCanvasTkAgg(self.figure, master=frame)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.configure(highlightthickness=0, takefocus=True)
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.scrollbar = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self._on_scrollbar)
        self.scrollbar.pack(side=tk.TOP, fill=tk.X)

        self.canvas.mpl_connect("draw_event", self._on_draw)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)

        self._context = tk.Menu(self, tearoff=False)
        self._context.add_command(label="Dividi qui", command=self._split_at_context)
        self._context.add_command(label="Rinomina…", command=self.rename_selected)
        self._context.add_command(label="Elimina confine a sinistra", command=self._remove_left)
        self._context.add_command(label="Riproduci sezione", command=self.play_selected)
        self._context_time = 0.0

    def _build_table(self) -> None:
        frame = ttk.Frame(self, padding=(8, 6))
        frame.pack(side=tk.TOP, fill=tk.BOTH)
        columns = ("index", "start", "end", "duration", "label")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=9, selectmode="extended"
        )
        headings = {
            "index": ("#", 40, "e"),
            "start": ("Inizio", 90, "e"),
            "end": ("Fine", 90, "e"),
            "duration": ("Durata", 90, "e"),
            "label": ("Etichetta", 300, "w"),
        }
        for key, (text, width, anchor) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "label")
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda _e: self.rename_selected())

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, padding=(8, 2))
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status = tk.StringVar(value="Apri un file audio per iniziare.")
        ttk.Label(bar, textvariable=self.status, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.info = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.info, anchor="e").pack(side=tk.LEFT, padx=8)
        self.progress = ttk.Progressbar(bar, length=160, mode="determinate", maximum=1.0)
        self.progress.pack(side=tk.RIGHT)

    def _bind_keys(self) -> None:
        self.bind("<Control-o>", lambda _e: self.open_dialog())
        self.bind("<Control-z>", lambda _e: self.undo())
        self.bind("<Control-y>", lambda _e: self.redo())
        self.bind("<F2>", lambda _e: self.rename_selected())
        for widget in (self.canvas_widget, self.tree):
            widget.bind("<space>", lambda _e: (self.toggle_play(), "break")[1])
            widget.bind("<s>", lambda _e: self.split_at_playhead())
            widget.bind("<m>", lambda _e: self.merge_selected())

    # ---------------------------------------------------------------- workers

    def _run_task(
        self,
        work: Callable[[Callable[[float, str], None]], Any],
        done: Callable[[Any], None],
        message: str,
    ) -> None:
        """Run ``work`` off the UI thread; ``done`` gets its result on the UI thread."""
        if self._busy:
            return
        self._busy = True
        self.status.set(message)
        self.progress.configure(value=0.0)
        self._refresh_actions()

        def report(fraction: float, text: str) -> None:
            self._events.put(("progress", fraction, text))

        def runner() -> None:
            try:
                result = work(report)
            except Exception as exc:  # noqa: BLE001 - reported to the user
                self._events.put(("error", exc))
            else:
                self._events.put(("done", done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _poll(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    self.progress.configure(value=event[1])
                    self.status.set(event[2] + "…")
                elif kind == "error":
                    self._busy = False
                    self.progress.configure(value=0.0)
                    self.status.set("Operazione non riuscita.")
                    self._refresh_actions()
                    messagebox.showerror(APP_NAME, str(event[1]), parent=self)
                elif kind == "done":
                    self._busy = False
                    self.progress.configure(value=0.0)
                    self._refresh_actions()
                    event[1](event[2])
        except queue.Empty:
            pass
        self._tick_playback()
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------- file

    def open_dialog(self) -> None:
        if self._busy:
            return
        patterns = " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS)
        path = filedialog.askopenfilename(
            parent=self,
            title="Apri file audio",
            filetypes=[("File audio", patterns), ("Tutti i file", "*.*")],
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str | Path) -> None:
        """Load ``path`` in the background, then analyse it."""
        path = Path(path)

        def work(report: Callable[[float, str], None]) -> tuple[Audio, WaveformEnvelope]:
            from .audio import load_audio

            report(0.1, f"Caricamento di {path.name}")
            audio = load_audio(path)
            report(0.8, "Preparazione della forma d'onda")
            return audio, WaveformEnvelope(audio.mono(), audio.sr)

        self.stop()
        self._run_task(work, self._on_loaded, f"Caricamento di {path.name}…")

    def _on_loaded(self, loaded: tuple[Audio, WaveformEnvelope]) -> None:
        self.audio, self.envelope = loaded
        self.player.load(self.audio.samples, self.audio.sr)
        self.structure = Structure(self.audio.duration)
        self.metadata = {"file": self.audio.path.name if self.audio.path else ""}
        self.analysis = None
        self.stems = {}
        self.view = (0.0, self.audio.duration)
        self.playhead_time = 0.0
        name = self.audio.path.name if self.audio.path else ""
        self.title(f"{name} - {APP_NAME}" if name else APP_NAME)
        self.info.set("")
        self._refresh_all()
        self.analyze()

    def analyze(self) -> None:
        if self.audio is None or self._busy:
            return
        audio = self.audio
        if self.engine.get() == "neural":
            python = find_python(self.settings["neural_python"])
            if python is None or audio.path is None:
                messagebox.showinfo(
                    APP_NAME,
                    "Il motore neurale usa un Python esterno in cui è installato allin1.\n\n"
                    "Indicalo da Analisi → Configura Python per il motore neurale…\n"
                    "Per ora uso il motore classico.",
                    parent=self,
                )
                python = None

        else:
            python = None

        def work(report: Callable[[float, str], None]) -> Any:
            from .pipeline import full_analysis

            return full_analysis(audio, python, progress=report)

        label = "Analisi neurale…" if python else "Analisi della struttura…"
        self._run_task(work, self._on_analyzed, label)

    def _on_engine_changed(self) -> None:
        self.settings["engine"] = self.engine.get()
        save_settings(self.settings)

    def configure_neural(self) -> None:
        """Pick the interpreter where allin1 is installed and verify it."""
        if self._busy:
            return
        path = filedialog.askopenfilename(
            parent=self,
            title="Scegli l'interprete Python in cui è installato allin1",
            filetypes=[("Python", "python.exe python python3"), ("Tutti i file", "*.*")],
        )
        if not path:
            return

        def work(report: Callable[[float, str], None]) -> tuple[str, bool, str]:
            report(0.3, "Verifica di allin1")
            ok, detail = check_python(path)
            return path, ok, detail

        def done(outcome: tuple[str, bool, str]) -> None:
            chosen, ok, detail = outcome
            if not ok:
                self.status.set("Interprete non valido per il motore neurale.")
                messagebox.showerror(
                    APP_NAME,
                    f"In questo Python non riesco a importare allin1 e torch:\n{detail}",
                    parent=self,
                )
                return
            self.settings["neural_python"] = chosen
            self.settings["engine"] = "neural"
            self.engine.set("neural")
            save_settings(self.settings)
            self.status.set(f"Motore neurale pronto (allin1 e torch: {detail}).")

        self._run_task(work, done, "Verifica dell'interprete…")

    def _on_analyzed(self, result: Any) -> None:
        if self.audio is None:
            return
        self.analysis = result
        segments = [Segment(s.start, s.end, s.label, s.group) for s in result.sections]
        if self.structure is not None:
            # Keeps the edit history, so that a re-analysis can be undone.
            self.structure.replace_all(segments)
        else:
            self.structure = Structure(self.audio.duration, segments)
        self.metadata.update(
            {
                "tempo_bpm": result.tempo,
                "key": result.key,
                "engine": result.engine,
                "chords": [
                    {"start": round(c.start, 3), "end": round(c.end, 3), "name": c.name}
                    for c in result.chords
                ],
            }
        )
        parts = ["motore neurale" if result.engine == "neural" else "motore classico"]
        if result.tempo:
            parts.append(f"{result.tempo:.0f} BPM")
        if result.key:
            parts.append(f"tonalità {result.key}")
        self.info.set("  ·  ".join(parts))
        self.status.set(
            f"{len(self.structure)} sezioni trovate. I nomi sono una proposta: verifica e correggi."
        )
        self._refresh_all()

    def export_dialog(self, suffix: str) -> None:
        if self.structure is None or self.audio is None or self.envelope is None:
            return
        names = {
            ".csv": "CSV",
            ".json": "JSON",
            ".txt": "Etichette Audacity",
            ".png": "Immagine PNG",
        }
        stem = self.audio.path.stem if self.audio.path else "struttura"
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Esporta {names[suffix]}",
            defaultextension=suffix,
            initialfile=f"{stem}{suffix}",
            filetypes=[(names[suffix], f"*{suffix}")],
        )
        if not path:
            return
        try:
            if suffix == ".png":
                render_png(path, self.envelope, self.structure, title=self.metadata.get("file", ""))
            else:
                write_export(path, self.structure, self.metadata)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"Esportazione non riuscita:\n{exc}", parent=self)
            return
        self.status.set(f"Esportato: {path}")

    def export_click_track(self) -> None:
        """Save the song mixed with beat clicks and section-change risers."""
        if self.structure is None or self.audio is None or self._busy:
            return
        if self.analysis is None or not self.analysis.beat_times:
            messagebox.showinfo(
                APP_NAME, "Serve un'analisi completata per conoscere i beat.", parent=self
            )
            return
        stem = self.audio.path.stem if self.audio.path else "brano"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Esporta traccia guida",
            defaultextension=".mp3",
            initialfile=f"{stem}.click.mp3",
            filetypes=[("MP3", "*.mp3"), ("WAV", "*.wav"), ("FLAC", "*.flac")],
        )
        if not path:
            return
        audio, analysis = self.audio, self.analysis
        boundaries = click_boundaries(self.structure)

        def work(report: Callable[[float, str], None]) -> str:
            from .sonify import sonify, write_click_track

            report(0.3, "Sintesi dei beep")
            mixed = sonify(
                audio.samples, audio.sr, analysis.beat_times, analysis.downbeat_times, boundaries
            )
            report(0.7, "Scrittura del file")
            return str(write_click_track(path, mixed, audio.sr))

        self._run_task(work, lambda saved: self.status.set(f"Esportato: {saved}"), "Traccia guida…")

    def export_chords(self) -> None:
        if self.audio is None or self.analysis is None or not self.analysis.chords:
            self.status.set("Nessun accordo da esportare: serve un'analisi completata.")
            return
        stem = self.audio.path.stem if self.audio.path else "brano"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Esporta accordi",
            defaultextension=".txt",
            initialfile=f"{stem}.accordi.txt",
            filetypes=[("Etichette Audacity", "*.txt")],
        )
        if not path:
            return
        from .export import chords_to_labels

        try:
            Path(path).write_text(chords_to_labels(self.analysis.chords), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Esportazione non riuscita:\n{exc}", parent=self)
            return
        self.status.set(f"Esportato: {path}")

    def _external_python(self) -> str | None:
        """Interpreter for Demucs, or ``None`` after telling the user why."""
        python = find_python(self.settings["neural_python"])
        if python is None:
            messagebox.showinfo(
                APP_NAME,
                "Stem e MIDI usano Demucs, che gira nel Python esterno del motore neurale.\n\n"
                "Indicalo da Analisi → Configura Python per il motore neurale…",
                parent=self,
            )
        return python

    def export_stems(self) -> None:
        """Separate the song into stems with Demucs."""
        if self.audio is None or self.audio.path is None or self._busy:
            return
        python = self._external_python()
        if python is None:
            return
        six = messagebox.askyesno(
            APP_NAME,
            "Separare anche chitarra e piano (6 stem)?\n\n"
            "No = 4 stem: voce, basso, batteria, altro.",
            parent=self,
        )
        folder = filedialog.askdirectory(parent=self, title="Cartella in cui salvare gli stem")
        if not folder:
            return
        source = self.audio.path
        model = "htdemucs_6s" if six else "htdemucs"

        def work(report: Callable[[float, str], None]) -> dict[str, Path]:
            from .stems import separate

            return separate(source, folder, python, model=model, progress=report)

        def done(stems: dict[str, Path]) -> None:
            self.stems = stems
            self.status.set(f"{len(stems)} stem salvati in {folder}")

        self._run_task(work, done, "Separazione degli stem…")

    def export_midi(self) -> None:
        """Transcribe vocals and bass (from the stems) to a MIDI file."""
        if self.audio is None or self.audio.path is None or self._busy:
            return
        have_stems = all(
            name in self.stems and self.stems[name].is_file() for name in ("vocals", "bass")
        )
        python = None if have_stems else self._external_python()
        if not have_stems and python is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Esporta MIDI",
            defaultextension=".mid",
            initialfile=f"{self.audio.path.stem}.mid",
            filetypes=[("MIDI", "*.mid")],
        )
        if not path:
            return
        audio, stems = self.audio, dict(self.stems) if have_stems else None
        bpm = self.analysis.tempo if self.analysis is not None else 120.0

        def work(report: Callable[[float, str], None]) -> tuple[Path, dict[str, int]]:
            from .pipeline import export_midi

            if stems is None:
                report(0.1, "Separazione degli stem con Demucs (può richiedere alcuni minuti)")
            return export_midi(path, audio, bpm, python, stems, progress=report)

        def done(outcome: tuple[Path, dict[str, int]]) -> None:
            saved, counts = outcome
            detail = ", ".join(f"{name}: {count} note" for name, count in counts.items())
            self.status.set(f"Esportato: {saved} ({detail})")

        self._run_task(work, done, "Esportazione MIDI…")

    def show_about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} {__version__}\n\n"
            "Analisi automatica della struttura di un brano,\n"
            "con timeline modificabile.\n\nLicenza GPL-3.0",
            parent=self,
        )

    def quit_app(self) -> None:
        self._closing = True
        self.player.close()
        self.destroy()

    # --------------------------------------------------------------- playback

    def toggle_play(self) -> None:
        if self.audio is None:
            return
        try:
            if self.player.playing:
                self.player.pause()
            else:
                self.player.play(start=self.playhead_time)
        except PlaybackError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
        self._refresh_actions()

    def play_selected(self) -> None:
        if self.structure is None:
            return
        selection = self.selected_indices()
        index = selection[0] if selection else self.structure.index_at(self.playhead_time)
        last = selection[-1] if selection else index
        try:
            self.player.play(start=self.structure[index].start, end=self.structure[last].end)
        except PlaybackError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
        self._refresh_actions()

    def stop(self) -> None:
        self.player.stop()
        self._was_playing = False
        self._refresh_actions()

    def seek(self, seconds: float) -> None:
        if self.audio is None:
            return
        self.playhead_time = min(max(seconds, 0.0), self.audio.duration)
        self.player.seek(self.playhead_time)
        self._update_playhead()

    def _tick_playback(self) -> None:
        playing = self.player.playing
        if playing:
            self.playhead_time = self.player.position
            start, end = self.view
            if not start <= self.playhead_time <= end and self._drag_boundary is None:
                self._set_view(self.playhead_time, self.playhead_time + (end - start))
            self._update_playhead()
        elif self._was_playing:
            # Reached the end of the range: release the device, keep position.
            self.playhead_time = self.player.position
            try:
                self.player.pause()
            except PlaybackError:
                self.player.close()
            self._update_playhead()
            self._refresh_actions()
        self._was_playing = playing

    # ---------------------------------------------------------------- editing

    def selected_indices(self) -> list[int]:
        return sorted(int(item) for item in self.tree.selection())

    def select(self, indices: list[int]) -> None:
        self._updating_tree = True
        try:
            items = [str(i) for i in indices if self.tree.exists(str(i))]
            self.tree.selection_set(items)
            if items:
                self.tree.see(items[0])
        finally:
            self._updating_tree = False
        self._refresh_actions()
        self._schedule_redraw()

    def undo(self) -> None:
        if self.structure is not None and self.structure.undo():
            self._refresh_all()

    def redo(self) -> None:
        if self.structure is not None and self.structure.redo():
            self._refresh_all()

    def split_at(self, seconds: float) -> None:
        if self.structure is None:
            return
        self.structure.checkpoint()
        created = self.structure.split(seconds)
        if created is None:
            self.structure.undo()
            self.status.set("Troppo vicino a un confine esistente per dividere.")
            return
        self._refresh_all()
        self.select([created])

    def split_at_playhead(self) -> None:
        self.split_at(self.playhead_time)

    def _split_at_context(self) -> None:
        self.split_at(self._context_time)

    def _remove_left(self) -> None:
        if self.structure is None:
            return
        index = self.structure.index_at(self._context_time)
        if index == 0:
            return
        self.structure.checkpoint()
        merged = self.structure.remove_boundary(index)
        self._refresh_all()
        self.select([merged])

    def merge_selected(self) -> None:
        if self.structure is None:
            return
        selection = self.selected_indices()
        if len(selection) < 2:
            self.status.set("Seleziona almeno due sezioni adiacenti da unire.")
            return
        if selection != list(range(selection[0], selection[-1] + 1)):
            self.status.set("Si possono unire solo sezioni adiacenti.")
            return
        self.structure.checkpoint()
        merged = self.structure.merge(selection[0], selection[-1])
        self._refresh_all()
        self.select([merged])

    def rename_selected(self) -> None:
        if self.structure is None:
            return
        selection = self.selected_indices()
        if not selection:
            selection = [self.structure.index_at(self.playhead_time)]
        current = self.structure[selection[0]]
        choices = list(dict.fromkeys([*self.structure.labels(), *STANDARD_LABELS]))
        dialog = LabelDialog(
            self, "Rinomina sezione", current.label, choices, offer_group=len(selection) == 1
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return
        label, whole_group = dialog.result
        self.structure.checkpoint()
        for index in selection:
            self.structure.rename(index, label, whole_group=whole_group)
        self._refresh_all()
        self.select(selection)

    # ------------------------------------------------------------------- view

    def _set_view(self, start: float, end: float) -> None:
        if self.audio is None:
            return
        total = self.audio.duration
        span = min(max(end - start, min(MIN_VIEW_SECONDS, total)), total)
        start = min(max(start, 0.0), total - span)
        self.view = (start, start + span)
        self.scrollbar.set(start / total, (start + span) / total)
        self._schedule_redraw()

    def zoom(self, factor: float, around: float | None = None) -> None:
        if self.audio is None:
            return
        start, end = self.view
        span = end - start
        pivot = (
            around
            if around is not None
            else (self.playhead_time if start <= self.playhead_time <= end else (start + end) / 2)
        )
        ratio = (pivot - start) / span if span else 0.5
        new_span = span / factor
        new_start = pivot - ratio * new_span
        self._set_view(new_start, new_start + new_span)

    def zoom_all(self) -> None:
        if self.audio is not None:
            self._set_view(0.0, self.audio.duration)

    def _on_scrollbar(self, *args: str) -> None:
        if self.audio is None:
            return
        start, end = self.view
        span = end - start
        total = self.audio.duration
        if args[0] == "moveto":
            new_start = float(args[1]) * total
        elif args[0] == "scroll":
            step = span * (0.1 if args[2] == "units" else 0.9)
            new_start = start + int(args[1]) * step
        else:
            return
        self._set_view(new_start, new_start + span)

    # ---------------------------------------------------------------- drawing

    def _columns(self) -> int:
        return max(200, int(self.ax.bbox.width))

    def _schedule_redraw(self) -> None:
        if not self._redraw_scheduled:
            self._redraw_scheduled = True
            self.after_idle(self._redraw)

    def _redraw(self) -> None:
        self._redraw_scheduled = False
        if self._closing:
            return
        selected = self.selected_indices() if self.structure is not None else []
        structure = self.structure if self.audio is not None else None
        chords = self.analysis.chords if self.analysis is not None and structure else ()
        draw_structure(
            self.ax, self.envelope, structure, self.view, self._columns(), selected, chords
        )
        self._playhead_artist = self.ax.axvline(
            self.playhead_time, color=PLAYHEAD, linewidth=1.4, animated=True
        )
        self.canvas.draw()

    def _on_draw(self, _event: Any) -> None:
        self._background = self.canvas.copy_from_bbox(self.figure.bbox)
        self._blit_playhead()

    def _blit_playhead(self) -> None:
        if self._background is None or self._playhead_artist is None:
            return
        self.canvas.restore_region(self._background)
        if self.audio is not None:
            self._playhead_artist.set_xdata([self.playhead_time, self.playhead_time])
            self.ax.draw_artist(self._playhead_artist)
        self.canvas.blit(self.figure.bbox)

    def _update_playhead(self) -> None:
        self._blit_playhead()
        total = self.audio.duration if self.audio is not None else 0.0
        self.time_label.configure(
            text=f"{format_timestamp(self.playhead_time, 1)} / {format_timestamp(total, 1)}"
        )

    def _refresh_table(self) -> None:
        self._updating_tree = True
        try:
            self.tree.delete(*self.tree.get_children())
            if self.structure is None or self.audio is None:
                return
            for index, seg in enumerate(self.structure.segments):
                self.tree.insert(
                    "",
                    tk.END,
                    iid=str(index),
                    values=(
                        index + 1,
                        format_timestamp(seg.start, 1),
                        format_timestamp(seg.end, 1),
                        format_timestamp(seg.duration, 1),
                        seg.label,
                    ),
                )
        finally:
            self._updating_tree = False

    def _refresh_all(self) -> None:
        self._refresh_table()
        self._refresh_actions()
        if self.audio is not None:
            self._set_view(*self.view)
        self._update_playhead()
        self._schedule_redraw()

    def _refresh_actions(self) -> None:
        def state(enabled: bool) -> str:
            return tk.NORMAL if enabled else tk.DISABLED

        has_audio = self.audio is not None
        ready = has_audio and not self._busy
        selection = self.selected_indices() if self.structure is not None else []
        self.btn_open.configure(state=state(not self._busy))
        self.btn_analyze.configure(state=state(ready))
        self.btn_play.configure(
            state=state(has_audio), text="Pausa" if self.player.playing else "Play"
        )
        self.btn_play_segment.configure(state=state(has_audio))
        self.btn_stop.configure(state=state(has_audio))
        self.btn_split.configure(state=state(ready))
        self.btn_rename.configure(state=state(ready))
        self.btn_merge.configure(state=state(ready and len(selection) >= 2))
        for widget in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_all):
            widget.configure(state=state(has_audio))
        can_undo = bool(self.structure and self.structure.can_undo and ready)
        can_redo = bool(self.structure and self.structure.can_redo and ready)
        self._edit_menu.entryconfigure(0, state=state(can_undo))
        self._edit_menu.entryconfigure(1, state=state(can_redo))
        for entry in (3, 4, 5):
            self._edit_menu.entryconfigure(entry, state=state(ready))
        self._analysis_menu.entryconfigure(0, state=state(ready))
        for entry in range(8):
            self._export_menu.entryconfigure(entry, state=state(ready))
        for entry in (2, 3, 4):
            self._analysis_menu.entryconfigure(entry, state=state(not self._busy))

    # ------------------------------------------------------------ interaction

    def _grab_tolerance(self) -> float:
        start, end = self.view
        return GRAB_PIXELS * (end - start) / max(1.0, self.ax.bbox.width)

    def _on_tree_select(self, _event: Any) -> None:
        if self._updating_tree:
            return
        self._refresh_actions()
        self._schedule_redraw()

    def _on_press(self, event: Any) -> None:
        if self.structure is None or self.audio is None or event.xdata is None or self._busy:
            return
        self.canvas_widget.focus_set()
        time = float(event.xdata)
        if event.button == 3:
            self._context_time = time
            self.select([self.structure.index_at(time)])
            gui = event.guiEvent
            if gui is not None:
                self._context.tk_popup(gui.x_root, gui.y_root)
            return
        if event.button != 1:
            return
        boundary = self.structure.boundary_near(time, self._grab_tolerance())
        if boundary is not None and not event.dblclick:
            self.structure.checkpoint()
            self._drag_boundary = boundary
            return
        self.seek(time)
        self.select([self.structure.index_at(time)])
        if event.dblclick:
            self.rename_selected()

    def _on_motion(self, event: Any) -> None:
        if self.structure is None or self.audio is None:
            return
        if self._drag_boundary is not None:
            if event.xdata is not None:
                self.structure.move_boundary(self._drag_boundary, float(event.xdata))
                self._schedule_redraw()
            return
        near = event.xdata is not None and (
            self.structure.boundary_near(float(event.xdata), self._grab_tolerance()) is not None
        )
        self.canvas_widget.configure(cursor="sb_h_double_arrow" if near else "")

    def _on_release(self, _event: Any) -> None:
        if self._drag_boundary is not None:
            self._drag_boundary = None
            self._refresh_all()

    def _on_scroll(self, event: Any) -> None:
        if self.audio is None or event.xdata is None:
            return
        self.zoom(1.25 if event.button == "up" else 1 / 1.25, around=float(event.xdata))


def run(path: str | None = None) -> int:
    app = App()
    if path:
        app.after(100, lambda: app.open_file(path))
    app.mainloop()
    return 0
