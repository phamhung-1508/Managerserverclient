import sys
import os
import socket
import threading
import json
import sqlite3
import hashlib
import winreg
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QCheckBox, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor

SERVER_PORT = 9999
DB_NAME = "master_users.db"
APP_NAME = "Mir4MasterManager"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT
        )
    ''')
    conn.commit()
    conn.close()

def hash_pw(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def register_user(username, password):
    if not username or not password:
        return False, "Tài khoản và mật khẩu không được rỗng!"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users VALUES (?, ?)", (username, hash_pw(password)))
        conn.commit()
        return True, "Tạo tài khoản thành công!"
    except sqlite3.IntegrityError:
        return False, "Tên tài khoản này đã tồn tại!"
    finally:
        conn.close()

def authenticate_user(username, password):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == hash_pw(password))

def set_autostart(enable=True):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            exe_path = os.path.abspath(sys.argv[0])
            cmd = f'"{exe_path}"' if exe_path.endswith('.exe') else f'"{sys.executable}" "{exe_path}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

def is_autostart_enabled():
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False

class MasterServerSignals(QObject):
    client_updated = pyqtSignal(dict)
    client_disconnected = pyqtSignal(str)

class MasterServer(threading.Thread):
    def __init__(self, current_username, signals):
        super().__init__(daemon=True)
        self.current_username = current_username
        self.signals = signals
        self.running = False
        self.active_sockets = {}
        self.lock = threading.Lock()

    def run(self):
        self.running = True
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', SERVER_PORT))
        server.listen(100)

        while self.running:
            try:
                conn, addr = server.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except Exception:
                break

    def handle_client(self, conn, addr):
        client_id = None
        buffer = ""
        try:
            while self.running:
                data = conn.recv(2048).decode('utf-8')
                if not data:
                    break
                buffer += data
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    
                    req_master = payload.get("master_user", "")
                    if req_master != self.current_username:
                        resp = json.dumps({"status": "REJECTED", "msg": "Sai tài khoản máy chính"}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                        conn.close()
                        return

                    client_id = payload.get("node_name", f"Node_{addr[0]}")
                    with self.lock:
                        self.active_sockets[client_id] = conn

                    node_data = {
                        "node_name": client_id,
                        "ip": addr[0],
                        "status": "ONLINE",
                        "qt_status": "ON" if payload.get("qt", False) else "OFF",
                        "tinker_status": "ON" if payload.get("tinker", False) else "OFF",
                        "uptime": payload.get("uptime", "N/A"),
                        "last_seen": datetime.now().strftime("%H:%M:%S")
                    }
                    self.signals.client_updated.emit(node_data)
        except Exception:
            pass
        finally:
            with self.lock:
                if client_id in self.active_sockets:
                    del self.active_sockets[client_id]
            conn.close()
            if client_id:
                self.signals.client_disconnected.emit(client_id)

    def send_command(self, node_name, command_str):
        with self.lock:
            conn = self.active_sockets.get(node_name)
            if conn:
                try:
                    payload = json.dumps({"command": command_str}) + "\n"
                    conn.sendall(payload.encode('utf-8'))
                    return True
                except Exception:
                    return False
        return False

class MasterAppWindow(QMainWindow):
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.nodes = {}
        self.signals = MasterServerSignals()
        self.signals.client_updated.connect(self.update_client_row)
        self.signals.client_disconnected.connect(self.mark_client_offline)

        self.server = MasterServer(self.username, self.signals)
        self.server.start()

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"Phần Mềm Quản Lý Mir4 (Máy Chính) - Đang đăng nhập: {self.username}")
        self.resize(1100, 700)
        self.setStyleSheet("background-color: #1e1e24; color: #ffffff;")

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        ad_banner = QFrame()
        ad_banner.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b8860b, stop:1 #d4af37);
            border-radius: 8px;
            padding: 10px;
        """)
        ad_layout = QVBoxLayout(ad_banner)
        ad_title = QLabel("★ HỆ THỐNG QUẢN LÝ AUTO MIR4 SERVER PRO ★")
        ad_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ad_title.setStyleSheet("color: #000000;")
        ad_title.setAlignment(Qt.AlignCenter)
        
        ad_sub = QLabel("Chuyên cung cấp dịch vụ máy chủ ảo, tối ưu 40 tab game Mir4, hỗ trợ tự động hoá QT & TINKER Robot")
        ad_sub.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        ad_sub.setStyleSheet("color: #111111;")
        ad_sub.setAlignment(Qt.AlignCenter)
        
        ad_layout.addWidget(ad_title)
        ad_layout.addWidget(ad_sub)
        layout.addWidget(ad_banner)

        top_bar = QHBoxLayout()
        user_lbl = QLabel(f"Tài khoản quản trị: <b><font color='#ffd700'>{self.username}</font></b> | Cổng kết nối LAN: <b>{SERVER_PORT}</b>")
        user_lbl.setFont(QFont("Segoe UI", 10))
        top_bar.addWidget(user_lbl)

        top_bar.addStretch()

        self.cb_autostart = QCheckBox("Khởi động cùng Windows")
        self.cb_autostart.setChecked(is_autostart_enabled())
        self.cb_autostart.stateChanged.connect(self.on_toggle_autostart)
        self.cb_autostart.setStyleSheet("color: #00e676; font-weight: bold;")
        top_bar.addWidget(self.cb_autostart)

        layout.addLayout(top_bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Tên Máy Con", "Địa Chỉ IP", "Trạng Thái", "QT", "TINKER", "Uptime Máy Con"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2b2b36;
                gridline-color: #3f3f50;
                border-radius: 6px;
                font-size: 13px;
                selection-background-color: #d4af37;
                selection-color: #000000;
            }
            QHeaderView::section {
                background-color: #18181f;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #333340;
                color: #d4af37;
            }
        """)
        layout.addWidget(self.table)

        ctrl_bar = QHBoxLayout()

        btn_style_green = "background-color: #2e7d32; color: #fff; font-weight: bold; padding: 8px 12px; border-radius: 4px;"
        btn_style_red = "background-color: #c62828; color: #fff; font-weight: bold; padding: 8px 12px; border-radius: 4px;"
        btn_style_blue = "background-color: #1565c0; color: #fff; font-weight: bold; padding: 8px 12px; border-radius: 4px;"
        btn_style_gray = "background-color: #424242; color: #fff; font-weight: bold; padding: 8px 12px; border-radius: 4px;"

        btn_select_all = QPushButton("Chọn Tất Cả")
        btn_select_all.setStyleSheet(btn_style_gray)
        btn_select_all.clicked.connect(self.table.selectAll)
        ctrl_bar.addWidget(btn_select_all)

        btn_qt_on = QPushButton("▶ Bật QT")
        btn_qt_on.setStyleSheet(btn_style_green)
        btn_qt_on.clicked.connect(lambda: self.execute_on_selected("START_QT"))
        ctrl_bar.addWidget(btn_qt_on)

        btn_qt_off = QPushButton("■ Tắt QT")
        btn_qt_off.setStyleSheet(btn_style_red)
        btn_qt_off.clicked.connect(lambda: self.execute_on_selected("STOP_QT"))
        ctrl_bar.addWidget(btn_qt_off)

        btn_tk_on = QPushButton("▶ Bật TINKER")
        btn_tk_on.setStyleSheet(btn_style_green)
        btn_tk_on.clicked.connect(lambda: self.execute_on_selected("START_TINKER"))
        ctrl_bar.addWidget(btn_tk_on)

        btn_tk_off = QPushButton("■ Tắt TINKER")
        btn_tk_off.setStyleSheet(btn_style_red)
        btn_tk_off.clicked.connect(lambda: self.execute_on_selected("STOP_TINKER"))
        ctrl_bar.addWidget(btn_tk_off)

        btn_reboot = QPushButton("⚡ Khởi Động Lại Máy Con")
        btn_reboot.setStyleSheet(btn_style_blue)
        btn_reboot.clicked.connect(lambda: self.execute_on_selected("REBOOT"))
        ctrl_bar.addWidget(btn_reboot)

        layout.addLayout(ctrl_bar)

    def get_selected_node_names(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        node_names = []
        for index in selected_indexes:
            row = index.row()
            item = self.table.item(row, 0)
            if item:
                node_names.append(item.text())
        return node_names

    def execute_on_selected(self, command_str):
        selected_nodes = self.get_selected_node_names()
        if not selected_nodes:
            QMessageBox.warning(self, "Chưa chọn máy", "Vui lòng click chọn 1 máy, giữ Ctrl chọn nhiều máy hoặc Shift để chọn dải máy!")
            return

        if command_str == "REBOOT":
            reply = QMessageBox.question(
                self, 'Xác nhận',
                f"Bạn có chắc muốn Khởi động lại {len(selected_nodes)} máy đã chọn?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        success_count = 0
        for name in selected_nodes:
            if self.server.send_command(name, command_str):
                success_count += 1

        QMessageBox.information(self, "Thực thi hoàn tất", f"Đã gửi lệnh [{command_str}] tới {success_count}/{len(selected_nodes)} máy đang Online.")

    def on_toggle_autostart(self, state):
        enable = state == Qt.Checked
        if set_autostart(enable):
            status = "đã bật" if enable else "đã tắt"
            QMessageBox.information(self, "Thông báo", f"Tự khởi động cùng Windows {status} thành công!")
        else:
            QMessageBox.warning(self, "Lỗi", "Không thể cập nhật cấu hình khởi động!")

    def update_client_row(self, data):
        node_name = data["node_name"]
        if node_name not in self.nodes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.nodes[node_name] = row
        else:
            row = self.nodes[node_name]

        self.table.setItem(row, 0, QTableWidgetItem(node_name))
        self.table.setItem(row, 1, QTableWidgetItem(data["ip"]))
        
        status_item = QTableWidgetItem(data["status"])
        status_item.setForeground(QColor("#00e676"))
        status_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.table.setItem(row, 2, status_item)

        qt_item = QTableWidgetItem(data["qt_status"])
        qt_item.setForeground(QColor("#00e676") if data["qt_status"] == "ON" else QColor("#ff5252"))
        self.table.setItem(row, 3, qt_item)

        tinker_item = QTableWidgetItem(data["tinker_status"])
        tinker_item.setForeground(QColor("#00e676") if data["tinker_status"] == "ON" else QColor("#ff5252"))
        self.table.setItem(row, 4, tinker_item)

        self.table.setItem(row, 5, QTableWidgetItem(data["uptime"]))

    def mark_client_offline(self, node_name):
        if node_name in self.nodes:
            row = self.nodes[node_name]
            status_item = QTableWidgetItem("OFFLINE")
            status_item.setForeground(QColor("#ff5252"))
            status_item.setFont(QFont("Segoe UI", 9, QFont.Bold))
            self.table.setItem(row, 2, status_item)

class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Đăng Nhập Quản Lý Mir4")
        self.resize(360, 320)
        self.setStyleSheet("background-color: #1e1e24; color: #ffffff; font-family: 'Segoe UI';")

        layout = QVBoxLayout(self)

        title = QLabel("HỆ THỐNG QUẢN TRỊ MIR4")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #d4af37; margin-bottom: 10px;")
        layout.addWidget(title)

        self.txt_user = QLineEdit()
        self.txt_user.setPlaceholderText("Tài khoản máy chính")
        self.txt_user.setStyleSheet("padding: 8px; border-radius: 4px; background: #2c2c38; color: #fff;")
        layout.addWidget(self.txt_user)

        self.txt_pass = QLineEdit()
        self.txt_pass.setPlaceholderText("Mật khẩu")
        self.txt_pass.setEchoMode(QLineEdit.Password)
        self.txt_pass.setStyleSheet("padding: 8px; border-radius: 4px; background: #2c2c38; color: #fff;")
        layout.addWidget(self.txt_pass)

        self.btn_login = QPushButton("Đăng Nhập")
        self.btn_login.setStyleSheet("background-color: #d4af37; color: #000; font-weight: bold; padding: 10px; border-radius: 4px;")
        self.btn_login.clicked.connect(self.handle_login)
        layout.addWidget(self.btn_login)

        self.btn_register = QPushButton("Tạo Tài Khoản Mới")
        self.btn_register.setStyleSheet("background-color: #3e3e50; color: #fff; padding: 8px; border-radius: 4px;")
        self.btn_register.clicked.connect(self.handle_register)
        layout.addWidget(self.btn_register)

    def handle_login(self):
        u = self.txt_user.text().strip()
        p = self.txt_pass.text().strip()
        if authenticate_user(u, p):
            self.master_win = MasterAppWindow(u)
            self.master_win.show()
            self.close()
        else:
            QMessageBox.critical(self, "Thất bại", "Sai tài khoản hoặc mật khẩu!")

    def handle_register(self):
        u = self.txt_user.text().strip()
        p = self.txt_pass.text().strip()
        ok, msg = register_user(u, p)
        if ok:
            QMessageBox.information(self, "Thành công", msg)
        else:
            QMessageBox.warning(self, "Lỗi", msg)

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    login = LoginWindow()
    login.show()
    sys.exit(app.exec_())
