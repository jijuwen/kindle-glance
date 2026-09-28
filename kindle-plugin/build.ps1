$ErrorActionPreference = 'Stop'
$pluginRoot = Join-Path $PSScriptRoot 'trmnl.koplugin'
$outputDir = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$zipPath = Join-Path $outputDir 'kindleglance-plugin-1.1.0-rc.1.zip'
$files = @('main.lua', 'trmnl_transport.lua', '_meta.lua', 'trmnl_i18n.lua', 'trmnl_menu.lua', 'trmnl_rtc_probe.lua', 'trmnl_rtc_refresh.lua', 'trmnl_diagnostics.lua', 'trmnl_loop.lua', 'trmnl_sleep_badge.lua', 'trmnl_dashboard.lua', 'trmnl_power_guard.lua', 'trmnl_journal.lua', 'LICENSE')
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$stream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::Create)
try {
    $archive = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($name in $files) {
            $path = if ($name -eq 'LICENSE') { Join-Path $PSScriptRoot 'LICENSE' } else { Join-Path $pluginRoot $name }
            $entry = 'koreader/plugins/trmnl.koplugin/' + $name
            $created = $archive.CreateEntry($entry)
            $created.LastWriteTime = [System.DateTimeOffset]::new(2026, 9, 7, 0, 0, 0, [System.TimeSpan]::Zero)
            $inputFile = [System.IO.File]::OpenRead($path)
            $outputFile = $created.Open()
            try { $inputFile.CopyTo($outputFile) }
            finally { $outputFile.Dispose(); $inputFile.Dispose() }
        }
    } finally { $archive.Dispose() }
} finally { $stream.Dispose() }
$check = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($check.Entries.Count -ne $files.Count) { throw 'Unexpected archive contents' }
    foreach ($entry in $check.Entries) {
        if ($entry.FullName -notmatch '^koreader/plugins/trmnl\.koplugin/([\w]+\.lua|LICENSE)$') {
            throw 'Unexpected archive entry'
        }
        $name = $entry.Name
        if ($name -notin $files) { throw 'Unexpected archive file' }
        $source = if ($name -eq 'LICENSE') { Join-Path $PSScriptRoot 'LICENSE' } else { Join-Path $pluginRoot $name }
        $inputStream = $entry.Open()
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try {
            $entryHash = [BitConverter]::ToString($hasher.ComputeHash($inputStream)).Replace('-', '')
        } finally { $inputStream.Dispose(); $hasher.Dispose() }
        if ($entryHash -ne (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash) { throw "Archive differs from source: $name" }
        $entry.FullName
    }
} finally { $check.Dispose() }
$hash = Get-FileHash -LiteralPath $zipPath -Algorithm SHA256
[System.IO.File]::WriteAllText($zipPath + '.sha256', $hash.Hash.ToLowerInvariant() + '  ' + [System.IO.Path]::GetFileName($zipPath) + "`n", [System.Text.Encoding]::ASCII)
$hash | Format-List
