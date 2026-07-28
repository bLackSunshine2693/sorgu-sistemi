"""
Sorgu Sistemi USB Launcher v2.0
- USB'nin drive letter'ını otomatik tespit eder
- _internal klasörünü local cache'e kopyalar (hız için)
- MariaDB'yi USB'deki data ile başlatır
- Lisans: USB serial + Makine ID kontrolü
- Kapatınca MariaDB'yi durdurur
"""
import sys, os, subprocess, time, socket, threading, webbrowser, atexit, shutil

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR  = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))

MARIADB_DIR = os.path.join(BASE_DIR, "MariaDB")
MYSQLD_EXE  = os.path.join(MARIADB_DIR, "bin", "mysqld.exe")
DATA_DIR    = os.path.join(MARIADB_DIR, "data")
MYSQL_PORT  = 3307
LOG_FILE    = os.path.join(BASE_DIR, "sorgu.log")

CURRENT_VERSION = "4.0.6"
GITHUB_RAW_URL  = "https://raw.githubusercontent.com/bLackSunshine2693/sorgu-version/main/version.json"

# Local cache dizini (C: sürücüsünde hızlı)
LOCAL_CACHE = r"C:\SorguCache"

_mariadb_proc = None

def show_error(title, msg):
    try:
        import tkinter as tk, tkinter.messagebox as mb
        r=tk.Tk(); r.withdraw()
        mb.showerror(title, msg); r.destroy()
    except:
        print(f"[HATA] {title}: {msg}")

def port_free(p):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0

def get_usb_serial_from_path(path):
    try:
        drive = os.path.splitdrive(path)[0] or "C:"
        out = subprocess.check_output(
            f"vol {drive}", shell=True,
            stderr=subprocess.DEVNULL, timeout=5, creationflags=0x08000000
        ).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            if "Serial" in line and "is" in line:
                return line.split("is")[-1].strip().replace("-", "")
    except: pass
    return ""

def ensure_local_cache():
    """_internal klasörünü local C: diskine kopyala — USB'den hızlı yükle."""
    if not IS_FROZEN: return
    drive = os.path.splitdrive(BASE_DIR)[0].upper()
    if drive == "C:": return  # Zaten local

    internal_src = os.path.join(BASE_DIR, "_internal")
    if not os.path.exists(internal_src): return

    cache_ver_file = os.path.join(LOCAL_CACHE, "cache_version.txt")
    cached_ver = ""
    if os.path.exists(cache_ver_file):
        try: cached_ver = open(cache_ver_file).read().strip()
        except: pass

    # Versiyon farklıysa veya cache yoksa kopyala
    if cached_ver != CURRENT_VERSION or not os.path.exists(os.path.join(LOCAL_CACHE, "_internal")):
        try:
            os.makedirs(LOCAL_CACHE, exist_ok=True)
            dst = os.path.join(LOCAL_CACHE, "_internal")
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(internal_src, dst)
            open(cache_ver_file, "w").write(CURRENT_VERSION)
        except Exception as e:
            pass  # Cache başarısız olsa da USB'den devam et

def write_my_ini():
    ini_path = os.path.join(MARIADB_DIR, "my.ini")
    data_dir_fwd = DATA_DIR.replace("\\", "/")
    tmp_dir = os.path.join(MARIADB_DIR, "tmp").replace("\\", "/")
    os.makedirs(os.path.join(MARIADB_DIR, "tmp"), exist_ok=True)
    content = f"""[mysqld]
port         = {MYSQL_PORT}
bind-address = 127.0.0.1
datadir      = {data_dir_fwd}
tmpdir       = {tmp_dir}
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
local-infile   = 0
skip-networking = 0
key_buffer_size         = 256M
myisam_sort_buffer_size = 64M

[client]
port    = {MYSQL_PORT}
default-character-set = utf8mb4
"""
    with open(ini_path, "w", encoding="utf-8") as f:
        f.write(content)
    return ini_path

