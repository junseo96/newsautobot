$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Dart-Key.ps1')
function Assert($Condition,[string]$Message) { if (-not $Condition) { throw $Message } }
function Assert-Throws([scriptblock]$Action) {
    $failed=$false
    try { & $Action | Out-Null } catch { $failed=$true }
    Assert $failed 'Malformed synthetic key should be rejected.'
}
# Synthetic strings only: no real credentials, API traffic, or writes.
$fake='z' * 40
Assert ((Normalize-DartKey $fake) -eq $fake) 'Forty characters outside hexadecimal must be accepted locally.'
Assert ((Normalize-DartKey (" `t"+$fake+"`r`n")) -eq $fake) 'Leading/trailing whitespace must be removed.'
Assert-Throws { Normalize-DartKey ('a' * 39) }
Assert-Throws { Normalize-DartKey ('a' * 41) }
Assert-Throws { Normalize-DartKey (('a' * 20)+' '+('b' * 19)) }
Assert-Throws { Normalize-DartKey (('a' * 20)+[char]0+('b' * 19)) }
Assert-Throws { Normalize-DartKey '' }
Write-Output 'PASS: DART documented key length, non-hex characters, whitespace trimming, malformed input rejection (synthetic data only).'
