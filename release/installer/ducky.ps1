# UEFN Ducky CLI. This process only speaks HTTP to the window on port 4199.
# It starts UEFN-Ducky.exe once when that port is closed, and never when it is open.
# ponytail: one PowerShell process; the window owns the agent, chats, and project.

$ErrorActionPreference = "Stop"

$script:PanelPort = 4199
if ($env:DUCKY_PANEL_PORT) {
    $script:PanelPort = [int]$env:DUCKY_PANEL_PORT
}
$script:Base = "http://127.0.0.1:$($script:PanelPort)"
$script:AppId = "{EAD694ED-E221-40B0-909B-AFFD7F683C9E}_is1"
$script:FeedHost = "https://uefnducky.org"
if ($env:DUCKY_UPDATE_BASE_URL) {
    $script:FeedHost = $env:DUCKY_UPDATE_BASE_URL.TrimEnd("/")
}
# Both waits are capped so a dead panel cannot spin forever. Defaults match a long turn.
$script:ReplyTimeoutSec = 1800
if ($env:DUCKY_REPLY_TIMEOUT_SEC) { $script:ReplyTimeoutSec = [int]$env:DUCKY_REPLY_TIMEOUT_SEC }
$script:StartTimeoutSec = 90
if ($env:DUCKY_START_TIMEOUT_SEC) { $script:StartTimeoutSec = [int]$env:DUCKY_START_TIMEOUT_SEC }

function Write-Out([string]$Text) {
    [Console]::Out.WriteLine($Text)
}

function Write-Err([string]$Text) {
    [Console]::Error.WriteLine($Text)
}

function Get-SessionPath {
    if ($env:DUCKY_SESSION_FILE) { return $env:DUCKY_SESSION_FILE }
    $root = $env:LOCALAPPDATA
    if (-not $root) { $root = $env:APPDATA }
    if (-not $root) { $root = $env:TEMP }
    return (Join-Path $root "UEFN-Ducky\cli-session.json")
}

function Read-Session {
    $path = Get-SessionPath
    if (-not (Test-Path -LiteralPath $path)) {
        return @{ conv_id = ""; mode = "agent" }
    }
    try {
        $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return @{ conv_id = ""; mode = "agent" }
    }
    $mode = [string]$raw.mode
    if ($mode -notin @("ask", "plan", "agent")) { $mode = "agent" }
    return @{ conv_id = [string]$raw.conv_id; mode = $mode }
}

function Write-Session($Session) {
    $path = Get-SessionPath
    $dir = Split-Path -Parent $path
    if ($dir -and -not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $json = ($Session | ConvertTo-Json -Compress)
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, $json, $utf8)
}

function Set-SessionMode([string]$Mode) {
    $session = Read-Session
    $session.mode = $Mode
    Write-Session $session
}

function Set-SessionConv([string]$ConvId) {
    $session = Read-Session
    $session.conv_id = $ConvId
    Write-Session $session
}

function Test-PanelUp {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect("127.0.0.1", $script:PanelPort, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($wait)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-DuckyExe {
    if ($env:DUCKY_EXE) { return $env:DUCKY_EXE }
    $beside = Join-Path $PSScriptRoot "UEFN-Ducky.exe"
    if (Test-Path -LiteralPath $beside) { return $beside }
    $keys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$($script:AppId)",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$($script:AppId)"
    )
    foreach ($key in $keys) {
        try {
            $loc = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).InstallLocation
        } catch {
            continue
        }
        if (-not $loc) { continue }
        $exe = Join-Path $loc "UEFN-Ducky.exe"
        if (Test-Path -LiteralPath $exe) { return $exe }
    }
    return $null
}

function Start-DuckyApp {
    # Port is closed: start the regular window once, then wait until it listens.
    $exe = Get-DuckyExe
    if (-not $exe) {
        throw "UEFN Ducky is not installed. Run: ducky install"
    }
    Start-Process -FilePath $exe | Out-Null
    $deadline = (Get-Date).AddSeconds($script:StartTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PanelUp) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "UEFN Ducky did not open."
}

function Ensure-Ducky {
    if (Test-PanelUp) { return }
    Start-DuckyApp
}

