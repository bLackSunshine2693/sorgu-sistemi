"""Sorgu Sistemi Lisans Motoru v1.0"""
import hashlib, json, os, sys, subprocess, base64, datetime
from pathlib import Path
import hmac as _hmac

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    _CRYPTO = True
except ImportError:
    _CRYPTO = False

MASTER_SECRET   = b"SorguSistemi_Master_2024_xK9mP3qR7nT"
ADMIN_PASS_HASH = hashlib.sha256("admin_sorgu_2024".encode()).hexdigest()
LICENSE_FILE    = "license.lic"

def _wmic(query):
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.check_output(f"wmic {query}", shell=True,
              stderr=subprocess.DEVNULL, timeout=5, creationflags=flags
              ).decode("utf-8", errors="ignore")
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        return lines[-1] if len(lines) > 1 else ""
    except:
        return ""

def get_machine_id():
    BAD  = {"To Be Filled By O.E.M.", "Default string", "None", ""}
    srcs = [s for s in [_wmic("cpu get ProcessorId"),
                         _wmic("baseboard get SerialNumber"),
                         _wmic("bios get SerialNumber")] if s not in BAD]
    if not srcs:
        import uuid; srcs = [str(uuid.getnode())]
    return hashlib.sha256("|".join(sorted(srcs)).encode()).hexdigest()[:32]

def get_usb_serial(drive_letter=None):
    try:
        if not drive_letter:
            exe = sys.executable if getattr(sys, "frozen", False) else __file__
            drive_letter = os.path.splitdrive(exe)[0] or "C:"
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.check_output(f"vol {drive_letter}", shell=True,
              stderr=subprocess.DEVNULL, timeout=5, creationflags=flags
              ).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            if "Serial" in line and "is" in line:
                return line.split("is")[-1].strip().replace("-", "")
    except:
        pass
    return ""

def _derive_key(machine_id):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=MASTER_SECRET[:16], iterations=100_000)
    return kdf.derive((MASTER_SECRET + machine_id.encode())[:64])

def encrypt_license(data, machine_id):
    key    = _derive_key(machine_id)
    nonce  = os.urandom(12)
    plain  = json.dumps(data, ensure_ascii=False).encode()
    ct     = AESGCM(key).encrypt(nonce, plain, None)
    sig    = _hmac.new(MASTER_SECRET, nonce + ct, hashlib.sha256).digest()
    return base64.b85encode(sig + nonce + ct)

def decrypt_license(blob, machine_id):
    try:
        raw   = base64.b85decode(blob)
        sig   = raw[:32]; nonce = raw[32:44]; ct = raw[44:]
        exp   = _hmac.new(MASTER_SECRET, nonce + ct, hashlib.sha256).digest()
        if not _hmac.compare_digest(sig, exp): return None
        plain = AESGCM(_derive_key(machine_id)).decrypt(nonce, ct, None)
        return json.loads(plain.decode())
    except:
        return None

def create_license(machine_id, plan, days, branch, issued_to, license_id, usb_serial=""):
    today = datetime.date.today()
    data  = {
        "license_id": license_id, "machine_id": machine_id,
        "usb_serial": usb_serial, "plan": plan,
        "issued_to":  issued_to,  "branch": branch,
        "start_date": today.isoformat(),
        "end_date":   (today + datetime.timedelta(days=int(days))).isoformat() if days else "SINIRSIZ",
        "created_at": datetime.datetime.now().isoformat(),
    }
    return encrypt_license(data, machine_id)

def check_license(lic_path=LICENSE_FILE):
    path = Path(lic_path)
    if not path.exists():
        return False, "Lisans dosyası bulunamadı.", {}
    blob = path.read_bytes().strip()
    mid  = get_machine_id()
    data = decrypt_license(blob, mid)
    if data is None:
        return False, "Lisans geçersiz veya bu makineye ait değil.", {}
    if data.get("machine_id") != mid:
        return False, "Makine kimliği eşleşmiyor.", {}
    if data.get("usb_serial"):
        usb = get_usb_serial()
        if usb and usb != data["usb_serial"]:
            return False, "USB seri numarası eşleşmiyor.", {}
    if data.get("end_date") != "SINIRSIZ":
        try:
            end   = datetime.date.fromisoformat(data["end_date"])
            today = datetime.date.today()
            if today > end:
                return False, f"Lisans {(today-end).days} gün önce sona erdi. ({end})", data
            kalan = (end - today).days
            return True, f"{data['plan']} lisans — {kalan} gün kaldı", data
        except:
            return False, "Lisans tarihi okunamadı.", data
    return True, f"{data['plan']} lisans — Sınırsız", data
