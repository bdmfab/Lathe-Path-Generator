import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from dxf_parser import extract_profile_from_dxf
from gcode_engine import calculate_roughing_moves, export_linuxcnc_file, densify_profile

class DxfVisualizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("QCAD Lathe Visualizer & CAM Engine")
        self.root.geometry("920x700")
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
        self.use_css = tk.BooleanVar(value=True)
        self.use_fpr = tk.BooleanVar(value=True)

        self.build_ui()
        
    def build_ui(self):
        tf = ttk.Frame(self.root, padding="10")
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
        
        canvas_frame = ttk.LabelFrame(self.root, text=" Live Path Preview (Red=G00, Green=G01, Cyan=Part Shape) ", padding="10")
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        self.canvas = tk.Canvas(canvas_frame, bg="#1e1e1e", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
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
                                  use_fpr=self.use_fpr.get(), fpr_feed=fpr, fpm_feed=fpm)
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