function Invoke-Panel([string]$Method, $CallArgs) {
    $payload = @{ args = $CallArgs } | ConvertTo-Json -Compress -Depth 8
    $uri = "$($script:Base)/__panel_api/$Method"
    $resp = Invoke-RestMethod -Uri $uri -Method POST -Body $payload -ContentType "application/json; charset=utf-8" -TimeoutSec 60
    if (-not $resp.ok) {
        $err = [string]$resp.error
        if (-not $err) { $err = "panel call failed: $Method" }
        throw $err
    }
    return $resp.result
}

function Get-Conversations {
    return @(Invoke-Panel "list_all_conversations" @{})
}

function Resolve-Conversation {
    $list = Get-Conversations
    $session = Read-Session
    if ($session.conv_id) {
        $hit = $list | Where-Object { [string]$_.id -eq $session.conv_id } | Select-Object -First 1
        if ($hit) { return $hit }
    }
    $newest = $list | Sort-Object { [double]$_.updated } -Descending | Select-Object -First 1
    if ($newest) {
        Set-SessionConv ([string]$newest.id)
        return $newest
    }
    $created = Invoke-Panel "create_conversation" @{ folder_id = "" }
    Set-SessionConv ([string]$created.id)
    return $created
}

function Select-ByName($Rows, [string]$Name, [string]$Field) {
    $want = $Name.Trim()
    if (-not $want) { return @() }
    $exact = @($Rows | Where-Object { [string]$_.$Field -eq $want })
    if ($exact.Count -gt 0) { return $exact }
    return @($Rows | Where-Object { [string]$_.$Field -like "$want*" })
}

function Wait-Reply([string]$ConvId) {
    $since = 0
    $deadline = (Get-Date).AddSeconds($script:ReplyTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $page = Invoke-RestMethod -Uri "$($script:Base)/__panel_events?since=$since" -TimeoutSec 30
        if ($null -ne $page.cursor) { $since = [int]$page.cursor }
        $events = @()
        if ($page.events) { $events = @($page.events) }
        $saw = $false
        foreach ($ev in $events) {
            if (-not $ev) { continue }
            if ([string]$ev.conv_id -ne $ConvId) { continue }
            $saw = $true
            $kind = [string]$ev.type
            if ($kind -eq "text_delta") {
                [Console]::Out.Write([string]$ev.text)
            } elseif ($kind -eq "error") {
                [Console]::Out.WriteLine()
                Write-Err ([string]$ev.text)
                return 1
            } elseif ($kind -eq "assistant_done") {
                [Console]::Out.WriteLine()
                return 0
            } elseif ($kind -eq "agent_stopped") {
                [Console]::Out.WriteLine()
                $reason = [string]$ev.reason
                if ($reason -and $reason -ne "done") {
                    $detail = [string]$ev.detail
                    if ($detail) { Write-Err $detail } else { Write-Err "Agent stopped: $reason" }
                    return 1
                }
                return 0
            }
        }
        if (-not $saw) { Start-Sleep -Milliseconds 50 }
    }
    Write-Err "Timed out waiting for a reply."
    return 1
}

function Send-Chat([string]$Text) {
    Ensure-Ducky
    $conv = Resolve-Conversation
    $mode = (Read-Session).mode
    $model = [string]$conv.model
    Invoke-Panel "send_message" @{
        conv_id = [string]$conv.id
        text    = $Text
        mode    = $mode
        model   = $model
    } | Out-Null
    return (Wait-Reply ([string]$conv.id))
}

function Show-Chats {
    Ensure-Ducky
    $session = Read-Session
    $list = Get-Conversations | Sort-Object { [double]$_.updated } -Descending
    if (-not $list) {
        Write-Out "(no chats)"
        return
    }
    foreach ($row in $list) {
        $mark = " "
        if ([string]$row.id -eq $session.conv_id) { $mark = "*" }
        $who = [string]$row.ducky_name
        if (-not $who) { $who = [string]$row.profile_id }
        Write-Out ("{0} {1}  {2}" -f $mark, [string]$row.title, $who)
    }
}

function New-Chat {
    Ensure-Ducky
    $created = Invoke-Panel "create_conversation" @{ folder_id = "" }
    Set-SessionConv ([string]$created.id)
    Write-Out ([string]$created.title)
}

