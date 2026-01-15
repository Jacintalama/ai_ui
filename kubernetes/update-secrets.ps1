# Update MCP Secrets Script
# Run: .\update-secrets.ps1

# Fill in your API keys below (leave empty if you don't have one)
$secrets = @{
    "GITHUB_TOKEN" = ""        # From https://github.com/settings/tokens
    "LINEAR_API_KEY" = ""      # From https://linear.app/settings/api
    "NOTION_API_KEY" = ""      # From https://www.notion.so/my-integrations
    "HUBSPOT_API_KEY" = ""     # From HubSpot settings
    "GITLAB_TOKEN" = ""        # From https://gitlab.com/-/user_settings/personal_access_tokens
    "PULUMI_ACCESS_TOKEN" = "" # From https://app.pulumi.com/account/tokens
    "ATLASSIAN_TOKEN" = ""     # From https://id.atlassian.com/manage-profile/security/api-tokens
    "ASANA_TOKEN" = ""         # From https://app.asana.com/0/my-apps
    "SENTRY_AUTH_TOKEN" = ""   # From https://sentry.io/settings/account/api/auth-tokens/
    "SONARQUBE_TOKEN" = ""     # From your SonarQube instance
}

Write-Host "Updating MCP secrets..." -ForegroundColor Cyan

foreach ($key in $secrets.Keys) {
    $value = $secrets[$key]
    if ($value -ne "") {
        $base64Value = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($value))
        kubectl patch secret mcp-secrets -n open-webui -p "{`"data`":{`"$key`":`"$base64Value`"}}"
        Write-Host "Updated $key" -ForegroundColor Green
    } else {
        Write-Host "Skipped $key (empty)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Restarting MCP Proxy to apply changes..." -ForegroundColor Cyan
kubectl rollout restart deployment/mcp-proxy -n open-webui

Write-Host ""
Write-Host "Done! MCP Proxy will restart with new API keys." -ForegroundColor Green
