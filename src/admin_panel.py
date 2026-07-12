"""Sorgu Sistemi — Admin Lisans Paneli v2.0"""
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
app.secret_key="admin_panel_secret_2024_xK9"
app.config['JSON_SORT_KEYS']=False

# ── VERİTABANI ───────────────────────────────────────────────────────────────
def init_db():
    conn=sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,branch TEXT NOT NULL,
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

# ── AUTH ─────────────────────────────────────────────────────────────────────
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

# ── STATS ─────────────────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();cur=conn.cursor();today=datetime.date.today().isoformat()
    cur.execute("SELECT COUNT(*) FROM customers WHERE active=1")
    total=cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM licenses WHERE active=1 AND end_date<? AND end_date!='SINIRSIZ'",[today])
    expired=cur.fetchone()[0]
    d30=(datetime.date.today()+datetime.timedelta(30)).isoformat()
    cur.execute("SELECT COUNT(*) FROM licenses WHERE active=1 AND end_date>=? AND end_date<=? AND end_date!='SINIRSIZ'",[today,d30])
    expiring=cur.fetchone()[0]
    conn.close()
    return jsonify({"total":total,"expired":expired,"expiring_soon":expiring})

# ── MÜŞTERİLER ───────────────────────────────────────────────────────────────
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
        # Uyarılar için en yakın bitiş tarihi
        dates=[l["end_date"] for l in lics if l["end_date"]!="SINIRSIZ"]
        if dates:
            nearest=min(dates)
            c["nearest_end"]=nearest
            try:
                d=(datetime.date.fromisoformat(nearest)-today).days
                c["nearest_days"]=d
            except:c["nearest_days"]=999
        else:c["nearest_end"]="SINIRSIZ";c["nearest_days"]=9999
    conn.close()
    return jsonify(custs)

@app.route("/api/customers",methods=["POST"])
def api_create_customer():
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    d=request.get_json(force=True) or {}
    if not d.get("name") or not d.get("branch"):
        return jsonify({"error":"Ad ve şube zorunludur"}),400
    conn=db()
    conn.execute("INSERT INTO customers(name,branch,quota,notes,created_at) VALUES(?,?,?,?,?)",
        [d["name"].strip(),d["branch"].strip(),int(d.get("quota",10)),
         d.get("notes",""),datetime.datetime.now().isoformat()])
    conn.commit();conn.close()
    return jsonify({"ok":True})

