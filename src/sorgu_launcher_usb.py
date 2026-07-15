"""
Sorgu Sistemi USB Launcher v1.0
- USB'nin drive letter'ını otomatik tespit eder
- MariaDB'yi USB'deki data ile başlatır
- Lisans: USB serial + Makine ID kontrolü
- Kapatınca MariaDB'yi durdurur
PyInstaller ile exe'ye dönüştürülür.
"""
import sys, os, subprocess, time, socket, threading, webbrowser, atexit

IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR  = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))

# USB klasör yapısı:
# [USB]:\ → SorguSistemi.exe, license.lic
# [USB]:\MariaDB\bin\mysqld.exe
# [USB]:\MariaDB\data\

MARIADB_DIR = os.path.join(BASE_DIR, "MariaDB")
MYSQLD_EXE  = os.path.join(MARIADB_DIR, "bin", "mysqld.exe")
DATA_DIR    = os.path.join(MARIADB_DIR, "data")
MYSQL_PORT  = 3307
LOG_FILE    = os.path.join(BASE_DIR, "sorgu.log")

_mariadb_proc = None


CURRENT_VERSION = "4.0.3"
GITHUB_RAW_URL  = "https://raw.githubusercontent.com/bLackSunshine2693/sorgu-version/main/version.json"

def check_update_background():
    """Arka planda güncelleme kontrol."""
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
    """Exe'nin bulunduğu sürücünün volume serial'ını al."""
    try:
        drive = os.path.splitdrive(path)[0] or "C:"
        flags = 0x08000000
        out = subprocess.check_output(
            f"vol {drive}", shell=True,
            stderr=subprocess.DEVNULL, timeout=5, creationflags=flags
        ).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            if "Serial" in line and "is" in line:
                return line.split("is")[-1].strip().replace("-", "")
    except: pass
    return ""

