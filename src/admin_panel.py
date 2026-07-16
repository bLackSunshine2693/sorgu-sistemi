"""Sorgu Sistemi Admin Paneli v2.0"""
import os,sys,sqlite3,hashlib,datetime,threading,webbrowser,socket,logging
from pathlib import Path
from flask import Flask,request,jsonify,session

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)-7s %(message)s",datefmt="%H:%M:%S")
log=logging.getLogger("admin")

ADMIN_PASSWORD_HASH="35ce5f0804be4660182f9df72f5b18f5f371d1d84565c6841acf608b57c2f608"
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from sorgu_license import MASTER_SECRET,create_license,get_machine_id,get_usb_serial,_CRYPTO

BASE_DIR=Path(__file__).parent
DB_PATH=BASE_DIR/"licenses.db"
app=Flask(__name__)
app.secret_key="admin_panel_secret_2026_NEW_xK9"
app.config['JSON_SORT_KEYS']=False

def init_db():
    conn=sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,branch TEXT DEFAULT '',
        quota INTEGER DEFAULT 10,notes TEXT DEFAULT '',
        created_at TEXT NOT NULL,active INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS licenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        license_id TEXT UNIQUE NOT NULL,
        customer_id INTEGER NOT NULL,
        machine_id TEXT NOT NULL,usb_serial TEXT DEFAULT '',
        plan TEXT DEFAULT 'YILLIK',
        start_date TEXT NOT NULL,end_date TEXT NOT NULL,
        license_file TEXT NOT NULL,
        active INTEGER DEFAULT 1,created_at TEXT NOT NULL,
        FOREIGN KEY(customer_id) REFERENCES customers(id))""")
    conn.commit();conn.close()

def db():
    c=sqlite3.connect(DB_PATH);c.row_factory=sqlite3.Row;return c

def next_lic_id():
    conn=db();cur=conn.cursor()
    cur.execute("SELECT COUNT(*) FROM licenses");n=cur.fetchone()[0];conn.close()
    return f"LIC-{n+1:04d}"

@app.route("/")
def index():return ADMIN_HTML

@app.route("/api/login",methods=["POST"])
def api_login():
    d=request.get_json(force=True) or {}
    if hashlib.sha256(d.get("password","").encode()).hexdigest()==ADMIN_PASSWORD_HASH:
        session["admin"]=True;return jsonify({"ok":True})
    return jsonify({"ok":False}),401

@app.route("/api/logout",methods=["POST"])
def api_logout():session.clear();return jsonify({"ok":True})

@app.route("/api/stats")
def api_stats():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();cur=conn.cursor();today=datetime.date.today().isoformat()
    cur.execute("SELECT COUNT(*) FROM customers WHERE active=1");total=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM licenses WHERE active=1 AND end_date<? AND end_date!='SINIRSIZ'",[today]);expired=cur.fetchone()[0]
    d30=(datetime.date.today()+datetime.timedelta(30)).isoformat()
    cur.execute("SELECT COUNT(*) FROM licenses WHERE active=1 AND end_date>=? AND end_date<=?",[today,d30]);expiring=cur.fetchone()[0]
    conn.close()
    return jsonify({"total":total,"expired":expired,"expiring_soon":expiring})

@app.route("/api/customers")
def api_customers():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();cur=conn.cursor()
    cur.execute("SELECT * FROM customers WHERE active=1 ORDER BY created_at DESC")
    custs=[dict(r) for r in cur.fetchall()]
    today=datetime.date.today()
    for c in custs:
        cur.execute("SELECT * FROM licenses WHERE customer_id=? AND active=1",[c["id"]])
        lics=[dict(r) for r in cur.fetchall()]
        c["pc_count"]=sum(1 for l in lics if not l["usb_serial"])
        c["usb_count"]=sum(1 for l in lics if l["usb_serial"])
        c["used"]=len(lics)
        dates=[l["end_date"] for l in lics if l["end_date"]!="SINIRSIZ"]
        if dates:
            nearest=min(dates)
            c["nearest_end"]=nearest
            try:c["nearest_days"]=(datetime.date.fromisoformat(nearest)-today).days
            except:c["nearest_days"]=999
        else:c["nearest_end"]="SINIRSIZ";c["nearest_days"]=9999
    conn.close()
    return jsonify(custs)

@app.route("/api/customers",methods=["POST"])
def api_create_customer():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    d=request.get_json(force=True) or {}
    if not d.get("name"):return jsonify({"error":"Müşteri adı zorunludur"}),400
    conn=db()
    conn.execute("INSERT INTO customers(name,branch,quota,notes,created_at) VALUES(?,?,?,?,?)",
        [d["name"].strip(),d.get("branch","").strip(),int(d.get("quota",10)),
         d.get("notes",""),datetime.datetime.now().isoformat()])
    cid=conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit();conn.close()
    return jsonify({"ok":True,"customer_id":cid})

@app.route("/api/customers/<int:cid>",methods=["DELETE"])
def api_delete_customer(cid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db()
    conn.execute("UPDATE customers SET active=0 WHERE id=?",[cid])
    conn.execute("UPDATE licenses SET active=0 WHERE customer_id=?",[cid])
    conn.commit();conn.close()
    return jsonify({"ok":True})

@app.route("/api/customers/<int:cid>/licenses")
def api_cust_licenses(cid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();cur=conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id=?",[cid]);cust=dict(cur.fetchone())
    cur.execute("SELECT * FROM licenses WHERE customer_id=? AND active=1 ORDER BY created_at DESC",[cid])
    lics=[dict(r) for r in cur.fetchall()]
    today=datetime.date.today()
    for l in lics:
        if l["end_date"]=="SINIRSIZ":l["days"]=99999
        else:
            try:l["days"]=(datetime.date.fromisoformat(l["end_date"])-today).days
            except:l["days"]=0
    conn.close()
    return jsonify({"customer":cust,"licenses":lics})

@app.route("/api/customers/<int:cid>/licenses",methods=["POST"])
def api_create_device(cid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    d=request.get_json(force=True) or {}
    conn=db();cur=conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id=?",[cid]);cust=dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) FROM licenses WHERE customer_id=? AND active=1",[cid]);used=cur.fetchone()[0]
    if used>=cust["quota"]:conn.close();return jsonify({"error":f"Kota dolu! ({used}/{cust['quota']})"}),400
    machine_id=d.get("machine_id","").strip()
    admin_mod=bool(d.get("admin_mod",False))
    usb_serial=d.get("usb_serial","").strip()
    start_date=d.get("start_date",datetime.date.today().isoformat())
    end_date=d.get("end_date","")
    if not machine_id:conn.close();return jsonify({"error":"Makine ID zorunludur"}),400
    if not end_date:end_date="SINIRSIZ"
    try:
        if end_date!="SINIRSIZ":
            days=(datetime.date.fromisoformat(end_date)-datetime.date.fromisoformat(start_date)).days
        else:days=None
    except:days=None;end_date="SINIRSIZ"
    plan="YILLIK" if (days and 300<=days<=400) else "AYLIK" if (days and days<=35) else "SINIRSIZ" if not days else "OZEL"
    lic_id=next_lic_id()
    lic_bytes=create_license(machine_id=machine_id,plan=plan,days=days,
        branch=cust.get("branch",""),issued_to=cust["name"],
        license_id=lic_id,usb_serial=usb_serial,admin_mod=admin_mod)
    conn.execute("INSERT INTO licenses(license_id,customer_id,machine_id,usb_serial,plan,start_date,end_date,license_file,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        [lic_id,cid,machine_id,usb_serial,plan,start_date,end_date,lic_bytes.decode("ascii"),datetime.datetime.now().isoformat()])
    conn.commit();conn.close()
    return jsonify({"ok":True,"license_id":lic_id,"license_file":lic_bytes.decode("ascii")})

@app.route("/api/licenses/<int:lid>/extend",methods=["POST"])
def api_extend(lid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    d=request.get_json(force=True) or {}
    new_end=d.get("end_date","")
    if not new_end:return jsonify({"error":"Bitiş tarihi gereklidir"}),400
    conn=db();cur=conn.cursor()
    cur.execute("SELECT l.*,c.name,c.branch FROM licenses l JOIN customers c ON l.customer_id=c.id WHERE l.id=?",[lid])
    row=dict(cur.fetchone())
    try:
        days=(datetime.date.fromisoformat(new_end)-datetime.date.fromisoformat(row["start_date"])).days if new_end!="SINIRSIZ" else None
    except:days=None;new_end="SINIRSIZ"
    plan="YILLIK" if (days and 300<=days<=400) else "AYLIK" if (days and days<=35) else "SINIRSIZ" if not days else "OZEL"
    lic_bytes=create_license(machine_id=row["machine_id"],plan=plan,days=days,
        branch=row["branch"],issued_to=row["name"],license_id=row["license_id"],usb_serial=row["usb_serial"])
    conn.execute("UPDATE licenses SET end_date=?,plan=?,license_file=? WHERE id=?",[new_end,plan,lic_bytes.decode("ascii"),lid])
    conn.commit();conn.close()
    return jsonify({"ok":True,"license_file":lic_bytes.decode("ascii"),"end_date":new_end})

@app.route("/api/licenses/<int:lid>",methods=["DELETE"])
def api_del_license(lid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();conn.execute("UPDATE licenses SET active=0 WHERE id=?",[lid]);conn.commit();conn.close()
    return jsonify({"ok":True})

@app.route("/api/machine_id")
def api_machine_id():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    return jsonify({"machine_id":get_machine_id(),"usb_serial":get_usb_serial()})


ADMIN_HTML = r"""
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lisans Yönetim Paneli</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        color-scheme: dark;
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0b111e; }
        ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 4px; }
    </style>
