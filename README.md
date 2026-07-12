# Sorgu Sistemi v4.0
Private repo — Kaynak kod

## Dosya Yapısı
```
src/
  sorgu_app.py          ← Ana uygulama
  sorgu_launcher.py     ← PC launcher
  sorgu_launcher_usb.py ← USB launcher
  sorgu_license.py      ← Lisans motoru
  admin_panel.py        ← Admin paneli
  machine_id_tool.py    ← Makine ID aracı
  *.spec                ← PyInstaller spec dosyaları
version.json            ← Versiyon takibi (otomatik güncelleme)
```

## Build
```cmd
cd src
python -m PyInstaller sorgu_launcher.spec --clean
python -m PyInstaller sorgu_launcher_usb.spec --clean
python -m PyInstaller admin_panel.spec --clean
```

## Güncelleme Yayınlama
1. Kodu değiştir
2. `version.json` → versiyon numarasını artır (4.0.1, 4.0.2...)
3. `git add . && git commit -m "v4.0.1" && git push`
4. Build al → `SorguSistemi.zip` oluştur
5. GitHub → Releases → New release → Tag: v4.0.1 → exe'yi yükle
