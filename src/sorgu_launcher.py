"""
Sorgu Sistemi Universal Launcher v3.0
- C:, D: veya USB (E:, F: vs.) — hepsinde çalışır
- Drive'ı otomatik tespit eder
- USB ise serial lisans kontrolü yapar
- USB ise my.ini dinamik yazar
- USB ise local cache kopyalar
"""
import sys, os, subprocess, time, socket, threading, webbrowser, atexit, shutil

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR  = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
DRIVE     = os.path.splitdrive(BASE_DIR)[0].upper()  # C:, D:, E: vs.

# USB mi yoksa lokal mi?
def is_usb_drive(drive):
    """Sürücünün USB/çıkarılabilir olup olmadığını kontrol et."""
    try:
        out = subprocess.check_output(
            f'wmic logicaldisk where caption="{drive}" get drivetype /value',
            shell=True, timeout=5, creationflags=0x08000000,
            stderr=subprocess.DEVNULL).decode(errors="ignore")
        for line in out.splitlines():
            if "DriveType=" in line:
                return line.split("=")[1].strip() == "2"  # 2 = Removable
    except: pass
    return False

IS_USB = is_usb_drive(DRIVE)

MARIADB_DIR = os.path.join(BASE_DIR, "MariaDB")
MYSQLD_EXE  = os.path.join(MARIADB_DIR, "bin", "mysqld.exe")
DATA_DIR    = os.path.join(MARIADB_DIR, "data")
MYSQL_PORT  = 3307
LOG_FILE    = os.path.join(BASE_DIR, "sorgu.log")

CURRENT_VERSION = "4.0.7"
GITHUB_RAW_URL  = "https://raw.githubusercontent.com/bLackSunshine2693/sorgu-version/main/version.json"

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

def get_usb_serial():
    try:
        out = subprocess.check_output(
            f"vol {DRIVE}", shell=True,
            stderr=subprocess.DEVNULL, timeout=5, creationflags=0x08000000
        ).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            if "Serial" in line and "is" in line:
                return line.split("is")[-1].strip().replace("-", "")
    except: pass
    return ""

def find_best_cache_drive():
    """En çok boş alan olan C veya D sürücüsünü seç."""
    best, best_free = "C:", 0
    for d in ["C:", "D:"]:
        try:
            free = shutil.disk_usage(d + "\\").free
            if free > best_free:
                best_free = free; best = d
        except: pass
    return best

def ensure_local_cache():
    """USB modunda _internal'ı local diske kopyala."""
    if not IS_USB or not IS_FROZEN: return
    cache_drive = find_best_cache_drive()
    cache_dir = cache_drive + "\\SorguCache"
    internal_src = os.path.join(BASE_DIR, "_internal")
    if not os.path.exists(internal_src): return
    ver_file = os.path.join(cache_dir, "ver.txt")
    cached_ver = open(ver_file).read().strip() if os.path.exists(ver_file) else ""
    if cached_ver == CURRENT_VERSION and os.path.exists(os.path.join(cache_dir, "_internal")):
        return
    try:
        os.makedirs(cache_dir, exist_ok=True)
        dst = os.path.join(cache_dir, "_internal")
        if os.path.exists(dst): shutil.rmtree(dst)
        shutil.copytree(internal_src, dst)
        open(ver_file, "w").write(CURRENT_VERSION)
    except: pass

def write_my_ini():
    """USB modunda my.ini dinamik yaz (drive letter değişebilir)."""
    ini_path = os.path.join(MARIADB_DIR, "my.ini")
    data_fwd = DATA_DIR.replace("\\", "/")
    tmp_dir  = os.path.join(MARIADB_DIR, "tmp").replace("\\", "/")
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
key_buffer_size         = 256M
myisam_sort_buffer_size = 64M

