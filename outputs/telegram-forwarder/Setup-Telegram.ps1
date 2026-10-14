[CmdletBinding()]
param(
    [string]$ConfigDir
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$consoleUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $consoleUtf8
[Console]::OutputEncoding = $consoleUtf8
$OutputEncoding = $consoleUtf8

if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $ConfigDir = Join-Path $projectRoot ".telegram-forwarder"
}

$tokenPath = Join-Path $ConfigDir "bot-token.dpapi"
$chatIdPath = Join-Path $ConfigDir "chat-id.txt"
$ignorePath = Join-Path $ConfigDir ".gitignore"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Invoke-TelegramApi {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$Method,
        [hashtable]$Body = @{}
    )

    $uri = "https://api.telegram.org/bot{0}/{1}" -f $Token, $Method
    try {
        $response = Invoke-RestMethod -Method Post -Uri $uri -Body $Body -TimeoutSec 30
    }
    catch {
        throw "Telegram API 요청에 실패했습니다. 인터넷 연결, 방화벽, 봇 토큰을 확인하세요. 보안을 위해 원래 오류와 URL은 표시하지 않습니다."
    }

    if (-not $response.ok) {
        throw "Telegram API가 요청을 거부했습니다. 봇 토큰과 대상 채팅 권한을 확인하세요."
    }
    return $response
}

function Convert-SecureTokenToPlainText {
    param([Parameter(Mandatory = $true)][Security.SecureString]$SecureToken)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureToken)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-ChatDisplayName {
    param($Chat)

    if (-not [string]::IsNullOrWhiteSpace([string]$Chat.title)) {
        return [string]$Chat.title
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$Chat.username)) {
        return "@{0}" -f [string]$Chat.username
    }

    $name = (([string]$Chat.first_name, [string]$Chat.last_name) -join " ").Trim()
    if (-not [string]::IsNullOrWhiteSpace($name)) {
        return $name
    }
    return "이름 없음"
}

Write-Host ""
Write-Host "=== Codex 뉴스 브리프용 Telegram 설정 ===" -ForegroundColor Cyan
Write-Host "봇 토큰은 화면에 표시되지 않으며 PowerShell 명령 기록에도 남지 않습니다."
Write-Host ""

$secureToken = Read-Host "@BotFather가 발급한 봇 토큰을 붙여 넣고 Enter" -AsSecureString
if ($secureToken.Length -eq 0) {
    throw "봇 토큰이 입력되지 않았습니다."
}

$plainToken = Convert-SecureTokenToPlainText -SecureToken $secureToken
try {
    $identity = Invoke-TelegramApi -Token $plainToken -Method "getMe"
    $botUsername = [string]$identity.result.username
    Write-Host ("토큰 확인 성공: @{0}" -f $botUsername) -ForegroundColor Green
    Write-Host ""
    Write-Host "1) Telegram에서 위 봇을 검색해 1:1 대화창을 여세요."
    Write-Host "2) 아래쪽 Start 버튼을 누르거나 /start 를 직접 전송하세요."
    Write-Host "3) 반드시 전송이 끝난 뒤 이 창으로 돌아오세요."
    Write-Host ""

    $candidates = @()
    while ($candidates.Count -eq 0) {
        $answer = Read-Host "전송했으면 Enter. 설정을 끝내려면 Q"
        if ($answer -match "^[Qq]$") {
            Write-Host "설정을 취소했습니다."
            exit 0
        }

        $updates = Invoke-TelegramApi -Token $plainToken -Method "getUpdates" -Body @{
            timeout = 0
            limit = 100
            allowed_updates = '["message","edited_message","channel_post","edited_channel_post"]'
        }

        $found = New-Object System.Collections.Generic.List[object]
        foreach ($update in @($updates.result)) {
            foreach ($field in @("message", "edited_message", "channel_post", "edited_channel_post")) {
                $container = $update.$field
                if ($null -ne $container -and $null -ne $container.chat) {
                    $chat = $container.chat
                    $found.Add([pscustomobject]@{
                        Id = [string]$chat.id
                        Type = [string]$chat.type
                        Name = Get-ChatDisplayName -Chat $chat
                        UpdateId = [long]$update.update_id
                    })
                }
            }
        }

        $candidates = @(
            $found |
                Sort-Object UpdateId -Descending |
                Group-Object Id |
                ForEach-Object { $_.Group[0] }
        )

        if ($candidates.Count -eq 0) {
            Write-Host "받은 메시지가 없습니다. 봇 대화창에서 /start를 실제로 전송했는지 확인한 뒤 다시 시도하세요." -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "발견한 채팅:" -ForegroundColor Cyan
    for ($index = 0; $index -lt $candidates.Count; $index++) {
        $candidate = $candidates[$index]
        Write-Host ("[{0}] {1} | type={2} | chat_id={3}" -f ($index + 1), $candidate.Name, $candidate.Type, $candidate.Id)
    }

    if ($candidates.Count -eq 1) {
        $selected = $candidates[0]
    }
    else {
        do {
            $selectionText = Read-Host "뉴스를 받을 채팅 번호를 입력"
            $selection = 0
            $valid = [int]::TryParse($selectionText, [ref]$selection) -and $selection -ge 1 -and $selection -le $candidates.Count
            if (-not $valid) {
                Write-Host "목록에 있는 번호를 입력하세요." -ForegroundColor Yellow
            }
        } while (-not $valid)
        $selected = $candidates[$selection - 1]
    }

    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
    [IO.File]::WriteAllText($ignorePath, "*`r`n", $utf8NoBom)
    [IO.File]::WriteAllText($tokenPath, ($secureToken | ConvertFrom-SecureString), $utf8NoBom)
    [IO.File]::WriteAllText($chatIdPath, $selected.Id, $utf8NoBom)

    Write-Host ""
    Write-Host ("chat_id 저장 완료: {0}" -f $selected.Id) -ForegroundColor Green
    Write-Host ("설정 폴더: {0}" -f $ConfigDir)
    Write-Host "토큰은 현재 Windows 사용자만 복호화할 수 있는 DPAPI 형식으로 저장했습니다."

    $senderPath = Join-Path $PSScriptRoot "Send-Telegram.ps1"
    if (-not (Test-Path -LiteralPath $senderPath -PathType Leaf)) {
        throw "시험 발송 스크립트를 찾을 수 없습니다: $senderPath"
    }

    & $senderPath -Text "[Codex 연결 시험] Telegram 설정이 완료되었습니다. 이 메시지가 보이면 bot token과 chat_id가 정상입니다." -ConfigDir $ConfigDir
    Write-Host ""
    Write-Host "설정 완료. Telegram에서 시험 메시지를 확인하세요." -ForegroundColor Green
}
finally {
    $plainToken = $null
    $secureToken.Dispose()
}
