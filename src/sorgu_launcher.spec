# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

try:
    curl_datas, curl_bins, curl_hidden = collect_all('curl_cffi')
except:
    curl_datas, curl_bins, curl_hidden = [], [], []

mysql_hidden = collect_submodules('mysql.connector')
block_cipher = None

a = Analysis(
    ['sorgu_launcher.py'],
    pathex=['.'],
    binaries=[*curl_bins],
    datas=[*curl_datas],
    hiddenimports=[
        'sorgu_app', 'sorgu_license',
        'flask', 'flask.templating', 'flask.json',
        'jinja2', 'jinja2.ext',
        'werkzeug', 'werkzeug.serving', 'werkzeug.routing',
        'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
        'mysql', 'mysql.connector',
        'mysql.connector.plugins',
        'mysql.connector.plugins.mysql_native_password',
        'mysql.connector.locales',
        'mysql.connector.locales.eng',
        'mysql.connector.locales.eng.client_error',
        'cryptography', 'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'cryptography.hazmat.primitives.hashes',
        'tkinter', 'tkinter.messagebox',
        'queue', 'threading', 'hashlib', 'hmac', 'socket',
        'base64', 'json', 'csv', 'subprocess',
        *curl_hidden, *mysql_hidden,
        'openpyxl','openpyxl.styles','openpyxl.utils',
        'openpyxl.writer.excel','openpyxl.reader.excel',
        'itsdangerous','click','colorama',
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
    name='SorguSistemi',
    debug=False, strip=False, upx=True, console=False,
    bootloader_ignore_signals=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name='SorguSistemi',
)