[client]
port    = {MYSQL_PORT}
default-character-set = utf8mb4
""")
    return ini_path

def start_mariadb():
    global _mariadb_proc
    if not port_free(MYSQL_PORT): return True
    if not os.path.exists(MYSQLD_EXE):
        show_error("MariaDB Hatası", f"mysqld.exe bulunamadı:\n{MYSQLD_EXE}")
        return False
    # USB modunda my.ini dinamik yaz
    if IS_USB:
        try:
            write_my_ini()
        except PermissionError:
            # my.ini yazılamıyor — read-only USB veya izin sorunu
            # mevcut my.ini kullan, devam et
            pass
    ini_path = os.path.join(MARIADB_DIR, "my.ini")
    _mariadb_proc = subprocess.Popen(
        [MYSQLD_EXE, f"--defaults-file={ini_path}", "--console"],
        stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    wait_sec = 90 if IS_USB else 30
    for _ in range(wait_sec * 2):
        if not port_free(MYSQL_PORT): return True
        time.sleep(0.5)
    show_error("MariaDB başlatılamadı", f"Log: {LOG_FILE}")
    return False

def stop_mariadb():
    global _mariadb_proc
    if _mariadb_proc:
        try: _mariadb_proc.terminate(); _mariadb_proc.wait(timeout=10)
        except: pass
        _mariadb_proc = None

def check_update_background():
    time.sleep(5)
    try:
        import urllib.request, json, urllib.parse
        with urllib.request.urlopen(GITHUB_RAW_URL, timeout=5) as r:
            data = json.loads(r.read().decode())
        remote = data.get("version","0")
        if remote > CURRENT_VERSION:
            notes = data.get("notes","")
            url   = data.get("download_url","")
            try:
                urllib.request.urlopen(
                    f"http://localhost:5001/api/set_update?v={remote}&notes={urllib.parse.quote(notes)}&url={urllib.parse.quote(url)}",
                    timeout=3)
            except: pass
    except: pass

def apply_efs_encryption():
    flag = os.path.join(MARIADB_DIR, ".efs_done")
    if os.path.exists(flag): return
    try:
        result = subprocess.run(
            f'cipher /e /s:"{DATA_DIR}"',
            shell=True, capture_output=True, timeout=1800, creationflags=0x08000000)
        if result.returncode == 0:
            open(flag, "w").close()
    except: pass

def main():
    # USB modunda cache kopyala (arka planda)
    if IS_USB:
        threading.Thread(target=ensure_local_cache, daemon=True).start()

    # Lisans kontrol
    try:
        sys.path.insert(0, BASE_DIR)
        from sorgu_license import check_license
        lic_path = os.path.join(BASE_DIR, "license.lic")
        ok, msg, lic_data = check_license(lic_path)
        if not ok:
            show_error("Lisans Hatası", f"Sorgu Sistemi çalıştırılamadı:\n\n{msg}\n\nYöneticinizle iletişime geçin.")
            return
        # Makine ID kontrolü (USB_ANY ise atla)
        lic_machine = lic_data.get("machine_id","")
        if lic_machine and lic_machine != "USB_ANY":
            from sorgu_license import get_machine_id as _gmid
            cur_mid = _gmid()
            if cur_mid != lic_machine:
                show_error("Lisans Hatası",
                    f"Bu lisans başka bir bilgisayar için oluşturulmuş.\n\nYöneticinizle iletişime geçin.")
                return

        # USB serial kontrolü
        if IS_USB and lic_data.get("usb_serial"):
            cur_serial = get_usb_serial()
            if cur_serial != lic_data["usb_serial"]:
                show_error("USB Hatası",
                    f"Lisans USB serial : {lic_data['usb_serial']}\n"
                    f"Mevcut USB serial : {cur_serial}\n\nDoğru USB'yi takın.")
                return
    except ImportError:
        pass

    if not start_mariadb(): return
    atexit.register(stop_mariadb)

    threading.Thread(target=apply_efs_encryption, daemon=True).start()
    threading.Thread(target=check_update_background, daemon=True).start()

    def run_flask():
        try:
            import sorgu_app
            sorgu_app.app.run(host="127.0.0.1", port=5001,
                              debug=False, threaded=True, use_reloader=False)
        except Exception as e:
            show_error("Flask Hatası", str(e))

    threading.Thread(target=run_flask, daemon=True).start()
    # USB'de yavaş başlar — daha uzun bekle
    delay = 5.0 if IS_USB else 2.0
    threading.Timer(delay, lambda: webbrowser.open("http://localhost:5001")).start()

    try:
        import tkinter as tk
        root = tk.Tk(); root.withdraw(); root.mainloop()
    except:
        while True: time.sleep(1)

if __name__ == "__main__":
    main()
