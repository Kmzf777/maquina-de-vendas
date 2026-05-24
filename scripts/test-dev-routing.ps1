# test-dev-routing.ps1
# Simula um webhook Meta com o numero de dev e verifica se producao roteou para o dev backend.
# Uso: .\scripts\test-dev-routing.ps1 [-Phone 553496652412]
param(
    [string]$Phone = "553496652412"
)

$ProdUrl   = "https://api.canastrainteligencia.com/webhook/meta"
$SshHost   = "vps-contabo-root"
$PhoneId   = "1079773125220705"
$WabaId    = "1399531671927018"
$Timestamp = [int][double]::Parse((Get-Date -UFormat %s))
$Rand      = [System.Guid]::NewGuid().ToString("N").Substring(0, 12).ToUpper()
$TestWamid = "wamid.TEST-$Rand"

$Payload = @"
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "$WabaId",
    "changes": [{
      "field": "messages",
      "value": {
        "messaging_product": "whatsapp",
        "metadata": { "display_phone_number": "test", "phone_number_id": "$PhoneId" },
        "contacts": [{ "profile": { "name": "[TEST] dev-routing" }, "wa_id": "$Phone" }],
        "messages": [{
          "from": "$Phone",
          "id": "$TestWamid",
          "timestamp": "$Timestamp",
          "type": "text",
          "text": { "body": "[TEST-DEV-ROUTING] pode ignorar" }
        }]
      }
    }]
  }]
}
"@

Write-Host ""
Write-Host "=== SIMULACAO WEBHOOK META ==="
Write-Host "Numero de dev : $Phone"
Write-Host "Wamid de teste: $TestWamid"
Write-Host "Endpoint prod : $ProdUrl"
Write-Host ""

try {
    $Sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri $ProdUrl -Method Post -ContentType "application/json" -Body $Payload
    $Sw.Stop()
    $respJson = $resp | ConvertTo-Json -Compress
    Write-Host "Resposta producao: $respJson ($($Sw.ElapsedMilliseconds)ms)"
} catch {
    Write-Host "ERRO ao chamar producao: $($_.Exception.Message)"
    exit 1
}

Write-Host "Aguardando logs do Swarm (4s)..."
Start-Sleep -Seconds 4

$LogCmd = 'docker service logs canastra_api --since 20s --no-trunc 2>&1 | grep DEV-ROUTER'
$Logs = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 $SshHost $LogCmd 2>&1
$LogStr = "$Logs"

Write-Host ""
Write-Host "--- Logs DEV-ROUTER (ultimos 20s) ---"
Write-Host $LogStr
Write-Host "--------------------------------------"
Write-Host ""

# PASS: whitelist hit com URL correta (dev_url=https://...) sem NOT_IN_WHITELIST
$RoutedPattern  = "dev_url=https://dev.canastrainteligencia.com"
$NotInWhitelist = "NOT_IN_WHITELIST"

if ($LogStr -match [regex]::Escape($RoutedPattern)) {
    Write-Host "RESULTADO: PASS - producao localizou o numero na whitelist e encaminhou para o backend de dev."
} elseif ($LogStr -match $NotInWhitelist) {
    Write-Host "RESULTADO: FAIL - numero nao esta na whitelist."
    Write-Host "Execute: Invoke-RestMethod -Uri https://api.canastrainteligencia.com/api/dev/whitelist/$Phone -Method Post -Body '{`"dev_url`": `"https://dev.canastrainteligencia.com`"}' -ContentType application/json -Headers @{'X-Dev-Key'='canastra-dev-api-key'}"
} elseif ($LogStr.Trim() -ne "") {
    Write-Host "RESULTADO: INDETERMINADO - logs encontrados mas padrao nao reconhecido. Analise acima."
} else {
    Write-Host "RESULTADO: WARN - sem logs DEV-ROUTER nos ultimos 20s."
    Write-Host "Verifique manualmente com: ssh $SshHost docker service logs canastra_api --tail 30"
}