function Use-Chat([string]$Title) {
    Ensure-Ducky
    $hits = Select-ByName (Get-Conversations) $Title "title"
    if ($hits.Count -eq 0) { throw "No chat named '$Title'." }
    if ($hits.Count -gt 1) {
        $names = ($hits | ForEach-Object { [string]$_.title }) -join ", "
        throw "More than one chat matches '$Title': $names"
    }
    Set-SessionConv ([string]$hits[0].id)
    Write-Out ([string]$hits[0].title)
}

function Show-Or-SetProject([string]$Path) {
    Ensure-Ducky
    if (-not $Path) {
        $info = Invoke-Panel "get_project_info" @{}
        Write-Out ([string]$info.path)
        return
    }
    $info = Invoke-Panel "set_project_root" @{ path = $Path }
    $shown = [string]$info.path
    if (-not $shown) { $shown = $Path }
    Write-Out $shown
}

function Use-Ducky([string]$Name) {
    Ensure-Ducky
    $catalog = Invoke-Panel "list_agent_profiles" @{}
    $hits = Select-ByName @($catalog.profiles) $Name "name"
    if ($hits.Count -eq 0) { throw "No ducky named '$Name'." }
    if ($hits.Count -gt 1) {
        $names = ($hits | ForEach-Object { [string]$_.name }) -join ", "
        throw "More than one ducky matches '$Name': $names"
    }
    $profile = $hits[0]
    $conv = Resolve-Conversation
    $config = @{
        profile_id        = [string]$profile.id
        ducky_name        = [string]$profile.name
        ducky_style       = [string]$profile.ducky_style
        ducky_personality = [string]$profile.ducky_personality
    }
    if ($profile.tts_voice) { $config.tts_voice = [string]$profile.tts_voice }
    if ($null -ne $profile.tts_speed) { $config.tts_speed = [double]$profile.tts_speed }
    if ($profile.disabled_packs) { $config.disabled_packs = @($profile.disabled_packs) }
    if ($profile.enabled_subskills) { $config.enabled_subskills = $profile.enabled_subskills }
    if ($profile.disabled_tool_ids) { $config.disabled_tool_ids = @($profile.disabled_tool_ids) }
    Invoke-Panel "apply_ducky_config" @{ conv_id = [string]$conv.id; config = $config } | Out-Null
    $models = @($profile.favorite_models)
    if ($models.Count -gt 0 -and [string]$models[0]) {
        Invoke-Panel "set_conversation_coding_agent" @{
            conv_id      = [string]$conv.id
            coding_agent = "ducky"
            model        = [string]$models[0]
        } | Out-Null
    }
    Write-Out ([string]$profile.name)
}

function Set-Mode([string]$Mode) {
    $name = $Mode.Trim().ToLowerInvariant()
    if (-not $name) {
        Write-Out (Read-Session).mode
        return
    }
    if ($name -notin @("ask", "plan", "agent")) {
        throw "Mode must be ask, plan, or agent."
    }
    Set-SessionMode $name
    Write-Out $name
}

function Show-Status {
    $mode = (Read-Session).mode
    if (-not (Test-PanelUp)) {
        Write-Out "UEFN Ducky is not running"
        Write-Out "mode: $mode"
        return
    }
    $info = Invoke-Panel "get_project_info" @{}
    $conv = Resolve-Conversation
    $who = [string]$conv.ducky_name
    if (-not $who) { $who = [string]$conv.profile_id }
    Write-Out "UEFN Ducky is running"
    Write-Out ("project: {0}" -f [string]$info.path)
    Write-Out ("chat: {0}" -f [string]$conv.title)
    Write-Out ("ducky: {0}" -f $who)
    Write-Out "mode: $mode"
}

function Open-Window {
    if (Test-PanelUp) {
        $body = @{ paths = @(); links = @() } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri "$($script:Base)/__panel_open_files" -Method POST -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
        Write-Out "UEFN Ducky is open"
        return
    }
    Start-DuckyApp
    Write-Out "UEFN Ducky is open"
}

