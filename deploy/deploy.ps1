# Deploys Tabula online: the code to /opt/tabula/app (then restarts the creature, which saves itself
# on the way down and wakes up where it was) and the page to https://kosmo-stars.ru/tabula/.
# Usage: powershell -ExecutionPolicy Bypass -File deploy\deploy.ps1 [-Setup]
#   -Setup  also run deploy/server-setup.sh (first time, or after changing it)
# Ships git HEAD, so commit first. No double quotes in the remote script: Windows PowerShell mangles
# them on the way to ssh.
param(
    [string]$Server = "root@31.76.42.101",
    [string]$Site = "/www/wwwroot/kosmo-stars.ru",
    [switch]$Setup
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Page = "$Site/tabula"

$archive = Join-Path $env:TEMP "tabula.tar.gz"
git archive --format=tar.gz -o $archive HEAD tabula web deploy requirements-server.txt
if ($LASTEXITCODE -ne 0) { throw "packing failed" }
scp -q $archive "${Server}:/tmp/tabula.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "upload failed" }

$setupLine = if ($Setup) { "sh /tmp/tabula-src/deploy/server-setup.sh" } else { "true" }
$remote = @"
set -e
rm -rf /tmp/tabula-src
mkdir -p /tmp/tabula-src
tar -xzf /tmp/tabula.tar.gz -C /tmp/tabula-src
rm /tmp/tabula.tar.gz
$setupLine
rm -rf /opt/tabula/app.next
mkdir -p /opt/tabula/app.next
cp -r /tmp/tabula-src/tabula /opt/tabula/app.next/
cd /opt/tabula/app.next && /opt/tabula/venv/bin/python -c 'import tabula.server' && cd /
rm -rf $Page.next
cp -r /tmp/tabula-src/web $Page.next
chown -R www:www $Page.next
find $Page.next -type d -exec chmod 755 {} +
find $Page.next -type f -exec chmod 644 {} +
systemctl stop tabula || true
rm -rf /opt/tabula/app.old
[ -d /opt/tabula/app ] && mv /opt/tabula/app /opt/tabula/app.old
mv /opt/tabula/app.next /opt/tabula/app
rm -rf $Page.old
[ -d $Page ] && mv $Page $Page.old
mv $Page.next $Page
rm -rf $Page.old /opt/tabula/app.old /tmp/tabula-src
systemctl start tabula
sleep 8
systemctl is-active tabula
curl -sf http://127.0.0.1:8790/state | head -c 160; echo
"@
ssh $Server ($remote -replace "`r", "")
if ($LASTEXITCODE -ne 0) { throw "server update failed" }
Remove-Item $archive
Write-Host "Deployed to https://kosmo-stars.ru/tabula/"