def write_my_ini():
    """my.ini'yi runtime'da dinamik path ile oluştur — USB drive değişse de çalışır."""
    ini_path = os.path.join(MARIADB_DIR, "my.ini")
    # Forward slash — MariaDB Windows'ta kabul eder
    data_dir_fwd  = DATA_DIR.replace("\\", "/")
    tmp_dir       = os.path.join(MARIADB_DIR, "tmp").replace("\\", "/")
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
        return True  # zaten çalışıyor

    if not os.path.exists(MYSQLD_EXE):
        show_error("USB Hatası",
            f"MariaDB USB'de bulunamadı:\n{MYSQLD_EXE}\n\n"
            "USB'nin doğru takıldığından emin olun.")
        return False

    ini_path = write_my_ini()

    args = [
        MYSQLD_EXE,
        f"--defaults-file={ini_path}",
        "--console",
    ]
    _mariadb_proc = subprocess.Popen(
        args, stdout=open(LOG_FILE, "a"), stderr=subprocess.STDOUT,
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
            log_file = os.path.join(BASE_DIR, "sorgu.log")
            with open(log_file, "a") as f:
                f.write("EFS şifreleme tamamlandı\n")
    except Exception as e:
        pass

def stop_mariadb():
    global _mariadb_proc
    if _mariadb_proc:
        try: _mariadb_proc.terminate(); _mariadb_proc.wait(timeout=10)
        except: pass
        _mariadb_proc = None

def create_shortcut():
    """Masaüstüne kısayol oluştur — her çalışmada günceller (drive letter değişebilir)."""
    try:
        import win32com.client
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        lnk_path = os.path.join(desktop, "Sorgu Sistemi.lnk")
        exe_path = sys.executable if IS_FROZEN else os.path.abspath(__file__)

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        shortcut.TargetPath   = exe_path
        shortcut.WorkingDirectory = BASE_DIR
        shortcut.Description  = "Sorgu Sistemi"
        shortcut.IconLocation = exe_path
        shortcut.save()
    except:
        # win32com yoksa PowerShell ile oluştur
        try:
            desktop  = os.path.join(os.path.expanduser("~"), "Desktop")
            lnk_path = os.path.join(desktop, "Sorgu Sistemi.lnk")
            exe_path = sys.executable if IS_FROZEN else os.path.abspath(__file__)
            ps = f'''$ws=New-Object -ComObject WScript.Shell
$s=$ws.CreateShortcut('{lnk_path}')
$s.TargetPath='{exe_path}'
$s.WorkingDirectory='{BASE_DIR}'
$s.Description='Sorgu Sistemi'
$s.IconLocation='{exe_path}'
$s.Save()'''
            subprocess.run(["powershell", "-Command", ps],
                         creationflags=0x08000000, capture_output=True, timeout=10)
        except: pass


    """
    data klasörüne NTFS kilidi uygula — otomatik, drive letter bağımsız.
    İlk çalışmada bir kere çalışır, flag dosyası bırakır.
    """
    flag = os.path.join(MARIADB_DIR, ".locked")
    if os.path.exists(flag):
        return  # zaten kilitli

    try:
        cmds = [
            f'icacls "{DATA_DIR}" /inheritance:r /T /Q',
            f'icacls "{DATA_DIR}" /grant SYSTEM:(OI)(CI)F /T /Q',
            f'icacls "{DATA_DIR}" /grant Administrators:(OI)(CI)F /T /Q',
            f'icacls "{DATA_DIR}" /deny Users:(OI)(CI)RX /T /Q',
        ]
        for cmd in cmds:
            subprocess.run(cmd, shell=True, creationflags=0x08000000,
                         capture_output=True, timeout=30)
        # Flag bırak — bir daha çalışmasın
        open(flag, "w").close()
    except:
        pass  # izin hatası olsa bile devam et


    global _mariadb_proc
    if _mariadb_proc:
        try: _mariadb_proc.terminate(); _mariadb_proc.wait(timeout=10)
        except: pass
        _mariadb_proc = None

def main():
    # ── LİSANS KONTROLÜ ──────────────────────────────────────────────────
    try:
        sys.path.insert(0, BASE_DIR)
        from sorgu_license import check_license, get_machine_id
        import hashlib

        lic_path = os.path.join(BASE_DIR, "license.lic")
        ok, msg, lic_data = check_license(lic_path)

        if not ok:
            show_error("Lisans Hatası",
                f"Sorgu Sistemi çalıştırılamadı:\n\n{msg}\n\n"
                "Yöneticinizle iletişime geçin.")
            return

        # USB serial kontrolü — lisansta usb_serial varsa mutlaka eşleşmeli
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
        pass  # geliştirme modunda lisans kontrolü yok

    # Eski instance'ı kapat
    try:
        out = subprocess.check_output('netstat -ano | findstr ":5001 "',
            shell=True, creationflags=0x08000000, stderr=subprocess.DEVNULL, timeout=5
        ).decode(errors='ignore')
        for line in out.splitlines():
            if ':5001' in line and 'LISTENING' in line:
                pid = line.strip().split()[-1]
                subprocess.run(f'taskkill /PID {pid} /T /F', shell=True,
                             capture_output=True, creationflags=0x08000000)
                time.sleep(1.5); break
    except: pass

    # Masaüstü kısayolu oluştur
    create_shortcut()

    # ── MARİADB BAŞLAT ───────────────────────────────────────────────────
    if not start_mariadb():
        return
    atexit.register(stop_mariadb)

    # EFS şifrelemesi arka planda
    threading.Thread(target=apply_efs_encryption, daemon=True).start()

    # Flask arka planda başlat
    def run_flask():
        try:
            import sorgu_app
            sorgu_app.MARIADB["port"] = MYSQL_PORT
            sorgu_app.app.run(host="127.0.0.1", port=5001,
                              debug=False, threaded=True, use_reloader=False)
        except Exception as e:
            show_error("Flask Hatası", str(e))

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Timer(2.0, lambda: webbrowser.open("http://localhost:5001")).start()
    threading.Thread(target=check_update_background, daemon=True).start()

    # Ana thread canlı tut
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop_mariadb()

if __name__ == "__main__":
    main()
