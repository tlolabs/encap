param([Parameter(Mandatory=$true)][string]$Folder, [Parameter(Mandatory=$true)][string]$ExpectedSubject)
$ErrorActionPreference = 'Stop'
$executables = Get-ChildItem -LiteralPath $Folder -Recurse -File -Filter '*.exe'
if (!$executables) { throw 'No executables to verify' }
foreach ($file in $executables) {
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($signature.Status -ne 'Valid' -or !$signature.TimeStamperCertificate -or !$signature.SignerCertificate) {
        throw "Missing valid timestamped Authenticode signature: $($file.Name)"
    }
    if ($signature.SignerCertificate.Subject -cne $ExpectedSubject) { throw "Unexpected signing subject: $($file.Name)" }
}
Write-Output 'All packaged executables have valid timestamped signatures from the approved Azure profile.'

$config = Get-Content -LiteralPath (Join-Path $Folder 'update-config.json') -Raw | ConvertFrom-Json
$expectedVersion = (Select-String -Path (Join-Path $PSScriptRoot '../Cargo.toml') -Pattern '^version = "([^"]+)"').Matches[0].Groups[1].Value
if ($config.application_id -ne 'com.tlolabs.encap' -or $config.repository -ne 'tlolabs/encap' -or $config.version -ne $expectedVersion -or $config.channel -ne 'stable') { throw 'Packaged application/update identity mismatch' }
$actualVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $Folder 'EnCap.exe')).FileVersion
if ([Version]$actualVersion -ne [Version]($expectedVersion + '.0')) { throw 'Native executable and Cargo version disagree' }
