import sys
import os
import socket
import threading
import json
import sqlite3
import hashlib
import winreg
import subprocess
import ctypes
import urllib.request
from datetime import datetime

from embedded_tailscale import EmbeddedTailscale

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

if not is_admin():
    try:
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
            args = ""
        else:
            exe_path = sys.executable
            args = f'"{os.path.abspath(__file__)}"'
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, args, None, 1)
        if ret > 32:
            sys.exit(0)
    except Exception:
        pass

def setup_windows_firewall(port=9999):
    rule_name = "Mir4_Master_Socket_Server"
    try:
        chk_cmd = f'netsh advfirewall firewall show rule name="{rule_name}"'
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        res = subprocess.run(chk_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        if res.returncode != 0 or rule_name.lower() not in res.stdout.decode('latin1', errors='ignore').lower():
            in_cmd = f'netsh advfirewall firewall add rule name="{rule_name}" dir=in action=allow protocol=TCP localport={port}'
            out_cmd = f'netsh advfirewall firewall add rule name="{rule_name}" dir=out action=allow protocol=TCP localport={port}'
            subprocess.run(in_cmd, shell=True, startupinfo=startupinfo)
            subprocess.run(out_cmd, shell=True, startupinfo=startupinfo)
    except Exception:
        pass

def get_machine_ips(ts_client=None):
    lan_ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    vpn_ip = ""
    if ts_client:
        vpn_ip = ts_client.get_my_ip()

    wan_ip = ""
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={'User-Agent': 'Mozilla/5.0'})
        wan_ip = urllib.request.urlopen(req, timeout=3).read().decode('utf8').strip()
    except Exception:
        pass
    return lan_ip, vpn_ip, wan_ip

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QCheckBox, QAbstractItemView,
    QMenu, QAction
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QIcon

SERVER_PORT = 9999
DB_NAME = "master_users.db"
APP_NAME = "Mir4MasterManager"
TASK_NAME = "Mir4MasterManager_AutoStart"
PREF_FILE = "login_pref.json"

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def init_db():
    db_path = os.path.join(get_app_dir(), DB_NAME)
    conn = sqlite3.connect(db_path)
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
        return False, "Tài khoản và mật khẩu không được để trống!"
    db_path = os.path.join(get_app_dir(), DB_NAME)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users VALUES (?, ?)", (username.strip().lower(), hash_pw(password)))
        conn.commit()
        return True, "Tạo tài khoản thành công!"
    except sqlite3.IntegrityError:
        return False, "Tên tài khoản này đã tồn tại!"
    finally:
        conn.close()

def authenticate_user(username, password):
    db_path = os.path.join(get_app_dir(), DB_NAME)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username = ?", (username.strip().lower(),))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == hash_pw(password))

def set_autostart(enable=True):
    """
    Sử dụng Windows Task Scheduler với quyền HIGHEST để vượt qua UAC,
    đồng thời duy trì ghi vào Registry Run để tương thích hoàn toàn.
    """
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

        if enable:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                exe_path = os.path.abspath(sys.argv[0])

            # Đăng ký Task Scheduler chạy quyền Administrator không hỏi Yes/No
            create_cmd = f'schtasks /create /tn "{TASK_NAME}" /tr "\"{exe_path}\"" /sc onlogon /rl highest /f'
            subprocess.run(create_cmd, shell=True, startupinfo=startupinfo)

            # Đăng ký phụ trợ trong HKCU Run
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            cmd = f'"{exe_path}"' if exe_path.endswith('.exe') else f'"{sys.executable}" "{exe_path}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
        else:
            # Xóa Task Scheduler
            del_cmd = f'schtasks /delete /tn "{TASK_NAME}" /f'
            subprocess.run(del_cmd, shell=True, startupinfo=startupinfo)

            # Xóa trong Registry Run
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
                winreg.DeleteValue(key, APP_NAME)
                winreg.CloseKey(key)
            except FileNotFoundError:
                pass
        return True
    except Exception:
        return False

