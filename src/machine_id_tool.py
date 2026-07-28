import os, sys, hashlib, ctypes

def get_machine_id():
    try:
        import subprocess
        results = []
        for cmd in [
            "wmic cpu get processorid /value",
            "wmic baseboard get serialnumber /value", 
            "wmic bios get serialnumber /value"
        ]:
            try:
                out = subprocess.check_output(cmd, shell=True, timeout=10,
                    creationflags=0x08000000, stderr=subprocess.DEVNULL).decode(errors="ignore")
                for line in out.splitlines():
                    if "=" in line:
                        v = line.split("=",1)[1].strip()
                        if v and v not in ("To Be Filled By O.E.M.","Default string","","None"):
                            results.append(v)
            except: pass
        if not results:
            return "ALINAMADI"
        return hashlib.sha256("|".join(sorted(results)).encode()).hexdigest()[:32]
    except Exception as e:
        return f"HATA: {e}"

def get_usb_serial():
    try:
        import subprocess
        out = subprocess.check_output(
            "wmic logicaldisk where drivetype=2 get volumeserialnumber,caption /value",
            shell=True, timeout=10, creationflags=0x08000000,
            stderr=subprocess.DEVNULL).decode(errors="ignore")
        serials = {}
        cur = ""
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Caption="): cur = line.split("=",1)[1].strip()
            elif line.startswith("VolumeSerialNumber="):
                s = line.split("=",1)[1].strip()
                if s and cur: serials[cur] = s
        return serials
    except: return {}

try:
    os.system("cls")
    print("=" * 55)
    print("    SORGU SİSTEMİ — MAKİNE ID ARACI")
    print("=" * 55)
    
    mid = get_machine_id()
    print(f"\n  MAKİNE ID:")
    print(f"  {mid}")
    
    usb = get_usb_serial()
    if usb:
        print("\n  USB SÜRÜCÜLER:")
        for cap, ser in usb.items():
            print(f"    {cap}  ➜  {ser}")
    else:
        print("\n  USB: Takılı USB bulunamadı")
    
    print("\n" + "=" * 55)
    print("  Bu bilgileri yöneticinize iletiniz.")
    print("=" * 55)

except Exception as e:
    print(f"\nHATA OLUSTU: {e}")

finally:
    print("\n  Cikis icin ENTER'a basin...")
    try:
        input()
    except:
        os.system("pause")
