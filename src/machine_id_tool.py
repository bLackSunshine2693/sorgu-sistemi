# -*- coding: utf-8 -*-
"""Machine ID Tool - Sorgu Sistemi"""
import subprocess, hashlib, sys, os

def _wmic(query):
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        out = subprocess.check_output(f"wmic {query}", shell=True,
              stderr=subprocess.DEVNULL, timeout=5, creationflags=flags
              ).decode("utf-8", errors="ignore")
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        return lines[-1] if len(lines) > 1 else "?"
    except:
        return "?"

print("=" * 55)
print("  SORGU SISTEMI - MAKINE KIMLIGI TESPIT ARACI")
print("=" * 55)

cpu   = _wmic("cpu get ProcessorId")
board = _wmic("baseboard get SerialNumber")
bios  = _wmic("bios get SerialNumber")

print(f"\n  CPU ID    : {cpu}")
print(f"  Anakart   : {board}")
print(f"  BIOS      : {bios}")

BAD   = {"To Be Filled By O.E.M.", "Default string", "None", "?", ""}
srcs  = [s for s in [cpu, board, bios] if s not in BAD]
if not srcs:
    import uuid; srcs = [str(uuid.getnode())]

machine_id = hashlib.sha256("|".join(sorted(srcs)).encode()).hexdigest()[:32]

print(f"\n  ---------------------------------------------------")
print(f"  MAKINE ID : {machine_id}")
print(f"  ---------------------------------------------------")

try:
    exe_drive = os.path.splitdrive(sys.executable)[0] or "C:"
    flags = 0x08000000 if sys.platform == "win32" else 0
    out = subprocess.check_output(f"vol {exe_drive}", shell=True,
          stderr=subprocess.DEVNULL, timeout=5, creationflags=flags
          ).decode("utf-8", errors="ignore")
    for line in out.splitlines():
        if "Serial" in line and "is" in line:
            usb = line.split("is")[-1].strip().replace("-","")
            print(f"  USB/Disk  : {usb} (surucu: {exe_drive})")
            break
except:
    pass

print(f"\n  Bu bilgileri yoneticinize gonderin.")
print(f"  Lisans dosyasi hazirlanip tarafiniza iletilecektir.")
print("=" * 55)
input("\n  Cikis icin Enter'a basin...")
