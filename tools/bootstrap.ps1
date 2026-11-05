# Creates credentials only. Services and migrations are separate explicit commands.
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Join-Path $env:LOCALAPPDATA "SubseaCopilot"
$path = Join-Path $root "secrets.json"
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
if (Test-Path -LiteralPath $path) {
    throw "Owned secrets already exist; refusing overwrite or reset. Dot-source tools\load-environment.ps1."
}
if ((Test-Path -LiteralPath $root) -and
    ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw "Refusing a linked secrets directory."
}

function Set-UserOnlyAcl([string]$Target, [bool]$Directory) {
    if ($Directory) {
        $acl = [System.Security.AccessControl.DirectorySecurity]::new()
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow"
        )
    } else {
        $acl = [System.Security.AccessControl.FileSecurity]::new()
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($sid, "FullControl", "Allow")
    }
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Target -AclObject $acl
}

function New-RandomHex {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    return [Convert]::ToHexString($bytes).ToLowerInvariant()
}

New-Item -ItemType Directory -Path $root -Force | Out-Null
Set-UserOnlyAcl $root $true
$values = [ordered]@{}
foreach ($name in @(
    "SUBSEA_DB_ADMIN_PASSWORD", "SUBSEA_DB_APP_PASSWORD", "SUBSEA_DB_TOOL_PASSWORD",
    "SUBSEA_DB_CHECKPOINT_PASSWORD", "SUBSEA_OPERATOR_PASSWORD",
    "LF_POSTGRES_PASSWORD", "LF_CLICKHOUSE_PASSWORD", "LF_REDIS_PASSWORD",
    "LF_MINIO_PASSWORD", "LF_SALT", "LF_ENCRYPTION_KEY", "LF_NEXTAUTH_SECRET",
    "LF_ADMIN_PASSWORD"
)) {
    $values[$name] = New-RandomHex
}
$values["LANGFUSE_PUBLIC_KEY"] = "pk-lf-$(New-RandomHex)"
$values["LANGFUSE_SECRET_KEY"] = "sk-lf-$(New-RandomHex)"
$document = @{
    schema_version = 1
    owner_sid = $sid.Value
    secrets = $values
} | ConvertTo-Json -Depth 3
# CreateNew refuses a race with another bootstrap and inherits the private directory ACL.
$stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($document)
    $stream.Write($bytes, 0, $bytes.Length)
} finally {
    $stream.Dispose()
}
Set-UserOnlyAcl $path $false
Write-Output "Owned credentials created at $path"
Write-Output "Dot-source tools\load-environment.ps1 in the same PowerShell process as subsequent commands."
