param(
    [Parameter(Mandatory=$true)][string]$Folder,
    [Parameter(Mandatory=$true)][string]$Version
)
$ErrorActionPreference = 'Stop'
# Unsigned is an explicit direct-download label,
# never an authenticated updater qualification or a signature-validity claim.
$config = Get-Content -LiteralPath (Join-Path $Folder 'update-config.json') -Raw | ConvertFrom-Json
if ($config.application_id -ne 'com.tlolabs.encap' -or $config.repository -ne 'tlolabs/encap' -or $config.version -ne $Version -or $config.channel -ne 'stable') { throw 'Packaged application/update identity mismatch' }
$actualVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $Folder 'EnCap.exe')).FileVersion
if ([Version]$actualVersion -ne [Version]($Version + '.0')) { throw 'Native executable and Cargo version disagree' }
$executables = @(Get-ChildItem -LiteralPath $Folder -Recurse -File -Filter '*.exe')
if (!$executables.Count) { throw 'No executables to verify' }
foreach ($name in @('EnCap.exe','encap-engine.exe','encap-update.exe','encap-portable-update.exe')) {
    $path = Join-Path $Folder $name
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing first-party executable: $name" }
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'NotSigned') { throw "Expected explicitly unsigned first-party executable: $name" }
}
Write-Output 'Unsigned direct-download package identity verified; Authenticode qualification was not performed.'
