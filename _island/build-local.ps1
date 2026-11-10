# Build Marc Island on this laptop (not Rox) and optionally install.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$android = Join-Path $root "android"
$javaSrc = Join-Path $android "app\src\main\java\com\marc\island"
$layout = Join-Path $android "app\src\main\res\layout"
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$jdk = "C:\Program Files\Microsoft\jdk-17.0.21.21-hotspot"
$gradle = Join-Path $root "tools\gradle-8.9\bin\gradle.bat"
$adb = Join-Path $sdk "platform-tools\adb.exe"

if (-not (Test-Path $jdk)) { throw "JDK 17 missing at $jdk" }
if (-not (Test-Path $gradle)) { throw "Gradle missing at $gradle" }
if (-not (Test-Path $sdk)) { throw "Android SDK missing at $sdk" }

New-Item -ItemType Directory -Force -Path $javaSrc, $layout | Out-Null
Get-ChildItem (Join-Path $root "*.java") | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $javaSrc $_.Name) -Force
}
Get-ChildItem (Join-Path $root "activity_*.xml") | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $layout $_.Name) -Force
}
Copy-Item (Join-Path $root "AndroidManifest.xml") (Join-Path $android "app\src\main\AndroidManifest.xml") -Force
Copy-Item (Join-Path $root "build.gradle") (Join-Path $android "app\build.gradle") -Force
if (Test-Path (Join-Path $root "strings.xml")) {
    Copy-Item (Join-Path $root "strings.xml") (Join-Path $android "app\src\main\res\values\strings.xml") -Force
}
if (Test-Path (Join-Path $root "values")) {
    Copy-Item (Join-Path $root "values\*") (Join-Path $android "app\src\main\res\values\") -Force
}

$sdkProp = ($sdk -replace '\\', '/')
Set-Content -Path (Join-Path $android "local.properties") -Value "sdk.dir=$sdkProp" -Encoding ASCII

$env:JAVA_HOME = $jdk
$env:ANDROID_HOME = $sdk
$env:Path = "$jdk\bin;$sdk\platform-tools;$env:Path"

Push-Location $android
try {
    & $gradle :app:assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "gradle failed: $LASTEXITCODE" }
} finally {
    Pop-Location
}

$apk = Join-Path $android "app\build\outputs\apk\debug\app-debug.apk"
$out = Join-Path $root "marc-local.apk"
Copy-Item $apk $out -Force
Write-Host "APK $out"

$devices = & $adb devices | Select-String "`tdevice$"
if (-not $devices) {
    Write-Host "No adb device. Plug the phone (USB debugging + File transfer) and rerun with -Install"
    if ($args -contains "-Install") { exit 2 }
    exit 0
}

if ($args -contains "-Install") {
    & $adb install -r $apk
    if ($LASTEXITCODE -ne 0) { throw "adb install failed" }
    & $adb shell "pm grant com.marc.island android.permission.RECORD_AUDIO"
    & $adb shell "pm grant com.marc.island android.permission.POST_NOTIFICATIONS"
    & $adb shell "pm grant com.marc.island android.permission.READ_PHONE_STATE"
    & $adb shell "appops set com.marc.island SYSTEM_ALERT_WINDOW allow"
    # Install clears a11y bindings; toggle so IslandAccess rebinds (needed for lock screen).
    & $adb shell "settings put secure accessibility_enabled 0"
    Start-Sleep -Seconds 1
    & $adb shell "settings put secure enabled_accessibility_services com.marc.island/com.marc.island.IslandAccess"
    & $adb shell "settings put secure accessibility_enabled 1"
    & $adb shell "am start -n com.marc.island/.IslandActivity"
    Write-Host "Installed and started Marc"
}
