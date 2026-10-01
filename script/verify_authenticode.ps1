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
