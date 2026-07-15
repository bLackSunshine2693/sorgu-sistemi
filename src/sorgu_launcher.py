"""
Sorgu Sistemi Launcher v2.0
- Sessiz çalışır (pencere yok)
- Yeniden başlatılınca eski instance otomatik kapatılır
- MariaDB otomatik başlar/durur
"""
import sys, os, subprocess, time, socket, threading, webbrowser, atexit

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR  = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

MARIADB_DIR = os.path.join(BASE_DIR, "MariaDB")
# Bir üst klasörde ara (dist/SorguSistemi → SorguSistemi)
if not os.path.exists(MARIADB_DIR):
    MARIADB_DIR = os.path.join(os.path.dirname(BASE_DIR), "MariaDB")

MYSQLD_EXE  = os.path.join(MARIADB_DIR, "bin", "mysqld.exe")
DATA_DIR    = os.path.join(MARIADB_DIR, "data")
MYSQL_PORT  = 3307
LOG_FILE    = os.path.join(BASE_DIR, "mariadb.log")

_mariadb_proc = None


CURRENT_VERSION = "4.0.0"
GITHUB_RAW_URL  = "https://raw.githubusercontent.com/bLackSunshine2693/sorgu-version/main/version.json"

def check_update_background():
    """Arka planda güncelleme kontrol — tarayıcı açıldıktan sonra."""
    import time; time.sleep(5)
    try:
        import urllib.request, json
        with urllib.request.urlopen(GITHUB_RAW_URL, timeout=5) as r:
            data = json.loads(r.read().decode())
        remote = data.get("version","0.0.0")
        if remote > CURRENT_VERSION:
            notes = data.get("notes","")
            url   = data.get("download_url","")
            # Kullanıcıya bildir (Windows toast yerine basit log)
            log_msg = f"[GÜNCELLEME] Yeni sürüm: {remote} — {notes}"
            with open(os.path.join(BASE_DIR,"sorgu.log"),"a") as f:
                f.write(log_msg + "\n")
            # sorgu_app üzerinden dashboard'a bildir
            try:
                import urllib.request as req
                req.urlopen(f"http://localhost:5001/api/set_update?v={remote}&notes={urllib.parse.quote(notes)}&url={urllib.parse.quote(url)}", timeout=3)
            except: pass
    except: pass

def show_error(title, msg):
    try:
        import tkinter as tk, tkinter.messagebox as mb
        r = tk.Tk(); r.withdraw()
        mb.showerror(title, msg); r.destroy()
    except:
        print(f"[HATA] {title}: {msg}")

def port_free(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0

def kill_port(port, wait=1.5):
    """Verilen porttaki işlemi kapat."""
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port} "',
            shell=True, stderr=subprocess.DEVNULL,
            timeout=5, creationflags=0x08000000
        ).decode(errors="ignore")
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                subprocess.run(f"taskkill /PID {pid} /T /F",
                             shell=True, capture_output=True,
                             creationflags=0x08000000)
                time.sleep(wait)
                return True
    except:
        pass
    return False

def write_my_ini():
    ini_path  = os.path.join(MARIADB_DIR, "my.ini")
    data_fwd  = DATA_DIR.replace("\\", "/")
    tmp_dir   = os.path.join(MARIADB_DIR, "tmp").replace("\\", "/")
    os.makedirs(os.path.join(MARIADB_DIR, "tmp"), exist_ok=True)
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write(f"""[mysqld]
port         = {MYSQL_PORT}
bind-address = 127.0.0.1
datadir      = {data_fwd}
tmpdir       = {tmp_dir}
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
local-infile = 0
key_buffer_size = 256M
myisam_sort_buffer_size = 64M

[client]
port    = {MYSQL_PORT}
default-character-set = utf8mb4
""")
    return ini_path

def start_mariadb():
    global _mariadb_proc
    if not port_free(MYSQL_PORT):
        return True
    if not os.path.exists(MYSQLD_EXE):
        show_error("MariaDB bulunamadı",
            f"MariaDB kurulu değil:\n{MYSQLD_EXE}\n\nKurulum klasörünü kontrol edin.")
        return False
    ini = write_my_ini()
    _mariadb_proc = subprocess.Popen(
        [MYSQLD_EXE, f"--defaults-file={ini}", "--console"],
        stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    for _ in range(60):
        if not port_free(MYSQL_PORT):
            return True
        time.sleep(0.5)
    show_error("MariaDB başlatılamadı", f"Log: {LOG_FILE}")
    return False


def apply_efs_encryption():
    """EFS ile data klasörünü şifrele — sadece bir kez çalışır."""
    flag = os.path.join(MARIADB_DIR, ".efs_done")
    if os.path.exists(flag):
        return
    try:
        data_dir = DATA_DIR.replace("/", "\\")
        result = subprocess.run(
            f'cipher /e /s:"{data_dir}"',
            shell=True, capture_output=True,
            timeout=1800, creationflags=0x08000000
        )
        if result.returncode == 0:
            open(flag, "w").close()
    except:
        pass

def stop_mariadb():
    global _mariadb_proc
    if _mariadb_proc:
        try: _mariadb_proc.terminate(); _mariadb_proc.wait(timeout=10)
        except: pass
        _mariadb_proc = None

def run_flask():
    try:
        import sorgu_app
        sorgu_app.MARIADB["port"] = MYSQL_PORT
        sorgu_app.app.run(host="127.0.0.1", port=5001,
                          debug=False, threaded=True, use_reloader=False)
    except Exception as e:
        show_error("Flask Hatası", str(e))

def main():
    # Eski instance'ı kapat (port 5001 ve 3307)
    kill_port(5001, wait=1.5)
    kill_port(MYSQL_PORT, wait=1.0)

    # Lisans kontrolü
    try:
        sys.path.insert(0, BASE_DIR)
        from sorgu_license import check_license
        ok, msg, _ = check_license(os.path.join(BASE_DIR, "license.lic"))
        if not ok:
            show_error("Lisans Hatası",
                f"Sorgu Sistemi çalıştırılamadı:\n\n{msg}\n\nYöneticinizle iletişime geçin.")
            return
    except ImportError:
        pass  # geliştirme modu

    # MariaDB başlat
    if not start_mariadb():
        return
    atexit.register(stop_mariadb)

    # EFS şifrelemesi arka planda
    threading.Thread(target=apply_efs_encryption, daemon=True).start()

    # Flask arka planda başlat
    threading.Thread(target=run_flask, daemon=True).start()

    # Tarayıcıyı aç
    threading.Timer(2.0, lambda: webbrowser.open("http://localhost:5001")).start()
    # Arka planda güncelleme kontrol
    threading.Thread(target=check_update_background, daemon=True).start()

    # Ana thread'i canlı tut
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        stop_mariadb()

if __name__ == "__main__":
    main()