function Unwrap-Feed($Raw) {
    $payload = $Raw.payload
    if ($payload -and $payload.payload -and ($payload.payload.installerUrl -or $payload.payload.currentVersion)) {
        return $payload.payload
    }
    if ($payload -and ($payload.installerUrl -or $payload.currentVersion -or $payload.version)) {
        return $payload
    }
    if ($Raw.installerUrl -or $Raw.currentVersion -or $Raw.version) { return $Raw }
    if ($payload) { return $payload }
    return $Raw
}

function Install-App {
    $uri = "$($script:FeedHost)/api/v1/plugins/uefn-ducky-store/collect/app-version"
    $headers = @{ Origin = $script:FeedHost; Accept = "application/json" }
    $raw = Invoke-RestMethod -Uri $uri -Method POST -Body "{}" -Headers $headers -ContentType "application/json" -TimeoutSec 30
    $feed = Unwrap-Feed $raw
    $paused = [string]$feed.downloadsPaused
    if ($feed.downloadsPaused -eq $true -or $paused -eq "true" -or $paused -eq "1") {
        throw "Downloads are paused."
    }
    $url = [string]$feed.installerUrl
    if (-not $url) { $url = [string]$feed.installer_url }
    if (-not $url) { throw "No installer on the Store feed. Download from https://uefnducky.org/download" }
    if ($url.StartsWith("/")) { $url = $script:FeedHost + $url }
    $version = [string]$feed.currentVersion
    if (-not $version) { $version = [string]$feed.version }
    if (-not $version) { $version = "latest" }
    $dest = Join-Path $env:TEMP ("UEFN-Ducky-Setup-" + $version + ".exe")
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    $hash = [string]$feed.installerSha256
    if (-not $hash) { $hash = [string]$feed.sha256 }
    if ($hash) {
        $got = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
        if ($got.ToLowerInvariant() -ne $hash.ToLowerInvariant()) {
            Remove-Item -LiteralPath $dest -Force
            throw "Installer hash did not match the Store feed."
        }
    }
    Start-Process -FilePath $dest -Wait | Out-Null
}

function Enter-Repl {
    Ensure-Ducky
    while ($true) {
        $line = Read-Host "ducky"
        if ($null -eq $line) { return }
        $text = $line.Trim()
        if (-not $text) { continue }
        if ($text -eq "exit" -or $text -eq "quit" -or $text -eq "/exit") { return }
        try {
            if ($text.StartsWith("/")) {
                $body = $text.Substring(1).Trim()
                $space = $body.IndexOf(" ")
                if ($space -lt 0) {
                    $name = $body
                    $rest = ""
                } else {
                    $name = $body.Substring(0, $space)
                    $rest = $body.Substring($space + 1).Trim()
                }
                Invoke-CommandName $name.ToLowerInvariant() $rest
                continue
            }
            $code = Send-Chat $text
            if ($code -ne 0) { exit $code }
        } catch {
            Write-Err $_.Exception.Message
        }
    }
}

function Invoke-CommandName([string]$Name, [string]$Rest) {
    switch ($Name) {
        "chats" { Show-Chats; return }
        "new" { New-Chat; return }
        "chat" {
            if (-not $Rest) { throw "Usage: ducky chat <title>" }
            Use-Chat $Rest
            return
        }
        "project" { Show-Or-SetProject $Rest; return }
        "use" {
            if (-not $Rest) { throw "Usage: ducky use <name>" }
            Use-Ducky $Rest
            return
        }
        "mode" { Set-Mode $Rest; return }
        "open" { Open-Window; return }
        "status" { Show-Status; return }
        "install" { Install-App; return }
        "update" { Install-App; return }
        default { throw "Unknown command: $Name" }
    }
}

$commands = @("chats", "new", "chat", "project", "use", "mode", "open", "status", "install", "update")
try {
    if ($args.Count -eq 0) {
        Enter-Repl
        exit 0
    }
    $head = [string]$args[0]
    $headLower = $head.ToLowerInvariant()
    if ($commands -contains $headLower) {
        $rest = ""
        if ($args.Count -gt 1) {
            $rest = (($args | Select-Object -Skip 1) -join " ")
        }
        Invoke-CommandName $headLower $rest
        exit 0
    }
    $message = ($args -join " ")
    $code = Send-Chat $message
    exit $code
} catch {
    Write-Err $_.Exception.Message
    exit 1
}