</head>
<body class="bg-[#0b111e] text-slate-200 font-sans min-h-screen p-4 md:p-6 w-full overflow-x-hidden relative">
<!-- GİRİŞ EKRANI -->
<div id="loginScreen" class="fixed inset-0 flex items-center justify-center bg-[#0b111e] z-50">
    <div class="bg-[#111a2e] border border-slate-800 rounded-2xl p-10 w-80 text-center shadow-2xl">
        <div class="text-4xl mb-3">🔐</div>
        <h2 class="text-sm font-bold text-white mb-1">Admin Paneli</h2>
        <p class="text-xs text-slate-500 mb-6">Sorgu Sistemi Lisans Yönetimi</p>
        <input type="password" id="pwdInput" placeholder="Şifre"
            class="w-full bg-[#0b111e] border border-slate-700 rounded px-3 py-2.5 text-sm text-slate-200 outline-none focus:border-blue-500 mb-3"
            onkeydown="if(event.key==='Enter')doLogin()">
        <button onclick="doLogin()" class="w-full bg-blue-600 hover:bg-blue-500 text-white text-sm font-bold py-2.5 rounded transition">Giriş Yap</button>
        <div id="loginErr" class="mt-3 text-xs text-red-400 hidden">Hatalı şifre.</div>
    </div>
