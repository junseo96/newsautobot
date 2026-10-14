function Normalize-DartKey([string]$Value) {
    # OpenDART documents STRING(40), not a hexadecimal-only character set.
    $normalized = $Value.Trim()
    if ($normalized.Length -ne 40 -or $normalized -match '[\s\p{C}]') {
        throw 'OpenDART key must contain 40 non-whitespace characters after trimming.'
    }
    return $normalized
}
