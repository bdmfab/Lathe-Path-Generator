import os
import json
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dxf_parser import extract_profile_from_dxf
from gcode_engine import calculate_roughing_moves, export_linuxcnc_file, densify_profile
from thread_engine import (ISO_COARSE_PRESETS, build_thread_program, export_thread_file,
                           thread_geometry, estimate_pass_count)

SETTINGS_FILE = "lathe_cam_settings.json"

# G-code review-panel syntax highlighting: color a whole word by its leading
# letter (G00 -> green, M03 -> blue, Z-10.100 -> red), not just the letter
# itself. The negative lookbehind keeps this from matching mid-word (e.g.
# the "M" in a comment word), only a fresh G/M/Z followed by a number.
GCODE_HIGHLIGHT_PATTERNS = [
    (re.compile(r'(?<![A-Za-z0-9.])G-?\d+(?:\.\d+)?', re.IGNORECASE), "g_tag"),
    (re.compile(r'(?<![A-Za-z0-9.])M-?\d+(?:\.\d+)?', re.IGNORECASE), "m_tag"),
    (re.compile(r'(?<![A-Za-z0-9.])Z-?\d+(?:\.\d+)?', re.IGNORECASE), "z_tag"),
]

class DxfVisualizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("QCAD Lathe Visualizer & CAM Engine")
        self.root.geometry("1300x740")
        self.root.resizable(False, False)
        
        self.profile_data = []
        self.toolpath_moves = []
        self.selected_file_path = ""
        
        self.stock_dia = tk.StringVar(value="12.0")
        self.doc_val = tk.StringVar(value="1.0")
        self.finish_allow = tk.StringVar(value="0.2")
        self.nose_radius = tk.StringVar(value="0.2")

        self.rpm_val = tk.StringVar(value="1000")
        self.css_val = tk.StringVar(value="250")
        self.fpm_val = tk.StringVar(value="100.0")
        self.fpr_val = tk.StringVar(value="0.12")
        self.max_rpm_val = tk.StringVar(value="2500")
        self.use_css = tk.BooleanVar(value=True)
        self.use_fpr = tk.BooleanVar(value=True)

        # G76 thread tab
        self.th_type = tk.StringVar(value="External")
        self.th_preset = tk.StringVar(value="")
        self.th_major = tk.StringVar(value="10.0")
        self.th_pitch = tk.StringVar(value="1.5")
        self.th_length = tk.StringVar(value="15.0")
        self.th_z_start = tk.StringVar(value="5.0")
        self.th_clear = tk.StringVar(value="2.0")
        self.th_depth = tk.StringVar(value="0")
        self.th_j = tk.StringVar(value="0.15")
        self.th_r = tk.StringVar(value="1.5")
        self.th_q = tk.StringVar(value="29.5")
        self.th_h = tk.StringVar(value="2")
        self.th_e = tk.StringVar(value="0")
        self.th_l = tk.StringVar(value="0 - None")
        self.th_rpm = tk.StringVar(value="400")

        self._load_settings()
        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _string_setting_vars(self):
        """Every entry field that should persist between runs."""
        return {
            "stock_dia": self.stock_dia, "doc_val": self.doc_val,
            "finish_allow": self.finish_allow, "nose_radius": self.nose_radius,
            "rpm_val": self.rpm_val, "css_val": self.css_val,
            "fpm_val": self.fpm_val, "fpr_val": self.fpr_val,
            "max_rpm_val": self.max_rpm_val,
            "th_type": self.th_type, "th_major": self.th_major,
            "th_pitch": self.th_pitch, "th_length": self.th_length,
            "th_z_start": self.th_z_start, "th_clear": self.th_clear,
            "th_depth": self.th_depth, "th_j": self.th_j, "th_r": self.th_r,
            "th_q": self.th_q, "th_h": self.th_h, "th_e": self.th_e,
            "th_l": self.th_l, "th_rpm": self.th_rpm,
        }

    def _bool_setting_vars(self):
        return {"use_css": self.use_css, "use_fpr": self.use_fpr}

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return  # no saved settings yet, or the file is unreadable - keep the defaults
        for key, var in self._string_setting_vars().items():
            if key in data:
                var.set(data[key])
        for key, var in self._bool_setting_vars().items():
            if key in data:
                var.set(bool(data[key]))

    def _save_settings(self):
        data = {key: var.get() for key, var in self._string_setting_vars().items()}
        data.update({key: var.get() for key, var in self._bool_setting_vars().items()})
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass  # non-fatal - just means this run's values won't be remembered

    def _on_close(self):
        self._save_settings()
        self.root.destroy()
        
    def build_ui(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        self.profile_tab = ttk.Frame(self.notebook)
        self.thread_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.profile_tab, text="  Profile / Roughing  ")
        self.notebook.add(self.thread_tab, text="  G76 Thread  ")
        self._build_thread_tab()

        tf = ttk.Frame(self.profile_tab, padding="10")
        tf.pack(fill=tk.X, side=tk.TOP)
        
        ttk.Button(tf, text="📁 Open DXF", command=self.browse_file).grid(row=0, column=0, rowspan=2, padx=(0,10), sticky="ns")
        
        ttk.Label(tf, text="Stock:").grid(row=0, column=1, sticky=tk.W)
        ttk.Entry(tf, textvariable=self.stock_dia, width=6).grid(row=0, column=2, padx=(0,5))
        
        ttk.Label(tf, text="Doc:").grid(row=0, column=3, sticky=tk.W)
        ttk.Entry(tf, textvariable=self.doc_val, width=6).grid(row=0, column=4, padx=(0,5))
        
        ttk.Label(tf, text="Allow:").grid(row=0, column=5, sticky=tk.W)
        ttk.Entry(tf, textvariable=self.finish_allow, width=6).grid(row=0, column=6, padx=(0,5))

        ttk.Label(tf, text="Nose R:").grid(row=0, column=7, sticky=tk.W)
        ttk.Entry(tf, textvariable=self.nose_radius, width=5).grid(row=0, column=8, padx=(0,5))

        ttk.Label(tf, text="Max RPM:").grid(row=0, column=9, sticky=tk.W)
        ttk.Entry(tf, textvariable=self.max_rpm_val, width=6).grid(row=0, column=10, padx=(0,5))

        ttk.Button(tf, text="🔄 Refresh", command=self.process_geometry).grid(row=0, column=13, rowspan=2, padx=5, sticky="ns")
        ttk.Button(tf, text="⚡ Export G-Code", command=self.trigger_gcode_export).grid(row=0, column=14, rowspan=2, sticky="ns")

        ttk.Label(tf, text="RPM:").grid(row=1, column=1, sticky=tk.W, pady=(5,0))
        ttk.Entry(tf, textvariable=self.rpm_val, width=6).grid(row=1, column=2, padx=(0,5), pady=(5,0))

        ttk.Label(tf, text="CSS (S):").grid(row=1, column=3, sticky=tk.W, pady=(5,0))
        ttk.Entry(tf, textvariable=self.css_val, width=6).grid(row=1, column=4, padx=(0,5), pady=(5,0))

        ttk.Checkbutton(tf, text="Use CSS", variable=self.use_css).grid(row=1, column=5, columnspan=2, sticky=tk.W, padx=(0,10), pady=(5,0))

        ttk.Label(tf, text="FPM:").grid(row=1, column=7, sticky=tk.W, pady=(5,0))
        ttk.Entry(tf, textvariable=self.fpm_val, width=6).grid(row=1, column=8, padx=(0,5), pady=(5,0))

        ttk.Label(tf, text="FPR:").grid(row=1, column=9, sticky=tk.W, pady=(5,0))
        ttk.Entry(tf, textvariable=self.fpr_val, width=6).grid(row=1, column=10, padx=(0,5), pady=(5,0))

        ttk.Checkbutton(tf, text="Use FPR", variable=self.use_fpr).grid(row=1, column=11, columnspan=2, sticky=tk.W, pady=(5,0))

        self.status_lbl = ttk.Label(tf, text="Status: Ready", foreground="gray")
        self.status_lbl.grid(row=2, column=0, columnspan=15, sticky=tk.W, pady=(5,0))
        
        body = ttk.Frame(self.profile_tab)
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))

        canvas_frame = ttk.LabelFrame(body, text=" Live Path Preview (Red=G00, Green=G01, Cyan=Part Shape) ", padding="10")
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.canvas = tk.Canvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        gcode_frame = ttk.LabelFrame(body, text=" G-Code Review ", padding="5")
        gcode_frame.pack(side=tk.RIGHT, fill=tk.Y)
        gcode_frame.pack_propagate(False)
        gcode_frame.configure(width=380)

        text_container = ttk.Frame(gcode_frame)
        text_container.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.gcode_text = tk.Text(text_container, wrap="none", bg="#1e1e1e", fg="#dddddd",
                                   insertbackground="#dddddd", font=("Courier New", 9),
                                   yscrollcommand=scrollbar.set, state="disabled")
        self.gcode_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.gcode_text.yview)

        self.gcode_text.tag_configure("g_tag", foreground="#33ff33")
        self.gcode_text.tag_configure("m_tag", foreground="#4da6ff")
        self.gcode_text.tag_configure("z_tag", foreground="#ff5555")

    def _show_gcode(self, text, widget=None):
        """Load g-code text into a review panel with G/M/Z syntax highlighting.
        Defaults to the profile tab's panel."""
        widget = widget or self.gcode_text
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        for _, tag in GCODE_HIGHLIGHT_PATTERNS:
            widget.tag_remove(tag, "1.0", "end")
        for pattern, tag in GCODE_HIGHLIGHT_PATTERNS:
            for m in pattern.finditer(text):
                widget.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        widget.config(state="disabled")

    # ------------------------------------------------------------------
    # G76 thread tab
    # ------------------------------------------------------------------
    def _thread_vars(self):
        return [self.th_type, self.th_major, self.th_pitch, self.th_length,
                self.th_z_start, self.th_clear, self.th_depth, self.th_j,
                self.th_r, self.th_q, self.th_h, self.th_e, self.th_l, self.th_rpm]

    def _build_thread_tab(self):
        body = ttk.Frame(self.thread_tab)
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        left = ttk.LabelFrame(body, text=" Thread Parameters ", padding="10")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        def label(r, text):
            ttk.Label(left, text=text).grid(row=r, column=0, sticky=tk.W, pady=2)

        def hint(r, text):
            ttk.Label(left, text=text, foreground="gray").grid(
                row=r, column=2, sticky=tk.W, padx=(8, 0))

        def entry(r, text, var, tip=""):
            label(r, text)
            ttk.Entry(left, textvariable=var, width=10).grid(
                row=r, column=1, sticky=tk.W, padx=(8, 0), pady=2)
            if tip:
                hint(r, tip)

        label(0, "Type:")
        ttk.Combobox(left, textvariable=self.th_type, values=["External", "Internal"],
                     state="readonly", width=9).grid(row=0, column=1, sticky=tk.W, padx=(8, 0), pady=2)

        label(1, "ISO preset:")
        preset = ttk.Combobox(left, textvariable=self.th_preset, width=9, state="readonly",
                              values=[p[0] for p in ISO_COARSE_PRESETS])
        preset.grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=2)
        preset.bind("<<ComboboxSelected>>", self._on_thread_preset)
        hint(1, "fills major dia + pitch")

        entry(2, "Major dia (D):", self.th_major, "mm, nominal")
        entry(3, "Pitch (P):", self.th_pitch, "mm/rev")
        entry(4, "Thread length:", self.th_length, "mm, from Z0 toward chuck")
        entry(5, "Start Z (lead-in):", self.th_z_start, "mm, room for Z to get up to speed")
        entry(6, "Radial clearance:", self.th_clear, "mm, drive line offset (sets I)")
        entry(7, "Depth K (0 = auto):", self.th_depth, "auto: 0.6134P ext / 0.5413P int")
        entry(8, "First cut (J):", self.th_j, "mm, radial")
        entry(9, "Degression (R):", self.th_r, "1 = const depth, 2 = const area")
        entry(10, "Compound (Q):", self.th_q, "29.5 for 60\u00b0 thread, 0 = plunge")
        entry(11, "Spring passes (H):", self.th_h)
        entry(12, "Taper dist (E):", self.th_e, "mm along drive line")

        label(13, "Taper ends (L):")
        ttk.Combobox(left, textvariable=self.th_l, state="readonly", width=9,
                     values=["0 - None", "1 - Entry", "2 - Exit", "3 - Both"]).grid(
            row=13, column=1, sticky=tk.W, padx=(8, 0), pady=2)

        entry(14, "Thread RPM:", self.th_rpm, "constant RPM (G97)")

        btns = ttk.Frame(left)
        btns.grid(row=15, column=0, columnspan=3, sticky=tk.W, pady=(12, 6))
        ttk.Button(btns, text="\U0001F504 Preview", command=lambda: self.update_thread_preview()).pack(side=tk.LEFT)
        ttk.Button(btns, text="\u26a1 Export G-Code", command=self.export_thread_gcode).pack(side=tk.LEFT, padx=(8, 0))

        self.th_info = ttk.Label(left, text="", justify=tk.LEFT, wraplength=420)
        self.th_info.grid(row=16, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

        right = ttk.LabelFrame(body, text=" G-Code Review ", padding="5")
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        container = ttk.Frame(right)
        container.pack(fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(container)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.thread_gcode_text = tk.Text(container, wrap="none", bg="#1e1e1e", fg="#dddddd",
                                         insertbackground="#dddddd", font=("Courier New", 9),
                                         yscrollcommand=sb.set, state="disabled")
        self.thread_gcode_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.thread_gcode_text.yview)
        self.thread_gcode_text.tag_configure("g_tag", foreground="#33ff33")
        self.thread_gcode_text.tag_configure("m_tag", foreground="#4da6ff")
        self.thread_gcode_text.tag_configure("z_tag", foreground="#ff5555")

        # Live preview: regenerate whenever any field changes.
        for var in self._thread_vars():
            var.trace_add("write", lambda *_: self.update_thread_preview(silent=True))
        self.update_thread_preview(silent=True)

    def _on_thread_preset(self, _event=None):
        for label_text, dia, pitch in ISO_COARSE_PRESETS:
            if label_text == self.th_preset.get():
                self.th_major.set(f"{dia:g}")
                self.th_pitch.set(f"{pitch:g}")
                break

    def _read_thread_params(self):
        try:
            return dict(
                external=(self.th_type.get() == "External"),
                major_dia=float(self.th_major.get()),
                pitch=float(self.th_pitch.get()),
                length=float(self.th_length.get()),
                z_start=float(self.th_z_start.get()),
                clearance=float(self.th_clear.get()),
                depth_override=float(self.th_depth.get()),
                first_cut=float(self.th_j.get()),
                degression=float(self.th_r.get()),
                compound_angle=float(self.th_q.get()),
                spring_passes=int(float(self.th_h.get())),
                taper_dist=float(self.th_e.get()),
                taper_ends=int(self.th_l.get().strip()[0]),
                rpm=float(self.th_rpm.get()),
            )
        except (ValueError, IndexError):
            raise ValueError("All thread entries must be valid numbers.")

    def update_thread_preview(self, silent=False):
        try:
            params = self._read_thread_params()
            text = build_thread_program(**params)
            geo = thread_geometry(params["external"], params["major_dia"], params["pitch"],
                                  params["clearance"], params["depth_override"])
        except Exception as e:
            if silent:
                self.th_info.config(text=str(e), foreground="#cc3333")
            else:
                messagebox.showerror("Error", str(e))
            return
        self._show_gcode(text, widget=self.thread_gcode_text)

        passes = estimate_pass_count(params["first_cut"], geo["k"], params["degression"])
        if params["external"]:
            size_line = f"Pre-turn OD: {geo['peak_dia']:.3f}   Root dia: {geo['root_dia']:.3f}"
        else:
            size_line = f"Pre-bore dia: {geo['peak_dia']:.3f}   Root dia: {geo['root_dia']:.3f}"
        self.th_info.config(
            text=(f"{size_line}\n"
                  f"Depth K: {geo['k']:.3f}   Drive line: X{geo['drive_dia']:.3f}   I{geo['i']:.3f}\n"
                  f"~{passes} cutting passes + {params['spring_passes']} spring"),
            foreground="gray")

    def export_thread_gcode(self):
        try:
            params = self._read_thread_params()
            build_thread_program(**params)  # validate before asking for a filename
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return

        kind = "ext" if params["external"] else "int"
        initial = f"thread_M{params['major_dia']:g}x{params['pitch']:g}_{kind}.ngc"
        start_dir = os.path.dirname(self.selected_file_path) if self.selected_file_path else os.getcwd()
        out_path = filedialog.asksaveasfilename(
            defaultextension=".ngc", initialfile=initial, initialdir=start_dir,
            filetypes=[("LinuxCNC G-Code", "*.ngc"), ("All Files", "*.*")])
        if not out_path:
            return
        try:
            text = export_thread_file(out_path, **params)
            self._show_gcode(text, widget=self.thread_gcode_text)
            self._save_settings()
            messagebox.showinfo("Success", f"Thread G-Code written to:\n{os.path.basename(out_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Export Failed: {str(e)}")
        
    def browse_file(self):
        s = filedialog.askopenfilename(filetypes=[("DXF Files", "*.dxf")])
        if s:
            self.selected_file_path = s
            self.process_geometry()
            
    def process_geometry(self):
        if not self.selected_file_path: return
        try:
            stk = float(self.stock_dia.get())
            doc, alw = float(self.doc_val.get()), float(self.finish_allow.get())
            nrad = float(self.nose_radius.get())
            
            self.profile_data = extract_profile_from_dxf(self.selected_file_path)
            self.toolpath_moves = calculate_roughing_moves(self.profile_data, stk, doc, alw, nose_radius=nrad)
            self.status_lbl.config(text=f"Showing: {os.path.basename(self.selected_file_path)}", foreground="green")
            self.draw_canvas()
        except Exception as e:
            messagebox.showerror("Error", str(e))
            
    def trigger_gcode_export(self):
        if not self.selected_file_path:
            messagebox.showwarning("Error", "Load a DXF file first.")
            return
        try:
            stk, doc = float(self.stock_dia.get()), float(self.doc_val.get())
            alw = float(self.finish_allow.get())
            nrad = float(self.nose_radius.get())
            rpm = float(self.rpm_val.get())
            css = float(self.css_val.get())
            fpm = float(self.fpm_val.get())
            fpr = float(self.fpr_val.get())
            max_rpm = float(self.max_rpm_val.get())
        except ValueError:
            messagebox.showerror("Error", "All entries must be valid numbers.")
            return
            
        f_dir = os.path.dirname(self.selected_file_path)
        b_name, _ = os.path.splitext(os.path.basename(self.selected_file_path))
        out_file = os.path.join(f_dir, b_name + ".ngc")
        
        try:
            # Re-verify clean profile coordinates map
            pts = extract_profile_from_dxf(self.selected_file_path)
            export_linuxcnc_file(out_file, pts, stk, doc, alw,
                                  nose_radius=nrad,
                                  use_css=self.use_css.get(), css_speed=css, rpm=rpm,
                                  use_fpr=self.use_fpr.get(), fpr_feed=fpr, fpm_feed=fpm,
                                  max_rpm=max_rpm)
            with open(out_file, "r") as f:
                self._show_gcode(f.read())
            self._save_settings()
            messagebox.showinfo("Success", f"G-Code written directly to folder:\n{b_name}.ngc")
        except Exception as e:
            messagebox.showerror("Error", f"Export Failed: {str(e)}")

    def _draw_h_dimension(self, x1, x2, y, value):
        """Horizontal dimension line with end ticks, below the part."""
        lo, hi = min(x1, x2), max(x1, x2)
        tick = 6
        self.canvas.create_line(lo, y - tick, lo, y + tick, fill="#ffcc00")
        self.canvas.create_line(hi, y - tick, hi, y + tick, fill="#ffcc00")
        self.canvas.create_line(lo, y, hi, y, fill="#ffcc00")
        self.canvas.create_text((lo + hi) / 2, y + 13, text=f"{value:.3f}",
                                 fill="#ffcc00", font=("TkDefaultFont", 9))

    def _draw_v_dimension(self, y1, y2, x, value):
        """Vertical dimension line with end ticks, left of the part."""
        lo, hi = min(y1, y2), max(y1, y2)
        tick = 6
        self.canvas.create_line(x - tick, lo, x + tick, lo, fill="#ffcc00")
        self.canvas.create_line(x - tick, hi, x + tick, hi, fill="#ffcc00")
        self.canvas.create_line(x, lo, x, hi, fill="#ffcc00")
        self.canvas.create_text(x - 15, (lo + hi) / 2, text=f"\u2300{value:.3f}",
                                 fill="#ffcc00", font=("TkDefaultFont", 9), angle=90)

    def draw_canvas(self):
        self.canvas.delete("all")
        c_w, c_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if c_w < 10: c_w, c_h = 760, 480
        if not self.profile_data:
            return
        
        all_z = [pt["z"] for pt in self.profile_data] + [m["z"] for m in self.toolpath_moves]
        all_x = [pt["dia"] for pt in self.profile_data] + [m["x"] for m in self.toolpath_moves]
        min_z, max_z = min(all_z), max(all_z)
        min_x, max_x = 0.0, max(all_x)
        
        span_z = max_z - min_z if (max_z - min_z) != 0 else 1.0
        span_x = max_x - min_x if (max_x - min_x) != 0 else 1.0

        # Extra gutters (vs. a plain pad) reserve room for the dimension
        # lines/text drawn along the bottom and left of the plot area.
        pad_top, pad_right = 30, 30
        pad_bottom, pad_left = 55, 65
        p_w = c_w - pad_left - pad_right
        p_h = c_h - pad_top - pad_bottom
        
        def to_pix(z, dia):
            px = pad_left + ((z - min_z) / span_z) * p_w
            py = (c_h - pad_bottom) - ((dia - min_x) / span_x) * p_h
            return px, py
            
        base_y = to_pix(min_z, 0)[1]
        self.canvas.create_line(pad_left, base_y, c_w - pad_right, base_y, fill="#444444", dash=(4,4))
        
        if self.toolpath_moves:
            px, py = to_pix(self.toolpath_moves[0]["z"], self.toolpath_moves[0]["x"])
            for m in self.toolpath_moves[1:]:
                nx, ny = to_pix(m["z"], m["x"])
                col = "#ff3333" if m["type"] == "G00" else "#33ff33"
                self.canvas.create_line(px, py, nx, ny, fill=col, width=1)
                px, py = nx, ny
                
        smooth_profile = densify_profile(self.profile_data)
        for i in range(len(smooth_profile) - 1):
            x1, y1 = to_pix(smooth_profile[i]["z"], smooth_profile[i]["dia"])
            x2, y2 = to_pix(smooth_profile[i+1]["z"], smooth_profile[i+1]["dia"])
            self.canvas.create_line(x1, y1, x2, y2, fill="#00ffff", width=3)

        # Part-length dimension along the bottom, and part-diameter
        # dimension along the left, for a quick visual sanity check.
        part_min_z = min(pt["z"] for pt in self.profile_data)
        part_max_z = max(pt["z"] for pt in self.profile_data)
        part_max_dia = max(pt["dia"] for pt in self.profile_data)

        x_at_min_z, _ = to_pix(part_min_z, 0)
        x_at_max_z, _ = to_pix(part_max_z, 0)
        self._draw_h_dimension(x_at_min_z, x_at_max_z, c_h - pad_bottom + 20,
                                abs(part_max_z - part_min_z))

        _, y_at_zero_dia = to_pix(part_min_z, 0)
        _, y_at_max_dia = to_pix(part_min_z, part_max_dia)
        self._draw_v_dimension(y_at_zero_dia, y_at_max_dia, pad_left - 20, part_max_dia)

if __name__ == "__main__":
    app_root = tk.Tk()
    app = DxfVisualizerApp(app_root)
    app_root.update()
    app_root.mainloop()