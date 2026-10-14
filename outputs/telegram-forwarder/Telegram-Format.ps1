function Get-MessageHash([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function ConvertTo-TelegramHtml([string]$Value) {
    $encoded = [Net.WebUtility]::HtmlEncode($Value)
    $encoded = [regex]::Replace($encoded, '\*\*(.+?)\*\*', '<b>$1</b>')
    # Keep the reviewed URL in the raw message/receipt, but show a compact
    # clickable label in Telegram. Legacy queued drafts use the old link line.
    $link = {
        param($match)
        return '<a href="' + $match.Groups['url'].Value + '">원문보기</a>'
    }
    $encoded = [regex]::Replace($encoded, '(?m)^링크: (?<url>https?://[^\r\n]+)\r?$', $link)
    $encoded = [regex]::Replace($encoded, '(?m)^\[원문보기\]\((?<url>https?://[^\r\n]+)\)\r?$', $link)
    return $encoded
}

function ConvertTo-TelegramHtmlLegacy([string]$Value) {
    # Receipt recovery must verify the bytes sent before the source-link change.
    return [regex]::Replace([Net.WebUtility]::HtmlEncode($Value), '\*\*(.+?)\*\*', '<b>$1</b>')
}

function Split-NewsMessage([string]$Value, [bool]$Bold, [int]$MaximumLength = 3500) {
    # Split raw Markdown, never inside a bold span or an encoded HTML entity.
    $parts = New-Object 'System.Collections.Generic.List[string]'
    $remaining = $Value
    while ($remaining.Length -gt $MaximumLength) {
        $cut = $remaining.LastIndexOf("`n", $MaximumLength)
        if ($cut -lt 1) { $cut = $MaximumLength }
        if ($Bold) {
            while ($cut -gt 0 -and ([regex]::Matches($remaining.Substring(0, $cut), '\*\*').Count % 2) -ne 0) {
                $cut = $remaining.LastIndexOf("`n", $cut - 1)
            }
            if ($cut -le 0) { throw 'A single bold section exceeds the Telegram chunk limit. Shorten the section.' }
        }
        if ($cut -gt 0 -and [char]::IsHighSurrogate($remaining[$cut - 1])) { $cut-- }
        $parts.Add($remaining.Substring(0, $cut).TrimEnd())
        $remaining = $remaining.Substring($cut).TrimStart("`r", "`n")
    }
    if ($remaining.Length -gt 0) { $parts.Add($remaining) }
    return $parts.ToArray()
}

function Assert-NewsFormat([string]$Value) {
    if ($Value -match '(?m)^.*(?:습니다|입니다|됩니다|합니다|읍니다)') { throw 'News messages must use Korean noun endings.' }
    if ($Value -notmatch '(?m)^\*\*\[[^\r\n]+\]\*\*\r?\n\r?\n') { throw 'A bold bracketed headline followed by a blank line is required.' }
    $summaries = [regex]::Matches($Value, '(?m)^\*\*- (?<summary>[^\r\n]*)\*\*\r?$')
    if ($summaries.Count -eq 0) { throw 'A bold one-line summary is required.' }
    foreach ($entry in $summaries) {
        # Inspect every summary, including multi-article briefs. Formatting or
        # invisible characters must not turn a label into substantive content.
        $summary = [regex]::Replace($entry.Groups['summary'].Value, '[\p{Cf}]', '').Trim()
        $summary = [regex]::Replace($summary, '^(?:요약|핵심\s*요약|한\s*줄\s*요약|summary|tl;?dr)\s*[:：]\s*', '', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        $summaryKey = [regex]::Replace($summary, '[^\p{L}\p{Nd}]', '').ToLowerInvariant()
        if (-not $summaryKey -or $summaryKey -match '^(?:(?:핵심|한줄)?요약(?:문|내용)?|summary|tldr|todo|tbd|내용없음|미작성|작성(?:예정|필요)?|입력|실제변화와핵심수치일정진행단계를담은한줄요약)(?:작성|예정|필요|입력|삽입)*$') {
            throw 'A substantive one-line summary is required; labels or placeholders alone are not allowed.'
        }
    }
    if ($Value -notmatch '(?m)^1\. ') { throw 'At least one numbered detail is required.' }
    if ($Value -notmatch '(?m)^(?:링크: https?://|\[원문보기\]\(https?://)') { throw 'An article source link is required.' }
    if ($Value -match '(?m)^\d+\. [^\r\n]+\r?\n\d+\. ') { throw 'Numbered details must have a blank line between them.' }
}

function Save-TelegramReceipt([string]$Path, $Receipt) {
    $parent = [IO.Path]::GetDirectoryName($Path)
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $temporary = $Path + '.tmp'
    [IO.File]::WriteAllText($temporary, ($Receipt | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
    if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, ($Path + '.previous')) }
    else { [IO.File]::Move($temporary, $Path) }
}
