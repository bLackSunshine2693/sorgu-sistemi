# USB_Sifrele.ps1
# USB'yi BitLocker ile şifreler
# Yönetici olarak çalıştırın: PowerShell -ExecutionPolicy Bypass -File USB_Sifrele.ps1
# Kullanım: .\USB_Sifrele.ps1 -Drive E -Sifre "GucluSifre123!"

param(
    [Parameter(Mandatory=$true)]
    [string]$Drive,      # Örn: E (harf yeterli, : olmadan)
    [Parameter(Mandatory=$true)]
    [string]$Sifre       # BitLocker şifresi
)

$DriveL = "$Drive`:"

Write-Host "`n  SORGU SİSTEMİ — USB BitLocker Şifreleme" -ForegroundColor Cyan
Write-Host "  Sürücü: $DriveL" -ForegroundColor Yellow

# USB takılı mı?
if (-not (Test-Path "$DriveL\")) {
    Write-Error "$DriveL sürücüsü bulunamadı. USB takılı mı?"
    exit 1
}

# SorguSistemi.exe var mı?
if (-not (Test-Path "$DriveL\SorguSistemi.exe")) {
    Write-Warning "$DriveL\SorguSistemi.exe bulunamadı. USB kurulumu tamamlandı mı?"
    $confirm = Read-Host "Yine de devam etmek istiyor musunuz? (E/H)"
    if ($confirm -ne "E") { exit 1 }
}

# Mevcut durum kontrolü
$status = Get-BitLockerVolume -MountPoint $DriveL -ErrorAction SilentlyContinue
if ($status -and $status.ProtectionStatus -eq "On") {
    Write-Host "`n  Bu sürücü zaten BitLocker ile şifreli!" -ForegroundColor Green
    Write-Host "  Volume Status: $($status.VolumeStatus)"
    exit 0
}

Write-Host "`n  BitLocker şifreleme başlıyor..."
Write-Host "  Bu işlem birkaç dakika sürebilir." -ForegroundColor Yellow

# Güvenli şifre oluştur
$SecurePass = ConvertTo-SecureString $Sifre -AsPlainText -Force

try {
    # BitLocker'ı etkinleştir (şifre koruması)
    Enable-BitLocker -MountPoint $DriveL `
        -Password $SecurePass `
        -PasswordProtector `
        -EncryptionMethod XtsAes256 `
        -ErrorAction Stop

    Write-Host "`n  ✅ BitLocker aktif!" -ForegroundColor Green

    # Recovery key kaydet (önemli!)
    $RecoveryKey = (Get-BitLockerVolume -MountPoint $DriveL).KeyProtector |
                   Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' } |
                   Select-Object -First 1

    if ($RecoveryKey) {
        $KeyFile = "$env:USERPROFILE\Desktop\BitLocker_RecoveryKey_$Drive.txt"
        $RecoveryKey.RecoveryPassword | Out-File $KeyFile
        Write-Host "  ⚠️  Recovery Key masaüstüne kaydedildi: $KeyFile" -ForegroundColor Yellow
        Write-Host "  Bu dosyayı güvenli bir yere yedekleyin!" -ForegroundColor Red
    }

    Write-Host "`n  Şifreleme arka planda devam ediyor."
    Write-Host "  USB'yi çekmeden önce şifrelemenin tamamlanmasını bekleyin."
    Write-Host "  Kontrol: manage-bde -status $DriveL"

} catch {
    Write-Error "BitLocker hatası: $_"
    Write-Host "`n  Olası sebep: Windows Home sürümünde BitLocker To Go desteklenmeyebilir."
    Write-Host "  Çözüm: VeraCrypt kullanın (ücretsiz, her Windows sürümünde çalışır)"
    exit 1
}

# USB volume serial no'yu göster (lisans için)
Write-Host "`n  ── USB BİLGİLERİ (lisans için) ──" -ForegroundColor Cyan
$volInfo = Get-Volume -DriveLetter $Drive
$serial  = (Get-Partition -DriveLetter $Drive | Get-Disk).SerialNumber
Write-Host "  Drive    : $DriveL"
Write-Host "  Label    : $($volInfo.FileSystemLabel)"
$volSerial = (cmd /c "vol $DriveL" 2>$null) -match "Serial" | ForEach-Object { $_ -replace '.*is\s+','' }
Write-Host "  Vol Seri : $volSerial" -ForegroundColor Green
Write-Host "  Bu seri numarasını admin panelinize girin."