def start_mariadb():
    global _mariadb_proc
    if not port_free(MYSQL_PORT):
        return True

    if not os.path.exists(MYSQLD_EXE):
        show_error("USB Hatası",
            f"MariaDB USB'de bulunamadı:\n{MYSQLD_EXE}\n\n"
            "USB'nin doğru takıldığından emin olun.")
        return False

    ini_path = write_my_ini()
    _mariadb_proc = subprocess.Popen(
        [MYSQLD_EXE, f"--defaults-file={ini_path}", "--console"],
        stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    # USB yavaş olabilir — 90 saniye bekle (eski 30 saniyeydi)
    for _ in range(180):
        if not port_free(MYSQL_PORT):
            return True
        time.sleep(0.5)

    show_error("MariaDB başlatılamadı",
        f"MariaDB 90 saniyede başlamadı.\n\n"
        f"USB'nin hızlı bir porta takıldığından emin olun.\nLog: {LOG_FILE}")
    return False

def stop_mariadb():
    global _mariadb_proc
    if _mariadb_proc:
        try: _mariadb_proc.terminate(); _mariadb_proc.wait(timeout=10)
        except: pass
        _mariadb_proc = None

def check_update_background():
    import time; time.sleep(5)
    try:
        import urllib.request, json, urllib.parse
        with urllib.request.urlopen(GITHUB_RAW_URL, timeout=5) as r:
            data = json.loads(r.read().decode())
        remote = data.get("version","0.0.0")
        if remote > CURRENT_VERSION:
            notes = data.get("notes","")
            url   = data.get("download_url","")
            try:
                import urllib.request as req
                req.urlopen(f"http://localhost:5001/api/set_update?v={remote}&notes={urllib.parse.quote(notes)}&url={urllib.parse.quote(url)}", timeout=3)
            except: pass
    except: pass

def apply_efs_encryption():
    flag = os.path.join(MARIADB_DIR, ".efs_done")
    if os.path.exists(flag): return
    try:
        data_dir = DATA_DIR.replace("/", "\\")
        result = subprocess.run(
            f'cipher /e /s:"{data_dir}"',
            shell=True, capture_output=True,
            timeout=1800, creationflags=0x08000000
        )
        if result.returncode == 0:
            open(flag, "w").close()
    except: pass

def main():
    # Local cache kopyala (arka planda)
    cache_thread = threading.Thread(target=ensure_local_cache, daemon=True)
    cache_thread.start()

    # Lisans kontrol
    try:
        sys.path.insert(0, BASE_DIR)
        from sorgu_license import check_license
        lic_path = os.path.join(BASE_DIR, "license.lic")
        ok, msg, lic_data = check_license(lic_path)
        if not ok:
            show_error("Lisans Hatası",
                f"Sorgu Sistemi çalıştırılamadı:\n\n{msg}\n\n"
                "Yöneticinizle iletişime geçin.")
            return
        if lic_data.get("usb_serial"):
            current_usb = get_usb_serial_from_path(BASE_DIR)
            if current_usb != lic_data["usb_serial"]:
                show_error("USB Hatası",
                    f"Bu lisans farklı bir USB için oluşturulmuş.\n\n"
                    f"Lisans USB serial : {lic_data['usb_serial']}\n"
                    f"Mevcut USB serial : {current_usb}\n\n"
                    "Doğru USB'yi takın.")
                return
    except ImportError:
        pass

    # MariaDB başlat
    if not start_mariadb():
        return
    atexit.register(stop_mariadb)

    # Arka plan görevleri
    threading.Thread(target=apply_efs_encryption, daemon=True).start()
    threading.Thread(target=check_update_background, daemon=True).start()

    # Flask başlat
    def run_flask():
        try:
            import sorgu_app
            sorgu_app.app.run(host="127.0.0.1", port=5001,
                              debug=False, threaded=True, use_reloader=False)
        except Exception as e:
            show_error("Flask Hatası", str(e))

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Timer(2.0, lambda: webbrowser.open("http://localhost:5001")).start()

    # Ana thread'i canlı tut
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.mainloop()
    except:
        while True:
            time.sleep(1)

if __name__ == "__main__":
    main()
