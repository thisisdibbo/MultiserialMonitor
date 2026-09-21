import sys
import csv
import serial
import serial.tools.list_ports
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QComboBox, QLabel,
    QTableWidget, QTableWidgetItem, QFileDialog
)
from PyQt6.QtCore import QThread, pyqtSignal, QTimer


# =========================================================
# SERIAL THREAD (UNCHANGED)
# =========================================================
class SerialWorker(QThread):
    data_signal = pyqtSignal(str, str)  # port, value

    def __init__(self, port, baud=9600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = True
        self.ser = None

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2)

            buffer = ""

            while self.running:
                try:
                    data = self.ser.read(self.ser.in_waiting or 1).decode(errors="ignore")

                    buffer += data
                    buffer = buffer.replace("\r", "\n")

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()

                        if line:
                            parts = line.split()

                            if len(parts) > 0:
                                value = parts[0]

                                if any(c.isdigit() for c in value):
                                    self.data_signal.emit(self.port, value)

                except Exception as e:
                    self.data_signal.emit(self.port, f"ERR:{e}")

        except Exception as e:
            self.data_signal.emit(self.port, f"OPEN_ERR:{e}")

    def stop(self):
        self.running = False
        if self.ser:
            self.ser.close()


# =========================================================
# MAIN DASHBOARD
# =========================================================
class LoadCellDashboard(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("QLB9 Industrial Load Cell Dashboard")
        self.resize(1200, 700)

        # ---------------- DATA ----------------
        self.latest_data = {}
        self.threads = {}
        self.ports = set()

        # ✅ ONLY ADDITION: TIME-BASED STORAGE FOR CSV
        self.time_buffer = {}   # {time: {port: value}}

        # ---------------- CSV ----------------
        self.csv_file = open("loadcell_data.csv", "w", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.header_written = False

        self.init_ui()

        # ---------------- TIMERS ----------------
        self.scan_timer = QTimer()
        self.scan_timer.timeout.connect(self.scan_ports)
        self.scan_timer.start(2000)

        self.table_timer = QTimer()
        self.table_timer.timeout.connect(self.insert_row)
        self.table_timer.start(1000)

        self.csv_timer = QTimer()
        self.csv_timer.timeout.connect(self.write_csv)
        self.csv_timer.start(1000)

    # =========================================================
    # UI (UNCHANGED)
    # =========================================================
    def init_ui(self):
        layout = QVBoxLayout()

        top = QHBoxLayout()

        self.port_box = QComboBox()
        self.baud_box = QComboBox()
        self.baud_box.addItems(["9600", "19200", "38400", "57600", "115200"])

        btn_refresh_ports = QPushButton("Refresh Ports")
        btn_refresh_ports.clicked.connect(self.refresh_ports)

        btn_connect = QPushButton("Connect")
        btn_connect.clicked.connect(self.connect_port)

        btn_disconnect = QPushButton("Disconnect")
        btn_disconnect.clicked.connect(self.disconnect_port)

        btn_refresh_data = QPushButton("Refresh Data")
        btn_refresh_data.clicked.connect(self.refresh_data)

        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self.export_csv)

        top.addWidget(QLabel("Port"))
        top.addWidget(self.port_box)
        top.addWidget(QLabel("Baud"))
        top.addWidget(self.baud_box)
        top.addWidget(btn_refresh_ports)
        top.addWidget(btn_connect)
        top.addWidget(btn_disconnect)
        top.addWidget(btn_refresh_data)
        top.addWidget(btn_export)

        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["Time"])
        layout.addWidget(self.table)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget { background-color:#121212; color:white; }
            QTextEdit { background-color:#1e1e1e; color:#00ff88; }
            QTableWidget { background-color:#1b1b1b; color:white; }
            QPushButton { background-color:#333; padding:5px; }
            QComboBox { background-color:#222; color:white; }
        """)

    # =========================================================
    # PORTS (UNCHANGED)
    # =========================================================
    def refresh_ports(self):
        self.port_box.clear()
        for p in serial.tools.list_ports.comports():
            self.port_box.addItem(p.device)

    def scan_ports(self):
        self.ports = {p.device for p in serial.tools.list_ports.comports()}

    def connect_port(self):
        port = self.port_box.currentText()
        baud = int(self.baud_box.currentText())

        if port in self.threads:
            return

        worker = SerialWorker(port, baud)
        worker.data_signal.connect(self.update_data)
        worker.start()

        self.threads[port] = worker
        self.latest_data[port] = ""

        self.log_msg(f"[CONNECTED] {port}")

        self.update_headers()

    def disconnect_port(self):
        port = self.port_box.currentText()

        if port in self.threads:
            self.threads[port].stop()
            self.threads[port].wait()
            del self.threads[port]

            self.log_msg(f"[DISCONNECTED] {port}")

    # =========================================================
    # DATA UPDATE (FIXED FOR CSV MATRIX)
    # =========================================================
    def update_data(self, port, value):
        self.latest_data[port] = value

        # ✅ TIME-BASED MATRIX STORAGE
        t = datetime.now().strftime("%H:%M:%S")

        if t not in self.time_buffer:
            self.time_buffer[t] = {}

        self.time_buffer[t][port] = value

    # =========================================================
    # REFRESH (UNCHANGED)
    # =========================================================
    def refresh_data(self):
        self.latest_data.clear()
        self.time_buffer.clear()
        self.table.setRowCount(0)

        self.log_msg("[REFRESH] Data cleared")

    # =========================================================
    # TABLE HEADERS
    # =========================================================
    def update_headers(self):
        ports = sorted(self.latest_data.keys())
        self.table.setColumnCount(len(ports) + 1)
        self.table.setHorizontalHeaderLabels(["Time"] + ports)

    # =========================================================
    # TABLE ROWS (UNCHANGED)
    # =========================================================
    def insert_row(self):
        t = datetime.now().strftime("%H:%M:%S")

        ports = sorted(self.latest_data.keys())

        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(t))

        for i, p in enumerate(ports):
            self.table.setItem(row, i + 1, QTableWidgetItem(str(self.latest_data.get(p, ""))))

        self.table.scrollToBottom()

    # =========================================================
    # LIVE CSV (UNCHANGED STYLE)
    # =========================================================
    def write_csv(self):
        t = datetime.now().strftime("%H:%M:%S")

        ports = sorted(self.latest_data.keys())

        if not self.header_written:
            self.csv_writer.writerow(["Time"] + ports)
            self.header_written = True

        row = [t] + [self.latest_data.get(p, "") for p in ports]

        self.csv_writer.writerow(row)
        self.csv_file.flush()

    # =========================================================
    # ✅ FINAL FIX: WIDE FORMAT EXPORT (YOUR REQUIRED OUTPUT)
    # =========================================================
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")

        if not path:
            return

        ports = sorted(self.latest_data.keys())

        with open(path, "w", newline="") as f:
            writer = csv.writer(f)

            # HEADER
            writer.writerow(["Time"] + ports)

            # ROWS (MATRIX FORMAT)
            for t in sorted(self.time_buffer.keys()):
                row = [t]

                for p in ports:
                    row.append(self.time_buffer[t].get(p, ""))

                writer.writerow(row)

        self.log_msg("[EXPORT] CSV saved in correct format")

    # =========================================================
    # LOG
    # =========================================================
    def log_msg(self, msg):
        self.log.append(msg)


# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoadCellDashboard()
    window.show()
    sys.exit(app.exec())