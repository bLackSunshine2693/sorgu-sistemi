# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

try:
    curl_datas, curl_bins, curl_hidden = collect_all('curl_cffi')
except:
    curl_datas, curl_bins, curl_hidden = [], [], []

mysql_hidden = collect_submodules('mysql.connector')
block_cipher = None

a = Analysis(
    ['admin_panel.py'],
    pathex=['.'],
    binaries=[*curl_bins],
    datas=[*curl_datas],
    hiddenimports=[
        'sorgu_license',
        'flask', 'flask.templating', 'flask.json',
        'jinja2', 'jinja2.ext',
        'werkzeug', 'werkzeug.serving', 'werkzeug.routing',
        'cryptography', 'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'cryptography.hazmat.primitives.hashes',
        'tkinter', 'tkinter.messagebox',
        'sqlite3', 'hashlib', 'hmac', 'base64',
        'json', 'threading', 'socket', 'subprocess',
        *curl_hidden, *mysql_hidden,
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib','numpy','pandas','scipy','PIL','Pillow','PyQt5','PyQt6','IPython','jupyter','notebook','spyder'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='AdminPanel',
    debug=False, strip=False, upx=True, console=False,
    bootloader_ignore_signals=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='AdminPanel',
    distpath='C:\\SorguSistemi\\src\\dist',
)