@app.route("/api/customers/<int:cid>",methods=["DELETE"])
def api_delete_customer(cid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db()
    conn.execute("UPDATE customers SET active=0 WHERE id=?",[cid])
    conn.execute("UPDATE licenses SET active=0 WHERE customer_id=?",[cid])
    conn.commit();conn.close()
    return jsonify({"ok":True})

# ── LİSANSLAR (cihazlar) ─────────────────────────────────────────────────────
@app.route("/api/customers/<int:cid>/licenses")
def api_cust_licenses(cid):
    if not session.get("admin"):return jsonify({"error":"Yetkisiz"}),401
    conn=db();cur=conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id=?",[cid])
    cust=dict(cur.fetchone())
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
    cur.execute("SELECT * FROM customers WHERE id=?",[cid])
    cust=dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) FROM licenses WHERE customer_id=? AND active=1",[cid])
    used=cur.fetchone()[0]
    if used>=cust["quota"]:
        conn.close();return jsonify({"error":f"Kota dolu! ({used}/{cust['quota']})"}),400

    machine_id=d.get("machine_id","").strip()
    usb_serial=d.get("usb_serial","").strip()
    start_date=d.get("start_date",datetime.date.today().isoformat())
    end_date=d.get("end_date","")
    if not machine_id:conn.close();return jsonify({"error":"Makine ID zorunludur"}),400
    if usb_serial and not machine_id:conn.close();return jsonify({"error":"USB için de Makine ID gereklidir"}),400

    # Bitiş tarihi kontrolü
    if not end_date:end_date="SINIRSIZ"
    try:
        if end_date!="SINIRSIZ":
            s=datetime.date.fromisoformat(start_date)
            e=datetime.date.fromisoformat(end_date)
            days=(e-s).days
        else:days=None
    except:days=None;end_date="SINIRSIZ"

    plan="YILLIK" if (days and 300<=days<=400) else "AYLIK" if (days and days<=35) else "SINIRSIZ" if not days else "OZEL"
    lic_id=next_lic_id()
    lic_bytes=create_license(
        machine_id=machine_id,plan=plan,days=days,
        branch=cust["branch"],issued_to=cust["name"],
        license_id=lic_id,usb_serial=usb_serial)

    conn.execute("""INSERT INTO licenses(license_id,customer_id,machine_id,usb_serial,
        plan,start_date,end_date,license_file,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        [lic_id,cid,machine_id,usb_serial,plan,start_date,end_date,
         lic_bytes.decode("ascii"),datetime.datetime.now().isoformat()])
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
        s=datetime.date.fromisoformat(row["start_date"])
        e=datetime.date.fromisoformat(new_end)
        days=(e-s).days if new_end!="SINIRSIZ" else None
    except:days=None;new_end="SINIRSIZ"
    plan="YILLIK" if (days and 300<=days<=400) else "AYLIK" if (days and days<=35) else "SINIRSIZ" if not days else "OZEL"
    lic_bytes=create_license(
        machine_id=row["machine_id"],plan=plan,days=days,
        branch=row["branch"],issued_to=row["name"],
        license_id=row["license_id"],usb_serial=row["usb_serial"])
    conn.execute("UPDATE licenses SET end_date=?,plan=?,license_file=? WHERE id=?",
        [new_end,plan,lic_bytes.decode("ascii"),lid])
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


ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lisans Yönetim Paneli</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
color-scheme:dark;
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:#0b111e}
::-webkit-scrollbar-thumb{background:#1e293b;border-radius:4px}
#panelContainer{transition:transform .3s cubic-bezier(.4,0,.2,1)}
#devicePanel{transition:visibility 0s .3s}
#devicePanel.open{transition:visibility 0s;visibility:visible!important}
#devicePanel.open #panelContainer{transform:translateX(0)!important}
</style>
</head>
<body class="bg-[#0b111e] text-slate-200 font-sans min-h-screen overflow-x-hidden relative">

<!-- GİRİŞ -->
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

<!-- ANA PANEL -->
<div id="mainApp" class="hidden">

<div class="bg-[#0d1526] border-b border-slate-800 px-6 py-3 flex items-center justify-between sticky top-0 z-40">
  <div class="flex items-center gap-3">
    <span class="text-lg">⚙️</span>
    <div><div class="text-sm font-bold text-white">Lisans Yönetim Paneli</div>
    <div class="text-[10px] text-slate-500">Sorgu Sistemi v4.0</div></div>
  </div>
  <button onclick="doLogout()" class="text-xs text-slate-400 hover:text-red-400 border border-slate-700 hover:border-red-800 px-3 py-1.5 rounded transition">Çıkış</button>
</div>

<div class="p-4 md:p-6 space-y-6 max-w-screen-2xl mx-auto">

  <!-- UYARI PANELİ -->
  <div id="expirationAlertPanel" class="bg-red-950/40 border border-red-900/60 rounded-xl p-4 hidden">
    <div class="flex items-start gap-3">
      <i class="fa-solid fa-triangle-exclamation text-red-500 text-lg mt-0.5 shrink-0 animate-pulse"></i>
      <div class="flex-1">
        <h4 class="text-xs font-bold text-red-400 uppercase tracking-wider mb-2">Kritik Süre Uyarı Merkezi (Son 10 Gün)</h4>
        <ul id="alertList" class="text-xs text-slate-300 space-y-1 list-disc list-inside"></ul>
      </div>
    </div>
  </div>

  <!-- İSTATİSTİKLER -->
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6">
    <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
      <div id="statTotal" class="text-3xl font-bold text-blue-500 mb-1">—</div>
      <div class="text-xs text-slate-400 uppercase tracking-wider">Toplam Müşteri</div>
    </div>
    <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
      <div id="statExp" class="text-3xl font-bold text-red-500 mb-1">—</div>
      <div class="text-xs text-slate-400 uppercase tracking-wider">Süresi Dolmuş Lisans</div>
    </div>
    <div class="bg-[#111a2e] border border-slate-800/80 rounded-lg p-6 text-center shadow-lg">
      <div id="statWarn" class="text-3xl font-bold text-amber-500 mb-1">—</div>
      <div class="text-xs text-slate-400 uppercase tracking-wider">30 Gün İçinde Bitecek</div>
    </div>
  </div>

  <!-- YENİ MÜŞTERİ FORMU -->
  <div class="bg-[#111a2e] border border-slate-800/80 rounded-xl p-6 shadow-xl">
    <div class="flex justify-between items-center mb-5 flex-wrap gap-2">
      <h2 class="text-sm font-semibold text-white flex items-center gap-2">
        <span class="text-blue-500 text-lg">+</span> Yeni Müşteri Ekle
      </h2>
      <button onclick="fillMyMid()" class="bg-[#1a263e] hover:bg-slate-700 text-xs text-slate-300 px-4 py-2 rounded border border-slate-700 transition">Bu Bilgisayarın Makine ID'sini Al</button>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div>
        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">Müşteri / Kullanıcı Adı *</label>
        <input id="fName" type="text" placeholder="Ad Soyad veya Kurum" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
      </div>
      <div>
        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">Şube *</label>
        <input id="fBranch" type="text" placeholder="ANKARA, İSTANBUL..." class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
      </div>
      <div>
        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">Toplam Lisans Kotası (Adet) *</label>
        <input id="fQuota" type="number" min="1" value="10" class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300">
      </div>
      <div>
        <label class="block text-[11px] font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">Notlar</label>
        <input id="fNotes" type="text" placeholder="İsteğe bağlı..." class="w-full bg-[#0b111e] border border-slate-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-slate-300 placeholder-slate-600">
      </div>
    </div>
    <div id="custMsg" class="mt-4 hidden"></div>
    <div class="pt-4">
      <button onclick="createCustomer()" class="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-5 py-2.5 rounded shadow-lg transition flex items-center gap-2">
        <i class="fa-solid fa-user-plus text-[11px]"></i> Müşteri Ekle
      </button>
    </div>
  </div>

  <!-- MÜŞTERİ TABLOSU -->
  <div class="bg-[#111a2e] border border-slate-800/80 rounded-xl shadow-xl overflow-hidden">
    <div class="p-4 border-b border-slate-800 flex justify-between items-center bg-[#131d33]">
      <h3 class="text-sm font-semibold text-white">📄 Tüm Müşteriler</h3>
      <button onclick="loadAll()" class="text-xs text-slate-400 hover:text-white flex items-center gap-1 bg-[#0b111e] px-3 py-1.5 rounded border border-slate-800 transition">
        <i class="fa-solid fa-rotate-right text-[10px]"></i> Yenile
      </button>
    </div>
    <div class="overflow-x-auto w-full">
      <table class="w-full text-left border-collapse min-w-[900px]">
        <thead>
          <tr class="border-b border-slate-800 text-[11px] text-slate-400 uppercase tracking-wider bg-[#0f172a]">
            <th class="p-4 font-semibold">ID</th>
            <th class="p-4 font-semibold">Müşteri Adı</th>
            <th class="p-4 font-semibold">Şube</th>
            <th class="p-4 font-semibold">PC / USB</th>
            <th class="p-4 font-semibold">En Yakın Bitiş</th>
            <th class="p-4 font-semibold">Kalan Süre</th>
            <th class="p-4 font-semibold text-center">Kullanılan / Kota</th>
            <th class="p-4 font-semibold text-center">İşlem</th>
          </tr>
        </thead>
        <tbody id="custBody" class="text-xs text-slate-300 divide-y divide-slate-800/50">
          <tr><td colspan="8" class="p-8 text-center text-slate-500">Yükleniyor...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
</div>

<!-- SAĞDAN AÇILAN CİHAZ DETAY PANELİ -->
<div id="devicePanel" class="fixed inset-0 z-50 invisible" onclick="if(event.target.id==='devicePanel')closePanel()">
  <div class="absolute inset-0 bg-black/60 backdrop-blur-sm"></div>
  <div id="panelContainer" class="absolute right-0 top-0 bottom-0 w-full max-w-xl bg-[#111a2e] border-l border-slate-800 flex flex-col h-full transform translate-x-full shadow-2xl">

    <!-- Panel Header -->
    <div class="flex justify-between items-center border-b border-slate-800 px-6 py-4 shrink-0">
      <div>
        <h3 id="panelClientName" class="text-sm font-bold text-white uppercase tracking-wide">Müşteri Cihazları</h3>
        <div id="panelQuotaSummary" class="flex gap-2 mt-1.5 flex-wrap">
          <span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[10px] font-semibold">Kullanılan: <span id="usedSpan">0</span></span>
          <span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded text-[10px] font-semibold">Boş Kota: <span id="freeSpan">0</span></span>
          <span class="bg-slate-800 text-slate-400 px-2 py-0.5 rounded text-[10px]">Toplam: <span id="totalSpan">0</span></span>
        </div>
      </div>
      <button onclick="closePanel()" class="text-slate-400 hover:text-white text-xl p-1"><i class="fa-solid fa-xmark"></i></button>
    </div>

    <!-- Yeni Cihaz Formu -->
    <div class="px-6 py-4 border-b border-slate-800 shrink-0 bg-[#0d1526]">
      <div class="bg-[#0b111e] border border-slate-800 rounded-lg p-4 space-y-4">
        <div class="text-[11px] font-bold text-blue-400 uppercase tracking-wider flex items-center gap-1.5">
          <i class="fa-solid fa-plus-circle"></i> Yeni Cihaz Bilgisi Kaydet &amp; Lisans Üret
        </div>
        <!-- Tip Seçimi -->
        <div>
          <label class="block text-[10px] text-slate-500 mb-1.5 uppercase tracking-wider font-semibold">Lisans Tipi Seçin</label>
          <div class="grid grid-cols-2 gap-2">
            <button type="button" id="btnTypePC" onclick="setType('PC')" class="bg-blue-600 text-white border border-blue-500 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2 shadow-md">
              <i class="fa-solid fa-desktop text-sm"></i> PC (Bilgisayar)
            </button>
            <button type="button" id="btnTypeUSB" onclick="setType('USB')" class="bg-[#111a2e] text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2">
              <i class="fa-solid fa-usb text-sm"></i> USB Anahtar
            </button>
          </div>
        </div>
        <!-- Kimlik -->
        <div id="inputContainer" class="grid grid-cols-1 gap-3">
          <div>
            <label class="block text-[10px] text-slate-400 mb-1 uppercase tracking-wide">Makine ID *</label>
            <input type="text" id="newMid" placeholder="Cihazın benzersiz donanım kimliği" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 placeholder-slate-600 font-mono">
          </div>
          <div id="usbInputGroup" class="hidden">
            <label class="block text-[10px] text-slate-400 mb-1 uppercase tracking-wide">USB Seri No *</label>
            <input type="text" id="newUsb" placeholder="Takılacak USB'nin seri numarası" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500 placeholder-slate-600">
          </div>
        </div>
        <!-- Tarihler -->
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block text-[10px] text-slate-400 mb-1">Başlangıç Tarihi</label>
            <input type="date" id="newStart" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
          </div>
          <div>
            <label class="block text-[10px] text-slate-400 mb-1">Bitiş Tarihi</label>
            <input type="date" id="newEnd" class="w-full bg-[#111a2e] border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-blue-500">
          </div>
        </div>
        <div id="devMsg" class="hidden text-xs text-red-400"></div>
        <button onclick="createDevice()" class="w-full bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold py-2 rounded transition flex items-center justify-center gap-1.5 shadow-md">
          <i class="fa-solid fa-wand-magic-sparkles"></i> Cihazı Kaydet ve Lisans Oluştur
        </button>
      </div>
    </div>

    <!-- Kayıtlı Cihazlar -->
    <div class="flex-1 overflow-y-auto p-4 space-y-2">
      <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Kayıtlı Cihazlar &amp; Lisans Bilgileri</div>
      <div id="panelDeviceList" class="space-y-2"></div>
    </div>
  </div>
</div>

<!-- LİSANS MODAL -->
<div id="licModal" class="fixed inset-0 z-[60] hidden items-center justify-center flex">
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

<script>
const today=new Date().toISOString().slice(0,10);
const nextYear=new Date(Date.now()+365*864e5).toISOString().slice(0,10);
let _licTxt='',_licId='',_curCid=null,_curCust={},_licType='PC';

// ── AUTH ─────────────────────────────────────────────────────────────────────
async function doLogin(){
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({password:document.getElementById('pwdInput').value})});
  if(r.ok){
    document.getElementById('loginScreen').style.display='none';
    document.getElementById('mainApp').classList.remove('hidden');
    loadAll();
  } else {
    document.getElementById('loginErr').classList.remove('hidden');
    document.getElementById('pwdInput').value='';
  }
}
document.getElementById('pwdInput').onkeydown=e=>{if(e.key==='Enter')doLogin()};
async function doLogout(){await fetch('/api/logout',{method:'POST'});location.reload();}

// ── STATS & LIST ─────────────────────────────────────────────────────────────
async function loadAll(){loadStats();loadCustomers();}

async function loadStats(){
  const d=await(await fetch('/api/stats')).json();
  document.getElementById('statTotal').textContent=d.total??'—';
  document.getElementById('statExp').textContent=d.expired??'—';
  document.getElementById('statWarn').textContent=d.expiring_soon??'—';
}

async function loadCustomers(){
  const rows=await(await fetch('/api/customers')).json();
  const tb=document.getElementById('custBody');
  const al=document.getElementById('alertList');
  const ap=document.getElementById('expirationAlertPanel');
  al.innerHTML=''; let alertCount=0;
  if(!rows.length){
    tb.innerHTML='<tr><td colspan="8" class="p-8 text-center text-slate-500">Henüz müşteri yok</td></tr>';
    ap.classList.add('hidden');return;
  }
  tb.innerHTML='';
  rows.forEach(r=>{
    const used=r.used,quota=r.quota,free=quota-used;
    const pct=Math.round((used/quota)*100);
    const days=r.nearest_days;
    const kalanHtml=r.nearest_end==='SINIRSIZ'
      ?'<span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded-full text-[10px]">∞ Sınırsız</span>'
      :days<0?'<span class="bg-red-950/80 text-red-400 border border-red-800/50 px-2 py-0.5 rounded-full text-[10px]">Doldu</span>'
      :days<=10?`<span class="bg-red-950/80 text-red-400 border border-red-800/50 px-2 py-0.5 rounded-full text-[10px] animate-pulse">${days} gün</span>`
      :days<=30?`<span class="bg-amber-950/80 text-amber-400 border border-amber-800/50 px-2 py-0.5 rounded-full text-[10px]">${days} gün</span>`
      :`<span class="bg-emerald-950/80 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded-full text-[10px]">${days} gün</span>`;

    if(days<=10&&r.nearest_end!=='SINIRSIZ'){
      alertCount++;
      al.innerHTML+=`<li><span class="text-amber-400 font-bold">${r.name}</span> — <span class="text-red-400 font-bold">${days<0?Math.abs(days)+' gün önce doldu':days===0?'Bugün bitiyor':days+' gün kaldı'}</span> (${r.nearest_end})</li>`;
    }

    const pcBadge=r.pc_count?`<span class="bg-blue-500/10 text-blue-400 border border-blue-500/20 px-2 py-0.5 rounded text-[10px] font-medium">${r.pc_count} PC</span>`:'';
    const usbBadge=r.usb_count?`<span class="bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded text-[10px] font-medium">${r.usb_count} USB</span>`:'';
    const noBadge=!r.pc_count&&!r.usb_count?'<span class="text-slate-600 text-[10px]">Cihaz Yok</span>':'';

    tb.innerHTML+=`<tr class="hover:bg-slate-800/30 transition">
      <td class="p-4 font-medium text-slate-400 font-mono">MUS-${String(r.id).padStart(4,'0')}</td>
      <td class="p-4 font-semibold text-white">${r.name}</td>
      <td class="p-4 text-slate-400">${r.branch}</td>
      <td class="p-4"><div class="flex gap-1 flex-wrap">${pcBadge}${usbBadge}${noBadge}</div></td>
      <td class="p-4 text-slate-400">${r.nearest_end==='SINIRSIZ'?'—':r.nearest_end}</td>
      <td class="p-4">${kalanHtml}</td>
      <td class="p-4 text-center">
        <div class="font-bold text-slate-200 text-sm">${used} <span class="text-slate-500 font-normal text-xs">/ ${quota}</span></div>
        <div class="w-20 bg-slate-800 h-1 rounded overflow-hidden mx-auto mt-1">
          <div class="bg-blue-500 h-full transition-all" style="width:${pct}%"></div>
        </div>
        <div class="text-[9px] text-emerald-400 mt-0.5 font-medium">${free} Boş Lisans</div>
      </td>
      <td class="p-4 text-center space-x-2 whitespace-nowrap">
        <button onclick="openPanel(${r.id})" class="bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white border border-blue-600/30 px-2.5 py-1 rounded text-[11px] transition inline-flex items-center gap-1">
          <i class="fa-solid fa-laptop text-[10px]"></i> Cihazlar
        </button>
        <button onclick="deleteCustomer(${r.id})" class="bg-red-600/20 hover:bg-red-600 text-red-400 hover:text-white border border-red-600/30 px-2.5 py-1 rounded text-[11px] transition">Sil</button>
      </td>
    </tr>`;
  });
  if(alertCount>0)ap.classList.remove('hidden');
  else ap.classList.add('hidden');
}

// ── MÜŞTERİ İŞLEMLERİ ───────────────────────────────────────────────────────
async function fillMyMid(){
  const d=await(await fetch('/api/machine_id')).json();
  // Panel açıksa oraya doldur
  if(_curCid){document.getElementById('newMid').value=d.machine_id;}
}

async function createCustomer(){
  const body={name:document.getElementById('fName').value.trim(),
    branch:document.getElementById('fBranch').value.trim(),
    quota:parseInt(document.getElementById('fQuota').value)||10,
    notes:document.getElementById('fNotes').value.trim()};
  if(!body.name||!body.branch){showMsg('custMsg','Müşteri adı ve şube zorunludur','red');return;}
  const r=await fetch('/api/customers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok){showMsg('custMsg',d.error||'Hata','red');return;}
  showMsg('custMsg','✅ Müşteri eklendi','green');
  document.getElementById('fName').value='';document.getElementById('fBranch').value='';
  loadAll();
}

async function deleteCustomer(id){
  if(!confirm('Bu müşteriyi ve tüm lisanslarını silmek istiyor musunuz?'))return;
  await fetch(`/api/customers/${id}`,{method:'DELETE'});
  loadAll();
}

// ── CİHAZ PANELİ ─────────────────────────────────────────────────────────────
async function openPanel(cid){
  _curCid=cid;
  document.getElementById('newStart').value=today;
  document.getElementById('newEnd').value=nextYear;
  document.getElementById('newMid').value='';
  document.getElementById('newUsb').value='';
  setType('PC');
  await loadDevices();
  document.getElementById('devicePanel').classList.add('open');
  document.getElementById('devicePanel').style.visibility='visible';
}

async function loadDevices(){
  const d=await(await fetch(`/api/customers/${_curCid}/licenses`)).json();
  _curCust=d.customer;
  const lics=d.licenses||[];
  document.getElementById('panelClientName').textContent=_curCust.name;
  const quota=_curCust.quota,used=lics.length,free=quota-used;
  document.getElementById('usedSpan').textContent=used;
  document.getElementById('freeSpan').textContent=Math.max(0,free);
  document.getElementById('totalSpan').textContent=quota;
  const list=document.getElementById('panelDeviceList');
  list.innerHTML='';
  if(!lics.length){list.innerHTML='<div class="text-xs text-slate-500 text-center py-4">Kayıtlı cihaz yok</div>';return;}
  lics.forEach(l=>{
    const days=l.days,isUsb=!!l.usb_serial;
    let badgeCls='bg-emerald-950/80 text-emerald-400 border-emerald-800/50';
    let badgeTxt=days>=99999?'Sınırsız':days+' gün kaldı';
    if(days<0){badgeCls='bg-red-950/80 text-red-400 border-red-800/50';badgeTxt='Süresi Doldu';}
    else if(days<=10){badgeCls='bg-amber-950/80 text-amber-400 border-amber-800/50 animate-pulse';}
    const div=document.createElement('div');
    div.className='bg-[#0b111e] border border-slate-800 rounded p-3 space-y-3';
    div.innerHTML=`
      <div class="flex justify-between items-start">
        <div class="space-y-1 text-[11px]">
          <div class="flex items-center gap-2">
            <span class="${isUsb?'bg-purple-500/10 text-purple-400 border-purple-500/20':'bg-blue-500/10 text-blue-400 border-blue-500/20'} border px-1.5 py-0.5 rounded text-[10px] font-bold">${isUsb?'USB':'PC'}</span>
            <span class="font-mono text-slate-400 text-[10px]">${l.license_id}</span>
          </div>
          <div><span class="text-slate-500">Makine ID:</span> <span class="font-mono text-[10px] text-slate-300">${l.machine_id.substring(0,16)}...</span></div>
          ${isUsb?`<div><span class="text-slate-500">USB Seri:</span> <span class="text-slate-300">${l.usb_serial}</span></div>`:''}
          <div><span class="text-slate-500">Başlangıç:</span> <span class="text-slate-200">${l.start_date}</span></div>
          <div><span class="text-slate-500">Bitiş:</span> <span class="text-slate-200">${l.end_date==='SINIRSIZ'?'Sınırsız':l.end_date}</span></div>
          <div class="pt-0.5"><span class="${badgeCls} border px-1.5 py-0.5 rounded text-[10px] font-semibold">${badgeTxt}</span></div>
        </div>
        <button onclick="deleteDevice(${l.id})" class="text-red-400 hover:text-red-300 text-xs p-1"><i class="fa-solid fa-trash-can"></i></button>
      </div>
      <div class="bg-[#121b2d] border border-slate-800/80 rounded p-2 flex items-center justify-between gap-2">
        <div class="flex flex-col flex-1">
          <span class="text-[9px] text-slate-500 font-semibold uppercase tracking-wider mb-0.5">Süreyi Uzat (Yeni Bitiş)</span>
          <input type="date" id="ext-${l.id}" value="${l.end_date==='SINIRSIZ'?nextYear:l.end_date}"
            class="bg-[#0b111e] border border-slate-800 text-slate-200 px-2 py-1 text-[11px] rounded focus:outline-none focus:border-blue-500 w-full">
        </div>
        <button onclick="extendDevice(${l.id})" class="bg-emerald-600 hover:bg-emerald-500 text-white p-2 rounded transition shadow mt-3 shrink-0" title="Süreyi Güncelle">
          <i class="fa-solid fa-check text-xs"></i>
        </button>
      </div>
      <div class="bg-[#121b2d] border border-slate-800 rounded px-2.5 py-2 flex items-center justify-between gap-2">
        <div class="font-mono text-[11px] text-slate-400 overflow-hidden text-ellipsis whitespace-nowrap flex-1">${l.license_id}</div>
        <button onclick="showLic('${l.license_file.replace(/'/g,"\\'")}','${l.license_id}')" class="bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white px-2 py-1 rounded text-[10px] border border-blue-600/30 transition shrink-0 flex items-center gap-1">
          <i class="fa-solid fa-file-arrow-down"></i> Lisans İndir
        </button>
      </div>`;
    list.appendChild(div);
  });
}

function closePanel(){
  document.getElementById('devicePanel').classList.remove('open');
  setTimeout(()=>{
    document.getElementById('devicePanel').style.visibility='hidden';
    _curCid=null;
  },300);
  loadAll();
}

function setType(type){
  _licType=type;
  const pcBtn=document.getElementById('btnTypePC');
  const usbBtn=document.getElementById('btnTypeUSB');
  const usbGrp=document.getElementById('usbInputGroup');
  const active='bg-blue-600 text-white border border-blue-500 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2 shadow-md';
  const passive='bg-[#111a2e] text-slate-400 border border-slate-800 hover:bg-slate-800 hover:text-slate-200 py-2 rounded text-xs font-semibold transition flex items-center justify-center gap-2';
  if(type==='PC'){pcBtn.className=active;usbBtn.className=passive;usbGrp.classList.add('hidden');}
  else{usbBtn.className=active;pcBtn.className=passive;usbGrp.classList.remove('hidden');}
}

async function createDevice(){
  if(!_curCid)return;
  const body={machine_id:document.getElementById('newMid').value.trim(),
    usb_serial:_licType==='USB'?document.getElementById('newUsb').value.trim():'',
    start_date:document.getElementById('newStart').value,
    end_date:document.getElementById('newEnd').value};
  if(!body.machine_id){showDevMsg('Makine ID zorunludur','red');return;}
  if(_licType==='USB'&&!body.usb_serial){showDevMsg('USB Seri No zorunludur','red');return;}
  const r=await fetch(`/api/customers/${_curCid}/licenses`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(!r.ok){showDevMsg(d.error||'Hata','red');return;}
  _licTxt=d.license_file;_licId=d.license_id;
  document.getElementById('licContent').textContent=d.license_file;
  document.getElementById('licModal').style.display='flex';
  await loadDevices();
}

async function extendDevice(id){
  const newEnd=document.getElementById('ext-'+id).value;
  if(!newEnd){return;}
  const r=await fetch(`/api/licenses/${id}/extend`,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({end_date:newEnd})});
  const d=await r.json();
  if(!r.ok){alert('Hata: '+(d.error||''));return;}
  _licTxt=d.license_file;_licId='';
  document.getElementById('licContent').textContent=d.license_file;
  document.getElementById('licModal').style.display='flex';
  await loadDevices();
}

async function deleteDevice(id){
  if(!confirm('Bu cihaz lisansını silmek istiyor musunuz?'))return;
  await fetch(`/api/licenses/${id}`,{method:'DELETE'});
  await loadDevices();
}

function showLic(file,id){
  _licTxt=file;_licId=id;
  document.getElementById('licContent').textContent=file;
  document.getElementById('licModal').style.display='flex';
}

// ── MODAL ─────────────────────────────────────────────────────────────────────
function copyLic(){navigator.clipboard.writeText(_licTxt).then(()=>alert('Kopyalandı!'));}
function downloadLic(){
  const a=document.createElement('a');
  a.href='data:text/plain;charset=utf-8,'+encodeURIComponent(_licTxt);
  a.download='license.lic';a.click();
}
function closeLicModal(){document.getElementById('licModal').style.display='none';}

// ── YARDIMCILAR ───────────────────────────────────────────────────────────────
function showMsg(id,msg,color){
  const el=document.getElementById(id);
  el.innerHTML=`<div class="border rounded px-4 py-2.5 text-xs ${color==='red'?'bg-red-950/50 border-red-900/60 text-red-400':'bg-emerald-950/50 border-emerald-900/60 text-emerald-400'}">${msg}</div>`;
  el.classList.remove('hidden');
  setTimeout(()=>el.classList.add('hidden'),4000);
}
function showDevMsg(msg,color){
  const el=document.getElementById('devMsg');
  el.textContent=msg;el.className=`text-xs ${color==='red'?'text-red-400':'text-emerald-400'}`;
  el.classList.remove('hidden');
  setTimeout(()=>el.classList.add('hidden'),3000);
}
</script>
</body>
</html>"""

# ── BAŞLAT ────────────────────────────────────────────────────────────────────
if __name__=="__main__":
    if not _CRYPTO:
        print("cryptography paketi gerekli: pip install cryptography")
        import sys; sys.exit(1)
    init_db()
    print(f"\n  ⚙️  Admin Paneli → http://localhost:5002")
    print(f"  Şifre: 14531453\n")
    threading.Timer(1.5,lambda:webbrowser.open("http://localhost:5002")).start()
    app.run(host="127.0.0.1",port=5002,debug=False,threaded=True,use_reloader=False)
