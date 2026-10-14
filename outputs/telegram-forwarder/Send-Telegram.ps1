[CmdletBinding(DefaultParameterSetName = "Text")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "Text")]
    [ValidateNotNullOrEmpty()]
    [string]$Text,

    [Parameter(Mandatory = $true, ParameterSetName = "File")]
    [ValidateNotNullOrEmpty()]
    [string]$MessageFile,

    [string]$Title,
    [switch]$MarkdownBold,
    [string]$ConfigDir,
    [string]$ReceiptFile,
    [string[]]$ArticleUrl = @(),
    [string]$ArticleUrlsFile,
    [switch]$NewsFormat,
    [string]$NoveltyReviewFile,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$consoleUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $consoleUtf8
[Console]::OutputEncoding = $consoleUtf8
$OutputEncoding = $consoleUtf8

if ($ReceiptFile -or $ArticleUrl.Count -gt 0 -or $ArticleUrlsFile -or $NewsFormat -or $ValidateOnly) {
    & (Join-Path $PSScriptRoot "Send-VerifiedTelegram.ps1") @PSBoundParameters
    return
}

. (Join-Path $PSScriptRoot 'Telegram-Auth.ps1')

if ($PSCmdlet.ParameterSetName -eq "File") {
    if (-not (Test-Path -LiteralPath $MessageFile -PathType Leaf)) {
        throw "메시지 파일을 찾을 수 없습니다: $MessageFile"
    }
    $message = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $MessageFile).Path, [Text.Encoding]::UTF8)
}
else {
    $message = $Text
}

if (-not [string]::IsNullOrWhiteSpace($Title)) {
    $message = "{0}`r`n`r`n{1}" -f $Title.Trim(), $message
}
$message = $message.Trim()
if ([string]::IsNullOrWhiteSpace($message)) {
    throw "보낼 메시지가 비어 있습니다."
}

if ($MarkdownBold) {
    $message = [Net.WebUtility]::HtmlEncode($message)
    $message = [Text.RegularExpressions.Regex]::Replace(
        $message,
        '\*\*(.+?)\*\*',
        '<b>$1</b>'
    )
}

function Split-TelegramText {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [int]$MaximumLength = 3800
    )

    $parts = New-Object System.Collections.Generic.List[string]
    $remaining = $Value
    while ($remaining.Length -gt $MaximumLength) {
        $cut = $remaining.LastIndexOf("`n", $MaximumLength)
        if ($cut -lt [int]($MaximumLength * 0.55)) {
            $cut = $MaximumLength
        }
        $parts.Add($remaining.Substring(0, $cut).TrimEnd())
        $remaining = $remaining.Substring($cut).TrimStart("`r", "`n")
    }
    if ($remaining.Length -gt 0) {
        $parts.Add($remaining)
    }
    return $parts.ToArray()
}

$credential = $null
$pointer = [IntPtr]::Zero
$plainToken = $null
$uri = $null

try {
    $credential = Get-NewsTelegramCredential -ConfigDir $ConfigDir
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential.SecureToken)
    $plainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $chatId = $credential.ChatId

    $parts = @(Split-TelegramText -Value $message)
    for ($index = 0; $index -lt $parts.Count; $index++) {
        $chunk = $parts[$index]
        if ($parts.Count -gt 1) {
            $chunk = "[{0}/{1}]`r`n{2}" -f ($index + 1), $parts.Count, $chunk
        }

        $uri = "https://api.telegram.org/bot{0}/sendMessage" -f $plainToken
        try {
            $body = @{
                chat_id = $chatId
                text = $chunk
            }
            if ($MarkdownBold) {
                $body.parse_mode = "HTML"
            }
            $response = Invoke-RestMethod -Method Post -Uri $uri -Body $body -TimeoutSec 30
        }
        catch {
            throw "Telegram 발송에 실패했습니다(조각 $($index + 1)/$($parts.Count)). 인터넷 연결, 봇 토큰, chat_id, 봇 권한을 확인하세요. 보안을 위해 원래 오류와 URL은 표시하지 않습니다."
        }

        if (-not $response.ok) {
            throw "Telegram이 발송을 거부했습니다(조각 $($index + 1)/$($parts.Count))."
        }

        if ($index -lt $parts.Count - 1) {
            Start-Sleep -Milliseconds 400
        }
    }

    Write-Host ("Telegram 발송 성공: {0}개 메시지" -f $parts.Count) -ForegroundColor Green
}
finally {
    $plainToken = $null
    $uri = $null
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ($null -ne $credential) { $credential.SecureToken.Dispose(); $credential = $null }
}
