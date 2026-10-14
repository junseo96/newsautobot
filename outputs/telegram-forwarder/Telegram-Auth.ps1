# Cloud deployments inject this pair. Never combine an injected credential
# with a file from a different machine or fall back when a pair is incomplete.
function Get-NewsTelegramCredential {
    param([string]$ConfigDir)

    $token = [Environment]::GetEnvironmentVariable('NEWS_TELEGRAM_BOT_TOKEN', 'Process')
    $chatId = [Environment]::GetEnvironmentVariable('NEWS_TELEGRAM_CHAT_ID', 'Process')
    try {
        if ($null -ne $token -or $null -ne $chatId) {
            if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($chatId)) {
                throw 'NEWS_TELEGRAM_BOT_TOKEN and NEWS_TELEGRAM_CHAT_ID must be configured together.'
            }
            return [pscustomobject]@{
                SecureToken = (ConvertTo-SecureString $token.Trim() -AsPlainText -Force)
                ChatId = $chatId.Trim()
            }
        }
        if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
            throw 'Telegram on this platform requires NEWS_TELEGRAM_BOT_TOKEN and NEWS_TELEGRAM_CHAT_ID.'
        }
        if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
            $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
            $ConfigDir = Join-Path $projectRoot '.telegram-forwarder'
        }
        $tokenPath = Join-Path $ConfigDir 'bot-token.dpapi'
        $chatIdPath = Join-Path $ConfigDir 'chat-id.txt'
        if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf) -or -not (Test-Path -LiteralPath $chatIdPath -PathType Leaf)) {
            throw 'Telegram configuration missing.'
        }
        $chatId = [IO.File]::ReadAllText($chatIdPath, [Text.Encoding]::UTF8).Trim()
        if ([string]::IsNullOrWhiteSpace($chatId)) { throw 'Empty Telegram chat configuration.' }
        try {
            $secureToken = ConvertTo-SecureString ([IO.File]::ReadAllText($tokenPath, [Text.Encoding]::UTF8).Trim())
        } catch {
            throw 'Telegram credential unlock failed; credential-bearing errors suppressed.'
        }
        return [pscustomobject]@{ SecureToken = $secureToken; ChatId = $chatId }
    } finally {
        $token = $null
    }
}
