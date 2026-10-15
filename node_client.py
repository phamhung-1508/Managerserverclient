import socket
import time
import json
import ctypes
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

CONFIG_FILE = "client_config.json"

PROCESS_CONFIG = {
    "qt_proc": "qt_mir4.exe",
    "qt_path": r"C:\Mir4Tools\qt_mir4.exe",
    "tinker_proc": "tinker.exe",
    "tinker_path": r"C:\Mir4Tools\tinker.exe"
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def get_uptime_str():
    millis = ctypes.windll.kernel32.GetTickCount64()
    seconds = int(millis / 1000)
    hours, remainder = divmod(seconds, 3600)
    minutes, sec = divmod(remainder, 60)
    return f"{hours}h {minutes}m {sec}s"

def is_process_running(proc_name):
    try:
        cmd = f'tasklist /FI "IMAGENAME eq {proc_name}"'
        output = subprocess.check_output(cmd, shell=True).decode(errors='ignore')
        return proc_name.lower() in output.lower()
    except Exception:
        return False

def kill_process(proc_name):
    try:
        subprocess.run(f'taskkill /F /IM "{proc_name}" /T', shell=True, capture_output=True)
    except Exception:
        pass

def start_program(path):
    try:
        if os.path.exists(path):
            subprocess.Popen([path], shell=True)
        else:
            subprocess.Popen(path, shell=True)
    except Exception:
        pass

def handle_remote_command(cmd):
    if cmd == "START_QT":
        start_program(PROCESS_CONFIG["qt_path"])
    elif cmd == "STOP_QT":
        kill_process(PROCESS_CONFIG["qt_proc"])
    elif cmd == "START_TINKER":
        start_program(PROCESS_CONFIG["tinker_path"])
    elif cmd == "STOP_TINKER":
        kill_process(PROCESS_CONFIG["tinker_proc"])
    elif cmd == "REBOOT":
        subprocess.run("shutdown /r /t 2 /f", shell=True)

def network_loop(cfg):
    master_ip = cfg.get("master_ip", "127.0.0.1")
    master_port = int(cfg.get("master_port", 9999))
    master_user = cfg.get("master_user", "")
    node_name = cfg.get("node_name", "Node_01")

    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((master_ip, master_port))

            def listen_commands(sock):
                buf = ""
                while True:
                    try:
                        data = sock.recv(1024).decode('utf-8')
                        if not data:
                            break
                        buf += data
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            if line.strip():
                                cmd_obj = json.loads(line)
                                handle_remote_command(cmd_obj.get("command", ""))
                    except Exception:
                        break

            t = threading.Thread(target=listen_commands, args=(s,), daemon=True)
            t.start()

            while t.is_alive():
                qt_active = is_process_running(PROCESS_CONFIG["qt_proc"])
                tinker_active = is_process_running(PROCESS_CONFIG["tinker_proc"])

                payload = {
                    "master_user": master_user,
                    "node_name": node_name,
                    "qt": qt_active,
                    "tinker": tinker_active,
                    "uptime": get_uptime_str()
                }

                s.sendall((json.dumps(payload) + "\n").encode('utf-8'))
                time.sleep(3)
        except Exception:
            time.sleep(5)

class ClientSetupUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cấu Hình Kết Nối Máy Con")
        self.root.geometry("380x300")
        self.root.resizable(False, False)

        cfg = load_config() or {}

        tk.Label(self.root, text="IP Máy Chính (LAN / Tailscale):").pack(anchor="w", padx=20, pady=(15, 0))
        self.txt_ip = tk.Entry(self.root)
        self.txt_ip.insert(0, cfg.get("master_ip", "192.168.1.100"))
        self.txt_ip.pack(fill="x", padx=20, pady=5)

        tk.Label(self.root, text="Tài khoản máy chính:").pack(anchor="w", padx=20, pady=(5, 0))
        self.txt_user = tk.Entry(self.root)
        self.txt_user.insert(0, cfg.get("master_user", "admin"))
        self.txt_user.pack(fill="x", padx=20, pady=5)

        tk.Label(self.root, text="Tên máy con (Node Name):").pack(anchor="w", padx=20, pady=(5, 0))
        self.txt_name = tk.Entry(self.root)
        self.txt_name.insert(0, cfg.get("node_name", "Node_01"))
        self.txt_name.pack(fill="x", padx=20, pady=5)

        btn_save = tk.Button(self.root, text="Lưu & Bắt Đầu Chạy", bg="#2e7d32", fg="#ffffff", font=("Segoe UI", 10, "bold"), command=self.on_start)
        btn_save.pack(fill="x", padx=20, pady=20)

    def on_start(self):
        cfg = {
            "master_ip": self.txt_ip.get().strip(),
            "master_port": 9999,
            "master_user": self.txt_user.get().strip(),
            "node_name": self.txt_name.get().strip()
        }
        if not cfg["master_ip"] or not cfg["master_user"] or not cfg["node_name"]:
            messagebox.showwarning("Lỗi", "Vui lòng nhập đầy đủ các trường!")
            return

        save_config(cfg)
        self.root.destroy()
        threading.Thread(target=network_loop, args=(cfg,), daemon=True).start()
        while True:
            time.sleep(1)

if __name__ == "__main__":
    config = load_config()
    if config:
        threading.Thread(target=network_loop, args=(config,), daemon=True).start()
        while True:
            time.sleep(1)
    else:
        app = ClientSetupUI()
        app.root.mainloop()
