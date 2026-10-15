<#
.SYNOPSIS
  Copies the newest release's install bundle from GitHub into your OneDrive folder and
  removes the older ones. Runs on the owner's Windows PC (docs/releasing.md).

.DESCRIPTION
  Each release on GitHub carries its install bundle (made by the Release workflow): the
  .tar.gz, its .sha256 and the MANIFEST. This script:
    1. asks GitHub for the newest release (read-only token, kept encrypted for your
       Windows account only);
    2. if its bundle isn't in <Folder>\<version>\ yet, downloads the three files, checks
       the SHA-256 and only then puts them in place (with the release notes);
    3. removes older version folders (x.y.z), keeping -Keep versions in all. Deleted
       folders go to the OneDrive recycle bin for 30 days.
  Run it again and it does nothing until there is a new release.

  One-time set-up (PowerShell, as yourself, not as administrator):
    .\Sync-NetCairnRelease.ps1 -SetToken      # paste the GitHub token
    .\Sync-NetCairnRelease.ps1                # first copy, to check it works
    .\Sync-NetCairnRelease.ps1 -Register      # then every day at 08:10 and at sign-in

.PARAMETER Folder
  Where the releases go. Default: <your OneDrive>\NetCairn\releases. Share this folder
  (not a version folder) with customers, so the link stays the same between releases.

.PARAMETER Keep
  How many versions to keep, the newest included. Default 1: only the newest.
#>
[CmdletBinding()]
param(
    [string]$Folder = $(if ($env:OneDrive) { Join-Path $env:OneDrive 'NetCairn\releases' } else { '' }),
    [string]$Repo = 'kevcarolan/networking-tool-kev',
    [ValidateRange(1, 20)][int]$Keep = 1,
    [switch]$SetToken,
    [switch]$Register
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # much faster downloads on Windows PowerShell 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$DataDir = Join-Path $env:LOCALAPPDATA 'NetCairn'
$TokenFile = Join-Path $DataDir 'github-token.dat'
$LogFile = Join-Path $DataDir 'release-sync.log'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Say([string]$Text) {
    $line = '{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $Text
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

if ($SetToken) {
    Write-Host 'Paste a GitHub fine-grained token: this repository only, permission Contents: Read-only.'
    $secure = Read-Host -AsSecureString 'Token'
    # Encrypted with Windows DPAPI: only your account on this PC can read it back.
    $secure | ConvertFrom-SecureString | Set-Content -Path $TokenFile -Encoding ASCII
    Say 'Token saved.'
    return
}

if ($Register) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Folder "{1}" -Repo "{2}" -Keep {3}' -f
        $PSCommandPath, $Folder, $Repo, $Keep)
    $triggers = @((New-ScheduledTaskTrigger -Daily -At '08:10'), (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME))
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName 'NetCairn release sync' -Action $action -Trigger $triggers `
        -Settings $settings -Description 'Copies the newest install bundle from GitHub into OneDrive' -Force | Out-Null
    Say "Scheduled task 'NetCairn release sync' registered: daily at 08:10 and at sign-in."
    return
}

if (-not $Folder) { throw 'OneDrive was not found: give the folder with -Folder' }
if (-not (Test-Path $TokenFile)) { throw 'No GitHub token yet: run this script with -SetToken first' }
$token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR((Get-Content $TokenFile | ConvertTo-SecureString)))
$headers = @{ Authorization = "Bearer $token"; 'User-Agent' = 'netcairn-release-sync'; 'X-GitHub-Api-Version' = '2022-11-28' }

try {
    $release = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri "https://api.github.com/repos/$Repo/releases/latest"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { Say 'GitHub refused the token (expired?): make a new one and run with -SetToken'; exit 1 }
    if ($code -eq 404) { Say 'No release yet (or the token cannot see the repository)'; exit 0 }
    throw
}

$version = $release.tag_name -replace '^v', ''
if ($version -notmatch '^\d+\.\d+\.\d+$') { Say "Newest release '$($release.tag_name)' is not x.y.z: skipped"; exit 0 }
$names = @("netops-bundle-$version.tar.gz", "netops-bundle-$version.tar.gz.sha256", "netops-bundle-$version.MANIFEST.txt")
$assets = @{}
foreach ($a in $release.assets) { $assets[$a.name] = $a }
$missing = $names | Where-Object { -not $assets.ContainsKey($_) }
if ($missing) { Say "Release $version has no bundle yet (still building?): will try again next run"; exit 0 }

New-Item -ItemType Directory -Force -Path $Folder | Out-Null
$target = Join-Path $Folder $version
$bundle = Join-Path $target $names[0]
$expected = ''
if (Test-Path $bundle) {
    $expected = ((Get-Content (Join-Path $target $names[1]) -Raw) -split '\s+')[0].ToLower()
}
if ($expected -and (Get-FileHash $bundle -Algorithm SHA256).Hash.ToLower() -eq $expected) {
    Say "Up to date: $version is in $target"
} else {
    $incoming = Join-Path $Folder ".incoming-$version"
    if (Test-Path $incoming) { Remove-Item $incoming -Recurse -Force }
    New-Item -ItemType Directory -Path $incoming | Out-Null
    $dl = $headers.Clone()
    $dl['Accept'] = 'application/octet-stream'
    foreach ($n in $names) {
        Say "Downloading $n"
        Invoke-WebRequest -UseBasicParsing -Headers $dl -Uri $assets[$n].url -OutFile (Join-Path $incoming $n)
    }
    $expected = ((Get-Content (Join-Path $incoming $names[1]) -Raw) -split '\s+')[0].ToLower()
    $actual = (Get-FileHash (Join-Path $incoming $names[0]) -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Remove-Item $incoming -Recurse -Force
        Say "SHA-256 mismatch for $($names[0]): nothing changed"
        exit 1
    }
    Set-Content -Path (Join-Path $incoming 'RELEASE-NOTES.md') -Value "# $version`r`n`r`n$($release.body)" -Encoding UTF8
    if (Test-Path $target) { Remove-Item $target -Recurse -Force }
    Rename-Item $incoming $version
    Say "Copied $version to $target (SHA-256 $actual)"
}

# Older versions: only folders named like a version and older than this one (a later patch
# for an old version never removes a newer one), never anything else in the folder.
$old = Get-ChildItem $Folder -Directory |
    Where-Object { $_.Name -match '^\d+\.\d+\.\d+$' -and [version]$_.Name -lt [version]$version } |
    Sort-Object { [version]$_.Name } -Descending | Select-Object -Skip ($Keep - 1)
foreach ($d in $old) {
    Remove-Item $d.FullName -Recurse -Force
    Say "Removed old version $($d.Name)"
}
