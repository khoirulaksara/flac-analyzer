import sys
import os
import threading
import shutil
import webbrowser
import numpy as np
import librosa
import librosa.display
import matplotlib.pyplot as plt
from mutagen import File as MutagenFile
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from PyQt6.QtWidgets import (QApplication, QMainWindow, QLabel, QVBoxLayout, 
                             QWidget, QProgressBar, QTableWidget, QTableWidgetItem,
                             QPushButton, QHBoxLayout, QHeaderView, QFrame, QMenu, QFileDialog,
                             QAbstractItemView)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QAction

class AcousticUltraFinal(QMainWindow):
    analysis_finished = pyqtSignal(int, dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FLAC Analyzer")
        self.setFixedSize(1150, 880)
        self.setAcceptDrops(True)

        self.spectrum_cache = {}
        self.processed_files = set()
        self.init_ui()
        self.apply_styles()
        self.analysis_finished.connect(self.finalize_row)

    def init_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(25, 25, 25, 25)

        # Header & Utility Toolbar
        header_box = QHBoxLayout()
        self.title = QLabel("FLAC Analyzer")
        self.title.setStyleSheet("font-size: 24px; font-weight: 800; color: #f8fafc;")
        
        self.organize_btn = QPushButton("Organize Suspect Files")
        self.organize_btn.clicked.connect(self.auto_organize)
        
        header_box.addWidget(self.title)
        header_box.addStretch()
        header_box.addWidget(self.organize_btn)

        # Drop Zone
        self.drop_frame = QFrame()
        self.drop_frame.setObjectName("dropFrame")
        self.drop_layout = QVBoxLayout(self.drop_frame)
        self.drop_label = QLabel("Drop FLAC/WAV/APE/M4A Files for Analysis")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_layout.addWidget(self.drop_label)
        self.drop_frame.setFixedHeight(90)

        # Table with Deep Metadata
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["FILE NAME", "TECH SPECS", "ENCODER", "STATUS", "CUTOFF", "PATH"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setColumnHidden(5, True) 
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemClicked.connect(self.update_visualizer)

        # Spectrogram Panel
        self.spec_card = QFrame()
        self.spec_card.setObjectName("specCard")
        self.spec_vbox = QVBoxLayout(self.spec_card)
        
        # Matplotlib Config for Dark Mode Visibility
        plt.rcParams.update({
            "text.color": "white", "axes.labelcolor": "white",
            "xtick.color": "#94a3b8", "ytick.color": "#94a3b8"
        })
        
        self.figure, self.ax = plt.subplots(figsize=(6, 3))
        self.figure.patch.set_facecolor('#1e293b')
        self.canvas = FigureCanvas(self.figure)
        self.spec_vbox.addWidget(self.canvas)
        self.ax.axis('off')

        # Footer
        footer_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.btn_clear = QPushButton("Reset Session")
        self.btn_clear.clicked.connect(self.reset_session)
        
        footer_layout.addWidget(self.progress_bar)
        footer_layout.addSpacing(20)
        footer_layout.addWidget(self.btn_clear)

        self.main_layout.addLayout(header_box)
        self.main_layout.addWidget(self.drop_frame)
        self.main_layout.addWidget(self.table)
        self.main_layout.addWidget(self.spec_card)
        self.main_layout.addLayout(footer_layout)

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            #dropFrame { background-color: #1e293b; border: 2px dashed #38bdf8; border-radius: 12px; color: #94a3b8; font-weight: 600; }
            QTableWidget { background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; color: #e2e8f0; alternate-background-color: #161e2e; }
            QHeaderView::section { background-color: #334155; color: #38bdf8; padding: 12px; border: none; font-size: 10px; font-weight: 800; }
            #specCard { background-color: #1e293b; border-radius: 15px; border: 1px solid #334155; }
            QPushButton { background-color: #38bdf8; color: #0f172a; border-radius: 8px; padding: 8px 15px; font-weight: bold; }
            QPushButton:hover { background-color: #7dd3fc; }
        """)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.accept()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for f in files:
            if f.lower().endswith(('.flac', '.wav', '.m4a', '.ape')) and f not in self.processed_files:
                self.processed_files.add(f)
                self.start_analysis(f)

    def start_analysis(self, path):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for i in range(5): self.table.setItem(row, i, QTableWidgetItem("..."))
        self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(path)))
        self.table.setItem(row, 5, QTableWidgetItem(path))
        threading.Thread(target=self.run_forensics, args=(path, row), daemon=True).start()

    def run_forensics(self, path, row):
        try:
            # 1. Deep Metadata & Encoder Check
            audio = MutagenFile(path)
            bitrate = f"{int(audio.info.bitrate/1000)}k" if hasattr(audio.info, 'bitrate') else "VBR"
            specs = f"{audio.info.sample_rate/1000}kHz / {getattr(audio.info, 'bits_per_sample', 16)}bit"
            
            # Encoder Detection (mencari sisa-sisa kompresi)
            encoder = "Original/Unknown"
            if audio.tags:
                tags_str = str(audio.tags).lower()
                if "lame" in tags_str or "lavf" in tags_str: encoder = "Potential Lossy Conv"
                elif "itunes" in tags_str: encoder = "iTunes Rip"

            # 2. Spectral Analysis
            y, sr = librosa.load(path, sr=None, duration=15, offset=30)
            S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
            S_db = librosa.power_to_db(S, ref=np.max)

            stft = np.abs(librosa.stft(y))
            db_spec = librosa.amplitude_to_db(np.mean(stft, axis=1), ref=np.max)
            freqs = librosa.fft_frequencies(sr=sr)
            cutoff_idx = np.where(db_spec > -52)[0]
            cutoff_f = freqs[cutoff_idx[-1]] if len(cutoff_idx) > 0 else 0

            # Classification
            if cutoff_f >= 19800: status, color = "PRO LOSSLESS", "#22c55e"
            elif cutoff_f >= 17200: status, color = "MASTERING LIMIT", "#f59e0b"
            else: status, color = "FAKE / UPSCALED", "#ef4444"

            res = {"specs": specs, "status": status, "color": color, "cutoff": f"{cutoff_f/1000:.1f}kHz", 
                   "S_db": S_db, "sr": sr, "path": path, "encoder": encoder}
            self.spectrum_cache[row] = res
            self.analysis_finished.emit(row, res)
        except:
            self.analysis_finished.emit(row, {"status": "ERROR", "color": "#ef4444"})

    @pyqtSlot(int, dict)
    def finalize_row(self, row, data):
        self.table.item(row, 1).setText(data.get("specs"))
        self.table.item(row, 2).setText(data.get("encoder"))
        self.table.item(row, 3).setText(data.get("status"))
        self.table.item(row, 3).setForeground(QColor(data.get("color")))
        self.table.item(row, 4).setText(data.get("cutoff"))
        self.progress_bar.setValue(100)

    def update_visualizer(self, item):
        row = item.row()
        if row in self.spectrum_cache:
            d = self.spectrum_cache[row]
            self.ax.clear()
            self.ax.axis('on')
            librosa.display.specshow(d['S_db'], sr=d['sr'], x_axis='time', y_axis='mel', ax=self.ax, cmap='magma')
            self.ax.set_title(f"Spectral Analysis: {os.path.basename(d['path'])}", color='white', pad=10)
            self.ax.tick_params(colors='white', labelsize=8)
            self.figure.tight_layout()
            self.canvas.draw()

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        file_name = self.table.item(row, 0).text()
        
        menu = QMenu()
        search_mb = QAction("Check Mastering (MusicBrainz)", self)
        search_mb.triggered.connect(lambda: webbrowser.open(f"https://musicbrainz.org/search?query={file_name}&type=release"))
        
        search_disc = QAction("Check Album (Discogs)", self)
        search_disc.triggered.connect(lambda: webbrowser.open(f"https://www.discogs.com/search/?q={file_name}&type=release"))
        
        open_loc = QAction("Open Folder", self)
        open_loc.triggered.connect(lambda: os.startfile(os.path.dirname(self.table.item(row, 5).text())))
        
        menu.addActions([search_mb, search_disc, open_loc])
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def auto_organize(self):
        target = QFileDialog.getExistingDirectory(self, "Select Destination")
        if not target: return
        log_folder = os.path.join(target, "_SUSPECTED_FAKE")
        if not os.path.exists(log_folder): os.makedirs(log_folder)
        
        for row in range(self.table.rowCount()):
            if "FAKE" in self.table.item(row, 3).text():
                shutil.copy(self.table.item(row, 5).text(), log_folder)
        self.title.setText("Cleanup Finished!")

    def reset_session(self):
        self.table.setRowCount(0)
        self.processed_files.clear()
        self.ax.clear()
        self.ax.axis('off')
        self.canvas.draw()
        self.progress_bar.setValue(0)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AcousticUltraFinal()
    window.show()
    sys.exit(app.exec())