</div>

<!-- LİSANS MODAL -->
<div id="licModal" class="fixed inset-0 z-[60] items-center justify-center" style="display:none">
    <div class="absolute inset-0 bg-black/70" onclick="closeLicModal()"></div>
    <div class="relative bg-[#111a2e] border border-slate-700 rounded-2xl p-6 w-full max-w-lg mx-4 shadow-2xl">
        <h3 class="text-sm font-bold text-white mb-1">🔑 Lisans Dosyası Hazır</h3>
        <p class="text-xs text-slate-400 mb-3">İçeriği kopyalayın veya indirin — <b>license.lic</b> olarak kaydedin</p>
        <div id="licContent" class="bg-[#0b111e] border border-slate-800 rounded p-3 text-[11px] font-mono text-emerald-400 break-all max-h-48 overflow-y-auto mb-4"></div>
        <div class="flex gap-2 justify-end">
            <button onclick="copyLic()" class="bg-emerald-600/20 border border-emerald-600/30 text-emerald-400 hover:bg-emerald-600 hover:text-white px-4 py-2 rounded text-xs font-semibold transition">📋 Kopyala</button>
            <button onclick="downloadLic()" class="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded text-xs font-semibold transition">⬇️ İndir (.lic)</button>
            <button onclick="closeLicModal()" class="border border-slate-700 text-slate-400 hover:text-white px-4 py-2 rounded text-xs transition">Kapat</button>
        </div>
    </div>
</div>

