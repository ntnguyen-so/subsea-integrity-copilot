# Process-local environment loader for bootstrap's owner-only credential document.
# Validate paths, ACLs, schema, variable set and value formats before any assignment.
# Repeated loads restore the same values; child commands must run in this process.
# This neither starts services nor authenticates hosted Copilot: live calls still
# require the separately configured provider/CLI access and local runtime services.
# Dot-source this script; no credential values are printed.
[CmdletBinding()]
param()
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$root = Join-Path $env:LOCALAPPDATA "SubseaCopilot"
$path = Join-Path $root "secrets.json"
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
foreach ($target in @($root, $path)) {
    if (-not (Test-Path -LiteralPath $target)) {
        throw "Owned credentials are missing; run tools\bootstrap.ps1 first."
    }
    if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw "Refusing linked credential paths."
    }
    $acl = Get-Acl -LiteralPath $target
    if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $sid -or
        -not $acl.AreAccessRulesProtected) {
        throw "Owned credential ACL or owner is invalid."
    }
    foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq "Allow" -and $rule.IdentityReference.Value -ne $sid) {
            throw "Credential ACL allows another principal."
        }
    }
}
if ((Get-Item -LiteralPath $path).Length -gt 16384) {
    throw "Owned credential document exceeds its bound."
}
$document = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
if ($document.schema_version -ne 1 -or $document.owner_sid -ne $sid) {
    throw "Credential document version or ownership is invalid."
}
$required = @(
    "SUBSEA_DB_ADMIN_PASSWORD", "SUBSEA_DB_APP_PASSWORD", "SUBSEA_DB_TOOL_PASSWORD",
    "SUBSEA_DB_CHECKPOINT_PASSWORD", "SUBSEA_OPERATOR_PASSWORD",
    "LF_POSTGRES_PASSWORD", "LF_CLICKHOUSE_PASSWORD", "LF_REDIS_PASSWORD",
    "LF_MINIO_PASSWORD", "LF_SALT", "LF_ENCRYPTION_KEY", "LF_NEXTAUTH_SECRET",
    "LF_ADMIN_PASSWORD", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"
)
$properties = @($document.secrets.PSObject.Properties.Name)
if (@($properties | Where-Object { $_ -notin $required }).Count -ne 0 -or
    $properties.Count -ne $required.Count) {
    throw "Credential variable set is invalid."
}
foreach ($name in $required) {
    $value = $document.secrets.$name
    $pattern = '^[a-f0-9]{64}$'
    if ($name -eq "SUBSEA_OPERATOR_PASSWORD") { $pattern = '^\S{1,1024}$' }
    if ($name -eq "LANGFUSE_PUBLIC_KEY") { $pattern = '^pk-lf-[a-f0-9]{64}$' }
    if ($name -eq "LANGFUSE_SECRET_KEY") { $pattern = '^sk-lf-[a-f0-9]{64}$' }
    if ($value -isnot [string] -or $value -cnotmatch $pattern) {
        throw "A required credential has invalid format."
    }
}
# Validate the entire document before changing the process environment.
foreach ($name in $required) {
    [Environment]::SetEnvironmentVariable($name, $document.secrets.$name, "Process")
}
$env:SUBSEA_RUNTIME_DIR = $root
$env:LANGSMITH_TRACING = "false"
$env:LANGCHAIN_TRACING_V2 = "false"
$env:SUBSEA_SYNTHETIC_ONLY = "1"
# This owned environment contains synthetic demo data only. Preserve an explicit opt-out.
if (-not $env:SUBSEA_TRACE_CONTENT) { $env:SUBSEA_TRACE_CONTENT = "1" }
$env:SUBSEA_TELEMETRY_ENABLED = "1"
$env:SUBSEA_LANGFUSE_ENABLED = "1"
$env:SUBSEA_TRACE_SYNC = "0"
# Jaeger is local and optional; explicit caller preference is preserved.
if (-not $env:SUBSEA_JAEGER_ENABLED) { $env:SUBSEA_JAEGER_ENABLED = "1" }
Write-Output "Owned environment loaded from $path for this PowerShell process."