def is_autostart_enabled():
    try:
        # Kiểm tra trước trong Task Scheduler
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        chk_cmd = f'schtasks /query /tn "{TASK_NAME}"'
        res = subprocess.run(chk_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
        if res.returncode == 0:
            return True

        # Fallback kiểm tra Registry
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

class MasterServerSignals(QObject):
    client_updated = pyqtSignal(dict)
    client_disconnected = pyqtSignal(str)

class MasterServer(threading.Thread):
    def __init__(self, current_username, signals):
        super().__init__(daemon=True)
        self.current_username = current_username.strip().lower()
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
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:
                        continue
                    
                    req_master = payload.get("master_user", "").strip().lower()
                    if req_master != self.current_username:
                        resp = json.dumps({"status": "REJECTED", "msg": "Sai tai khoan quan tri"}) + "\n"
                        conn.sendall(resp.encode('utf-8'))
                        conn.close()
                        return

                    client_id = payload.get("node_name", f"Node_{addr[0]}").strip()
                    with self.lock:
                        self.active_sockets[client_id] = conn

                    # Xử lý linh hoạt cả định dạng payload chuỗi mới ("ON", "OFF", "ĐÃ CHẠY-CHỜ ĐĂNG NHẬP") và boolean cũ
                    qt_val = payload.get("qt", False)
                    if isinstance(qt_val, str):
                        qt_status = qt_val
                    else:
                        qt_status = "ON" if qt_val else "OFF"

                    tinker_val = payload.get("tinker", False)
                    if isinstance(tinker_val, str):
                        tinker_status = tinker_val
                    else:
                        tinker_status = "ON" if tinker_val else "OFF"

                    node_data = {
                        "node_name": client_id,
                        "ip": addr[0],
                        "status": "ONLINE",
                        "qt_status": qt_status,
                        "tinker_status": tinker_status,
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
        self.username = username.strip().lower()
        self.signals = MasterServerSignals()
        self.signals.client_updated.connect(self.update_client_row)
        self.signals.client_disconnected.connect(self.mark_client_offline)

        self.server = MasterServer(self.username, self.signals)
        self.server.start()

        self.ts = EmbeddedTailscale()
        self.ts.start_and_connect()
        self.lan_ip, self.vpn_ip, self.wan_ip = get_machine_ips(self.ts)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(f"Mir4 Master Hub - [Tài khoản: {self.username}]")
        self.resize(1180, 740)
        self.setStyleSheet("background-color: #121214; color: #ffffff;")

        if os.path.exists("app_icon.ico"):
            self.setWindowIcon(QIcon("app_icon.ico"))

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # BANNER QUẢNG CÁO (GIỮ NGUYÊN QUẢNG CÁO CŨ, THÊM QUẢNG CÁO MỚI)
        ad_banner = QFrame()
        ad_banner.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b8860b, stop:1 #d4af37);
            border-radius: 8px;
            padding: 8px;
        """)
        ad_layout = QVBoxLayout(ad_banner)
        ad_title = QLabel("★ HỆ THỐNG QUẢN LÝ AUTO MIR4 SERVER PRO [PHAMHUNG] ★")
        ad_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        ad_title.setStyleSheet("color: #000000;")
        ad_title.setAlignment(Qt.AlignCenter)
        
        ad_sub = QLabel("Hỗ trợ đồng bộ đa máy con qua LAN/Internet | Zalo: 0392771558")
        ad_sub.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        ad_sub.setStyleSheet("color: #111111;")
        ad_sub.setAlignment(Qt.AlignCenter)

        # QUẢNG CÁO MỚI BỔ SUNG
        ad_extra = QLabel("Mua QT + TINKER liên hệ : ZL : 0392771558")
        ad_extra.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ad_extra.setStyleSheet("color: #8b0000; margin-top: 2px;")
        ad_extra.setAlignment(Qt.AlignCenter)
        
        ad_layout.addWidget(ad_title)
        ad_layout.addWidget(ad_sub)
        ad_layout.addWidget(ad_extra)
        layout.addWidget(ad_banner)

        # THANH THÔNG TIN IP
        top_bar = QHBoxLayout()
        ip_info = f"LAN: <font color='#00e676'><b>{self.lan_ip}</b></font>"
        if self.vpn_ip:
            ip_info += f" | VPN TAILSCALE: <font color='#ffeb3b'><b>{self.vpn_ip}</b></font>"
        if self.wan_ip:
            ip_info += f" | WAN: <font color='#00e5ff'><b>{self.wan_ip}</b></font>"

        user_lbl = QLabel(f"Tài khoản quản trị: <b><font color='#ffd700'>{self.username}</font></b> | IP Máy Chính ({ip_info}) | Port: <b>9999</b>")
        user_lbl.setFont(QFont("Segoe UI", 10))
        top_bar.addWidget(user_lbl)

        top_bar.addStretch()

        self.cb_autostart = QCheckBox("Khởi động cùng Windows (Bypass UAC)")
        self.cb_autostart.setChecked(is_autostart_enabled())
        self.cb_autostart.stateChanged.connect(self.on_toggle_autostart)
        self.cb_autostart.setStyleSheet("color: #00e676; font-weight: bold;")
        top_bar.addWidget(self.cb_autostart)

        layout.addLayout(top_bar)

        # BẢNG THEO DÕI MÁY CON
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Tên Máy Con", "Địa Chỉ IP", "Trạng Thái", "QT", "TINKER", "Thời Gian Uptime"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1c1c24;
                gridline-color: #2e2e38;
                border-radius: 6px;
                font-size: 13px;
                selection-background-color: #ff6600;
                selection-color: #ffffff;
            }
            QHeaderView::section {
                background-color: #16161b;
                padding: 6px;
                font-weight: bold;
                border: 1px solid #292933;
                color: #d4af37;
            }
        """)
        layout.addWidget(self.table)

        # THANH NÚT ĐIỀU KHIỂN
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

        btn_reboot = QPushButton("⚡ Reboot Máy Con")
        btn_reboot.setStyleSheet(btn_style_blue)
        btn_reboot.clicked.connect(lambda: self.execute_on_selected("REBOOT"))
        ctrl_bar.addWidget(btn_reboot)

        layout.addLayout(ctrl_bar)

    def show_context_menu(self, pos):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #24242c; color: #ffffff; border: 1px solid #444; font-weight: bold; }
            QMenu::item:selected { background-color: #c6282