<div id="mainApp" class="hidden">


    <div class="w-full space-y-6">
        
        <!-- 🔔 SÜRESİ YAKLAŞAN LİSANSLAR UYARI MERKEZİ (SON 10 GÜN) -->
        <div id="expirationAlertPanel" class="bg-red-950/40 border border-red-900/60 rounded-xl p-4 shadow-lg hidden">
            <div class="flex items-start gap-3">
                <div class="text-red-500 text-lg mt-0.5 shrink-0">
                    <i class="fa-solid fa-triangle-exclamation animate-pulse"></i>
                </div>
                <div class="flex-1">
                    <h4 class="text-xs font-bold text-red-400 uppercase tracking-wider mb-1">Kritik Süre Uyarı Merkezi (Son 10 Gün)</h4>
                    <ul id="alertList" class="text-xs text-slate-300 space-y-1 list-disc list-inside">
                        <!-- JavaScript otomatik doldurur -->
                    </ul>
                </div>
            </div>
        </div>
        
        <!-- ÜST İSTATİSTİK KARTLARI -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6">
            <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
                <div id="statTotal" class="text-3xl font-bold text-blue-500 mb-1">—</div>
                <div class="text-xs text-slate-400 uppercase tracking-wider">Toplam Lisans</div>
            </div>
            <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
                <div class="text-3xl font-bold text-red-500 mb-1" id="expiredCountCard">0</div>
                <div class="text-xs text-slate-400 uppercase tracking-wider">Süresi Dolmuş / Az Kalmış</div>
            </div>
            <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
                <div id="statWarn" class="text-3xl font-bold text-amber-500 mb-1">—</div>
                <div class="text-xs text-slate-400 uppercase tracking-wider">30 Gün İçinde Bitecek</div>
            </div>
        </div>

        <!-- YENİ LİSANS OLUŞTURMA FORMU -->
        <div class="bg-[#111a2e] border border-slate-800/80 rounded-xl p-6 shadow-xl">
            <div class="flex justify-between items-center mb-6 flex-wrap gap-2">
                <h2 class="text-sm font-semibold text-white flex items-center gap-2">
                    <span class="text-blue-500 text-lg">+</span> Yeni Lisans Oluştur
                </h2>
                <button onclick="getMachineId()" class="bg-[#1a263e] hover:bg-slate-700 text-xs text-slate-300 px-4 py-2 rounded border border-slate-700 transition">Bu Bilgisayarın MAC ID'sini Al</button>
            </div>

            <form class="space-y-5" onsubmit="event.preventDefault();">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">MAC ID *</label>
                        <input type="text" id="fMid" placeholder="wmic veya mac adresi..." class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">USB SERİ NO (USB VERSİYONU)</label>
                        <input type="text" id="fUsb" placeholder="Boş bırakılabilir" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">MÜŞTERI / KULLANICI ADI *</label>
                        <input type="text" id="fName" placeholder="Ad Soyad veya Kurum" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">TOPLAM LİSANS KOTASI (ADET) *</label>
                        <input id="fQuota" type="number" min="1" value="10" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">BAŞLANGIÇ TARİHİ *</label>
                        <input type="date" id="mainStart" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300">
                    </div>
                    <div>
                        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">BİTİŞ TARİHİ *</label>
                        <input type="date" id="mainEnd" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300">
                    </div>
                </div>
                <div class="pt-2">
                    <button onclick="createMainLicense()" class="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-5 py-2.5 rounded shadow-lg transition flex items-center gap-2"><i class="fa-solid fa-key text-[11px]"></i> Lisans Oluştur
                    </button>
                </div>
            </form>
        </div>

        <!-- LİSANS LİSTESİ TABLOSU -->
        <div class="bg-[#111a2e] border border-slate-800/80 rounded-xl shadow-xl overflow-hidden">
            <div class="p-4 border-b border-slate-800 flex justify-between items-center bg-[#131d33]">
                <h3 class="text-sm font-semibold text-white flex items-center gap-2">
                    📄 Tüm Lisanslar
                </h3>
                <button onclick="loadAll()" class="text-xs text-slate-400 hover:text-white flex items-center gap-1 bg-[#0b111e] px-3 py-1.5 rounded border border-slate-800 transition"><i class="fa-solid fa-rotate-right text-[10px]"></i> Yenile</button>
            </div>
            
            <div class="overflow-x-auto w-full">
                <table class="w-full text-left border-collapse min-w-[1000px]">
                    <thead>
                        <tr class="border-b border-slate-800 text-[11px] text-slate-400 uppercase tracking-wider bg-[#0f172a]">
                            <th class="p-4 font-semibold">ID</th>
                            <th class="p-4 font-semibold">Müşteri Adı</th>
                            <th class="p-4 font-semibold">PC/USB Bilgisi</th>
                            <th class="p-4 font-semibold">Başlangıç</th>
                            <th class="p-4 font-semibold">Bitiş</th>
                            <th class="p-4 font-semibold">Kalan Süre</th>
                            <th class="p-4 font-semibold text-center">Kullanılan / Kota</th>
                            <th class="p-4 font-semibold text-center">İşlem</th>
                        </tr>
                    </thead>
                    <tbody id="licBody" class="text-xs text-slate-300 divide-y divide-slate-800/50">
                        <tr class="hover:bg-slate-800/30 transition">
                            <td class="p-4 font-medium text-slate-400">LIC-0001</td>
                            <td class="p-4 font-semibold text-white">Ahmet Yılmaz (Yılmaz Lojistik)</td>
                            <td class="p-4">
                                <span id="mainTableDeviceCounts" class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[11px] font-medium">
                                    0 PC, 0 USB
                                </span>
                            </td>
                            <td class="p-4 text-slate-400">2026-07-12</td>
                            <td class="p-4 text-slate-400">2027-07-12</td>
                            <td class="p-4">
                                <span class="bg-emerald-950/80 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded-full text-[10px]">365 gün</span>
                            </td>
                            <td class="p-4 text-center">
                                <div class="font-bold text-slate-200 text-sm"><span id="mainTableUsed">2</span> <span class="text-slate-500 font-normal text-xs">/ 10</span></div>
                                <div class="w-20 bg-slate-800 h-1 rounded overflow-hidden mx-auto mt-1">
                                    <div id="mainTableProgress" class="bg-blue-500 h-full" style="width: 20%"></div>
                                </div>
                                <div id="mainTableFreeText" class="text-[9px] text-emerald-400 mt-0.5 font-medium">8 Boş Lisans</div>
                            </td>
                            <td class="p-4 text-center space-x-2 whitespace-nowrap">
                                <button onclick="openDevicePanel('Ahmet Yılmaz (Yılmaz Lojistik)', 10)" class="bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white border border-blue-600/30 px-2.5 py-1 rounded text-[11px] transition inline-flex items-center gap-1">
                                    <i class="fa-solid fa-laptop text-[10px]"></i> Cihazlar
                                </button>
                                <button onclick="this.closest('tr').remove()" class="bg-red-600/20 hover:bg-red-600 text-red-400 hover:text-white border border-red-600/30 px-2.5 py-1 rounded text-[11px] transition">Sil</button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- SAĞDAN AÇILAN CİHAZ DETAY PANELİ -->
    <div id="devicePanel" class="fixed inset-0 z-50 invisible transition-all duration-300">
        <div onclick="closeDevicePanel()" class="absolute inset-0 bg-black/60 backdrop-blur-sm"></div>
        
        <div class="absolute right-0 top-0 bottom-0 w-full max-w-xl bg-[#111a2e] border-l border-slate-800 p-6 shadow-2xl flex flex-col h-full transform translate-x-full transition-transform duration-300" id="panelContainer">
            
            <!-- Panel Başlığı -->
            <div class="flex justify-between items-center border-b border-slate-800 pb-4 mb-4">
                <div>
                    <h3 id="panelClientName" class="text-sm font-bold text-white uppercase tracking-wide">Müşteri Cihazları</h3>
                    <div id="panelQuotaSummary" class="flex gap-2 mt-1.5">
                        <span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[10px] font-semibold">Kullanılan: <span id="usedSpan">0</span></span>
                        <span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded text-[10px] font-semibold">Boş Kota: <span id="freeSpan">0</span></span>
                        <span class="bg-slate-800 text-slate-400 px-2 py-0.5 rounded text-[10px]">Toplam: <span id="totalSpan">0</span></span>
                    </div>
                </div>
                <button onclick="closeDevicePanel()" class="text-slate-400 hover:text-white text-lg p-1">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>

            <!-- + Yeni Cihaz Bilgisi Kaydet -->
            <div class="bg-[#0b111e] border border-slate-800 rounded-lg p-4 mb-4 space-y-4">
                <div class="text-[11px] font-bold text-blue-400 uppercase tracking-wider flex items-center gap-1.5">
                    <i class="fa-solid fa-plus-circle"></i> Yeni Cihaz Bilgisi Kaydet & Lisans Üret
                </div>

                <!-- Lisans Türü Seçimi -->
                <div>
                    <label class="block text-[10px] text-slate-500 mb-1.5 uppercase tracking-wider font-semibold">LİSANS TIPI SEÇİN</label>
                    <div class="grid grid-cols-2 gap-2">
                        <button type="button" onclick="setLicenseType('PC')" id="btnTypePC" class="bg-blue-600 text-white border border-blue-500 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2 shadow-md">
                            <i class="fa-solid fa-desktop text-sm"></i> PC (Bilgisayar)
                        </button>
                        <button type="button" onclick="setLicenseType('USB')" id="btnTypeUSB" class="bg-[#111a2e] text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2">
                            <i class="fa-solid fa-usb text-sm"></i> USB Anahtar
                        </button>
                    </div>
                </div>
                
                <!-- Dinamik Kimlik Girişleri -->
                <div class="grid grid-cols-1 gap-3" id="inputContainer">
                    <div id="macInputGroup">
                        <label class="block text-[10px] text-slate-400 mb-1 uppercase tracking-wide">MAC ID *</label>
                        <input type="text" id="newCpuId" placeholder="Cihazın benzersiz MAC veya Donanım adresi" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 placeholder-slate-600">
                    </div>
                    <div id="usbInputGroup" class="hidden">
                        <label class="block text-[10px] text-slate-400 mb-1 uppercase tracking-wide">USB SERİ NO *</label>
                        <input type="text" id="newUsbId" placeholder="Takılacak USB'nin seri numarası" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 placeholder-slate-600">
                    </div>
                </div>

                <!-- Tarih Girişleri -->
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">BAŞLANGIÇ TARİHİ</label>
                        <input type="date" id="newDeviceStart" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
                    </div>
                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">BİTİŞ TARİHİ</label>
                        <input type="date" id="newDeviceEnd" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
                    </div>
                </div>

                <div class="flex items-center gap-2 bg-[#0b111e] border border-amber-600/30 rounded p-2">
                <input type="checkbox" id="chkAdminMod" class="w-3.5 h-3.5 accent-amber-500">
                <label for="chkAdminMod" class="text-[11px] text-amber-400 font-semibold cursor-pointer">
                    ⭐ Toplu GSM Sorgu Yetkisi (Admin Mod)
                </label>
            </div>
            <button onclick="generateDeviceLicense()" class="w-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold py-2 rounded transition flex items-center justify-center gap-1.5 shadow-md">
                    <i class="fa-solid fa-wand-magic-sparkles"></i> Cihazı Kaydet ve Lisans Oluştur
                </button>
            </div>

            <!-- Kayıtlı Cihazlar Listesi -->
            <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Kayıtlı Cihazlar & Lisans Bilgileri</div>
            <div class="flex-1 overflow-y-auto space-y-2 pr-1" id="panelDeviceList">
                <!-- JavaScript verileri buraya gelecek -->
            </div>
        </div>
    </div>


    <script>
        const todayStr = new Date().toISOString().slice(0,10);
        const nextYear = new Date(Date.now()+365*864e5).toISOString().slice(0,10);
        let activeLicenseType = 'PC';
        let currentCid = null;
        let currentTotal = 10;
        let _licTxt = '', _licId = '';

        // ── AUTH ─────────────────────────────────────────────────────────────
        document.getElementById('pwdInput').onkeydown = e => { if(e.key==='Enter') doLogin(); };
        async function doLogin() {
            const r = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({password: document.getElementById('pwdInput').value})});
            if(r.ok) {
                document.getElementById('loginScreen').style.display = 'none';
                document.getElementById('mainApp').classList.remove('hidden');
                document.getElementById('mainStart').value = todayStr;
                document.getElementById('mainEnd').value = nextYear;
                document.getElementById('newDeviceStart').value = todayStr;
                document.getElementById('newDeviceEnd').value = nextYear;
                loadAll();
            } else {
                document.getElementById('loginErr').classList.remove('hidden');
                document.getElementById('pwdInput').value = '';
            }
        }

        // ── STATS & TABLO ────────────────────────────────────────────────────
        async function loadAll() { await Promise.all([loadStats(), loadTable()]); }

        async function loadStats() {
            const d = await(await fetch('/api/stats')).json();
            document.getElementById('statTotal').textContent = d.total ?? '—';
            document.getElementById('expiredCountCard').textContent = d.expired ?? '—';
            document.getElementById('statWarn').textContent = d.expiring_soon ?? '—';
        }

        async function loadTable() {
            const rows = await(await fetch('/api/customers')).json();
            const tb = document.getElementById('licBody');
            const al = document.getElementById('alertList');
            const ap = document.getElementById('expirationAlertPanel');
            al.innerHTML = ''; let alertCount = 0;

            if(!rows.length) {
                tb.innerHTML = '<tr><td colspan="8" class="p-8 text-center text-slate-500">Henüz kayıt yok</td></tr>';
                ap.classList.add('hidden'); return;
            }
            tb.innerHTML = '';
            rows.forEach(r => {
                const used = r.used, quota = r.quota, free = quota - used;
                const pct = Math.min(100, Math.round((used/quota)*100));
                const days = r.nearest_days;
                if(days <= 10 && r.nearest_end !== 'SINIRSIZ') {
                    alertCount++;
                    const li = document.createElement('li');
                    if(days < 0) li.innerHTML = `<span class="text-red-400 font-bold">${r.name}</span> - Süresi <span class="underline">${Math.abs(days)} gün önce dolmuş!</span> (Bitiş: ${r.nearest_end})`;
                    else if(days === 0) li.innerHTML = `<span class="text-amber-400 font-bold">${r.name}</span> - <span class="font-bold underline">Süresi BUGÜN bitiyor!</span>`;
                    else li.innerHTML = `<span class="text-amber-400 font-bold">${r.name}</span> - Süresinin bitmesine <span class="text-red-400 font-bold underline">${days} gün kaldı!</span> (Bitiş: ${r.nearest_end})`;
                    al.appendChild(li);
                }
                const pcBadge = r.pc_count ? `${r.pc_count} PC` : '';
                const usbBadge = r.usb_count ? `${r.usb_count} USB` : '';
                const deviceText = [pcBadge,usbBadge].filter(Boolean).join(', ') || 'Cihaz Yok';
                const deviceClass = (r.pc_count||r.usb_count) ? "bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[11px] font-medium" : "bg-slate-800 text-slate-500 border border-slate-700/50 px-2 py-0.5 rounded text-[11px]";
                const kalanBadge = r.nearest_end==='SINIRSIZ'
                    ? '<span class="bg-emerald-950/80 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded-full text-[10px]">Sınırsız</span>'
                    : days<0 ? '<span class="bg-red-950/80 text-red-400 border border-red-800/50 px-2 py-0.5 rounded-full text-[10px]">Doldu</span>'
                    : days<=10 ? `<span class="bg-red-950/80 text-red-400 border border-red-800/50 px-2 py-0.5 rounded-full text-[10px] animate-pulse">${days} gün</span>`
                    : days<=30 ? `<span class="bg-amber-950/80 text-amber-400 border border-amber-800/50 px-2 py-0.5 rounded-full text-[10px]">${days} gün</span>`
                    : `<span class="bg-emerald-950/80 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded-full text-[10px]">${days} gün</span>`;

                tb.innerHTML += `<tr class="hover:bg-slate-800/30 transition">
                    <td class="p-4 font-medium text-slate-400">LIC-${String(r.id).padStart(4,'0')}</td>
                    <td class="p-4 font-semibold text-white">${r.name}</td>
                    <td class="p-4"><span class="${deviceClass}">${deviceText}</span></td>
                    <td class="p-4 text-slate-400">${r.nearest_end==='SINIRSIZ'?'—':r.nearest_end.substring(0,10)}</td>
                    <td class="p-4 text-slate-400">${r.nearest_end==='SINIRSIZ'?'Sınırsız':r.nearest_end.substring(0,10)}</td>
                    <td class="p-4">${kalanBadge}</td>
                    <td class="p-4 text-center">
                        <div class="font-bold text-slate-200 text-sm"><span>${used}</span> <span class="text-slate-500 font-normal text-xs">/ ${quota}</span></div>
                        <div class="w-20 bg-slate-800 h-1 rounded overflow-hidden mx-auto mt-1">
                            <div class="bg-blue-500 h-full" style="width:${pct}%"></div>
                        </div>
                        <div class="text-[9px] text-emerald-400 mt-0.5 font-medium">${Math.max(0,free)} Boş Lisans</div>
                    </td>
                    <td class="p-4 text-center space-x-2 whitespace-nowrap">
                        <button onclick="openDevicePanel('${r.name.replace(/[^a-zA-Z0-9 ]/g,"")}', ${r.quota}, ${r.id})" class="bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white border border-blue-600/30 px-2.5 py-1 rounded text-[11px] transition inline-flex items-center gap-1">
                            <i class="fa-solid fa-laptop text-[10px]"></i> Cihazlar
                        </button>
                        <button onclick="deleteCustomer(${r.id})" class="bg-red-600/20 hover:bg-red-600 text-red-400 hover:text-white border border-red-600/30 px-2.5 py-1 rounded text-[11px] transition">Sil</button>
                    </td>
                </tr>`;
            });
            if(alertCount>0) ap.classList.remove('hidden');
            else ap.classList.add('hidden');
        }

        // ── ANA FORM ─────────────────────────────────────────────────────────
        async function getMachineId() {
            const d = await(await fetch('/api/machine_id')).json();
            document.getElementById('fMid') && (document.getElementById('fMid').value = d.machine_id);
            document.getElementById('newCpuId') && (document.getElementById('newCpuId').value = d.machine_id);
        }

        async function createMainLicense() {
            const mid = document.getElementById('fMid').value.trim();
            const usb = document.getElementById('fUsb').value.trim();
            const name = document.getElementById('fName').value.trim();
            const quota = parseInt(document.getElementById('fQuota').value)||10;
            const start = document.getElementById('mainStart').value;
            const end = document.getElementById('mainEnd').value;
            if(!mid||!name){alert('MAC ID ve Müşteri Adı zorunludur!');return;}
            const cr = await fetch('/api/customers',{method:'POST',headers:{'Content-Type':'application/json'},
                body:JSON.stringify({name,quota})});
            const cd = await cr.json();
            if(!cr.ok){alert(cd.error||'Hata');return;}
            const lr = await fetch(`/api/customers/${cd.customer_id}/licenses`,{method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({machine_id:mid,usb_serial:usb,start_date:start,end_date:end})});
            const ld = await lr.json();
            if(!lr.ok){alert(ld.error||'Hata');return;}
            _licTxt=ld.license_file;_licId=ld.license_id;
            document.getElementById('licContent').textContent=ld.license_file;
            document.getElementById('licModal').style.display='flex';
            document.getElementById('fMid').value='';document.getElementById('fUsb').value='';document.getElementById('fName').value='';
            loadAll();
        }

        async function deleteCustomer(id) {
            if(!confirm('Bu müşteriyi ve tüm lisanslarını silmek istiyor musunuz?'))return;
            await fetch(`/api/customers/${id}`,{method:'DELETE'});
            loadAll();
        }

        // ── CİHAZ PANELİ ─────────────────────────────────────────────────────
        async function openDevicePanel(clientName, total, cid) {
            currentCid = cid; currentTotal = total;
            document.getElementById('panelClientName').innerText = clientName;
            setLicenseType('PC');
            document.getElementById('newDeviceStart').value = todayStr;
            document.getElementById('newDeviceEnd').value = nextYear;
            document.getElementById('newCpuId').value = '';
            document.getElementById('newUsbId').value = '';
            await renderDevices();
            const panel = document.getElementById('devicePanel');
            const container = document.getElementById('panelContainer');
            panel.classList.remove('invisible');
            setTimeout(() => { container.classList.remove('translate-x-full'); }, 50);
        }

        async function renderDevices() {
            if(!currentCid)return;
            const d = await(await fetch(`/api/customers/${currentCid}/licenses`)).json();
            const lics = d.licenses||[];
            const used=lics.length, free=currentTotal-used;
            document.getElementById('usedSpan').innerText = used;
            document.getElementById('totalSpan').innerText = currentTotal;
            document.getElementById('freeSpan').innerText = Math.max(0,free);

            // Ana tablo sayaçları
            let pcCount=0,usbCount=0;
            lics.forEach(l=>{if(l.usb_serial)usbCount++;else pcCount++;});
            
            const list = document.getElementById('panelDeviceList');
            list.innerHTML = '';
            if(!lics.length){list.innerHTML='<div class="text-xs text-slate-500 text-center py-4">Kayıtlı cihaz yok</div>';return;}

            lics.forEach(dev => {
                const days = dev.days;
                let badgeClass = "bg-emerald-950/80 text-emerald-400 border border-emerald-800/50";
                let remainingText = days>=99999?'Sınırsız':`${days} gün kaldı`;
                if(days<=0){badgeClass="bg-red-950/80 text-red-400 border border-red-800/50";remainingText="Süresi Doldu";}
                else if(days<=10){badgeClass="bg-amber-950/80 text-amber-400 border border-amber-800/50 animate-pulse";}

                const card = document.createElement('div');
                card.className = "bg-[#0b111e] border border-slate-800 rounded p-3 space-y-3";
                card.innerHTML = `
                    <div class="flex justify-between items-start">
                        <div class="space-y-1 text-[11px]">
                            <div><span class="text-slate-400">Tür:</span> <span class="text-blue-400 font-bold">${dev.usb_serial?'USB':'PC'}</span> <span class="font-mono text-slate-500 text-[10px] ml-2">${dev.license_id}</span></div>
                            <div><span class="text-slate-400">Başlangıç:</span> <span class="text-slate-200 font-medium">${dev.start_date}</span></div>
                            <div><span class="text-slate-400">Bitiş:</span> <span id="displayEnd-${dev.id}" class="text-slate-200 font-medium">${dev.end_date==='SINIRSIZ'?'Sınırsız':dev.end_date}</span></div>
                            <div class="pt-0.5"><span id="badge-${dev.id}" class="${badgeClass} px-1.5 py-0.5 rounded text-[10px] font-semibold">${remainingText}</span></div>
                        </div>
                        <button onclick="removeDevice(${dev.id})" class="text-red-400 hover:text-red-300 text-xs p-1"><i class="fa-solid fa-trash-can"></i></button>
                    </div>
                    <div class="bg-[#121b2d] border border-slate-800/80 rounded p-2 flex items-center justify-between gap-2">
                        <div class="flex flex-col flex-1">
                            <span class="text-[9px] text-slate-500 font-semibold uppercase tracking-wider mb-0.5">Süreyi Uzat (Yeni Bitiş)</span>
                            <input type="date" id="extendDate-${dev.id}" value="${dev.end_date==='SINIRSIZ'?nextYear:dev.end_date}"
                                class="bg-[#0b111e] border border-slate-800 text-slate-200 px-2 py-1 text-[11px] rounded focus:outline-none focus:border-blue-500 w-full">
                        </div>
                        <button onclick="updateDeviceDuration(${dev.id})" class="bg-emerald-600 hover:bg-emerald-500 text-white p-2 rounded transition shadow mt-3 shrink-0" title="Süreyi Güncelle ve Kaydet">
                            <i class="fa-solid fa-check text-xs"></i>
                        </button>
                    </div>
                    <div class="bg-[#121b2d] border border-slate-800 rounded px-2.5 py-2 flex items-center justify-between gap-2">
                        <div class="font-mono text-[11px] text-slate-400 overflow-hidden text-ellipsis whitespace-nowrap">${dev.license_id}</div>
                        <button onclick="showLicById(${dev.id})"
                            class="bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white px-2 py-1 rounded text-[10px] border border-blue-600/30 transition shrink-0 flex items-center gap-1">
                            <i class="fa-solid fa-file-arrow-down"></i> Lisans İndir
                        </button>
                    </div>`;
                list.appendChild(card);
            });
        }

        function closeDevicePanel() {
            const panel=document.getElementById('devicePanel');
            const container=document.getElementById('panelContainer');
            container.classList.add('translate-x-full');
            setTimeout(()=>{panel.classList.add('invisible');},300);
            loadAll();
        }

        function setLicenseType(type) {
            activeLicenseType=type;
            const btnPC=document.getElementById('btnTypePC');
            const btnUSB=document.getElementById('btnTypeUSB');
            const usbGroup=document.getElementById('usbInputGroup');
            const inputContainer=document.getElementById('inputContainer');
            if(type==='PC'){
                btnPC.className="bg-blue-600 text-white border border-blue-500 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2 shadow-md";
                btnUSB.className="bg-[#111a2e] text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2";
                inputContainer.className="grid grid-cols-1 gap-3";
                usbGroup.classList.add('hidden');
                document.getElementById('newUsbId').value='';
            } else {
                btnUSB.className="bg-blue-600 text-white border border-blue-500 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2 shadow-md";
                btnPC.className="bg-[#111a2e] text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2";
                inputContainer.className="grid grid-cols-1 sm:grid-cols-2 gap-3";
                usbGroup.classList.remove('hidden');
            }
        }

        async function generateDeviceLicense() {
            if(!currentCid)return;
            const macId=document.getElementById('newCpuId').value.trim();
            const usbId=document.getElementById('newUsbId').value.trim();
            const start=document.getElementById('newDeviceStart').value;
            const end=document.getElementById('newDeviceEnd').value;
            if(!macId){alert('Lütfen MAC ID alanını doldurunuz!');return;}
            if(activeLicenseType==='USB'&&!usbId){alert('USB SERİ NO alanı boş bırakılamaz!');return;}
            const r=await fetch(`/api/customers/${currentCid}/licenses`,{method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({machine_id:macId,usb_serial:activeLicenseType==='USB'?usbId:'',start_date:start,end_date:end,admin_mod:document.getElementById('chkAdminMod').checked})});
            const d=await r.json();
            if(!r.ok){alert(d.error||'Hata');return;}
            _licTxt=d.license_file;_licId=d.license_id;
            document.getElementById('licContent').textContent=d.license_file;
            document.getElementById('licModal').style.display='flex';
            document.getElementById('newCpuId').value='';document.getElementById('newUsbId').value='';
            await renderDevices();loadAll();
        }

        async function updateDeviceDuration(id) {
            const newDateVal=document.getElementById(`extendDate-${id}`).value;
            if(!newDateVal){alert('Lütfen geçerli bir tarih seçiniz!');return;}
            const r=await fetch(`/api/licenses/${id}/extend`,{method:'POST',
                headers:{'Content-Type':'application/json'},body:JSON.stringify({end_date:newDateVal})});
            const d=await r.json();
            if(!r.ok){alert('Hata: '+(d.error||''));return;}
            _licTxt=d.license_file;
            document.getElementById('licContent').textContent=d.license_file;
            document.getElementById('licModal').style.display='flex';
            await renderDevices();
        }

        async function removeDevice(id) {
            if(!confirm('Bu cihaz lisansını silmek istiyor musunuz?'))return;
            await fetch(`/api/licenses/${id}`,{method:'DELETE'});
            await renderDevices();loadAll();
        }

        function showLic(file,id){_licTxt=file;_licId=id;document.getElementById('licContent').textContent=file;document.getElementById('licModal').style.display='flex';}
        async function showLicById(licId){
            const d=await(await fetch(`/api/customers/${currentCid}/licenses`)).json();
            const lic=d.licenses.find(l=>l.id===licId);
            if(!lic)return;
            showLic(lic.license_file,lic.license_id);
        }
        function copyLic(){navigator.clipboard.writeText(_licTxt).then(()=>alert('Kopyalandı!'));}
        function downloadLic(){const a=document.createElement('a');a.href='data:text/plain;charset=utf-8,'+encodeURIComponent(_licTxt);a.download='license.lic';a.click();}
        function closeLicModal(){document.getElementById('licModal').style.display='none';}

        // Mockup'taki statik fonksiyonlar API'ye bağlandı — sayfa ilk yüklendiğinde çalışmaz
        // renderDevices() → API'den çağrılır
    </script>

</div>
</body>
</html>
"""

if __name__=="__main__":
    if not _CRYPTO:
        print("cryptography paketi gerekli: pip install cryptography")
        import sys; sys.exit(1)
    # Eski instance'ı kapat
    import subprocess, time
    try:
        out = subprocess.check_output('netstat -ano | findstr ":5002 "',
            shell=True, stderr=subprocess.DEVNULL, timeout=5,
            creationflags=0x08000000).decode(errors='ignore')
        for line in out.splitlines():
            if ':5002' in line and 'LISTENING' in line:
                pid = line.strip().split()[-1]
                subprocess.run(f'taskkill /PID {pid} /T /F', shell=True,
                    capture_output=True, creationflags=0x08000000)
                time.sleep(1); break
    except: pass
    init_db()
    print(f"\n  ⚙️  Admin Paneli → http://localhost:5002")
    print(f"  Şifre: 14531453\n")
    threading.Timer(1.5,lambda:webbrowser.open("http://localhost:5002")).start()
    app.run(host="127.0.0.1",port=5002,debug=False,threaded=True,use_reloader=False)
