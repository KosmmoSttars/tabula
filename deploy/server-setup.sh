#!/bin/sh
# One-time setup of Tabula online on the server (run as root). deploy.ps1 runs it when needed;
# running it again is harmless.
#
#   /opt/tabula/app     the code (replaced on every deploy)
#   /opt/tabula/venv    Python with numpy, pymunk and CPU-only PyTorch
#   /opt/tabula/lives   the creature itself: never touched by a deploy
#
# The service runs at the lowest CPU priority with a CPU and memory cap, so the site, the bot and
# everything else on the box always come first; the creature just lives a little slower when the
# server is busy. nginx passes /tabula/api/ to it on 127.0.0.1:8790.
set -e

id tabula >/dev/null 2>&1 || useradd --system --home /opt/tabula --shell /usr/sbin/nologin tabula
mkdir -p /opt/tabula/app /opt/tabula/lives
chown -R tabula:tabula /opt/tabula/lives

if [ ! -x /opt/tabula/venv/bin/python ]; then
    python3 -m venv /opt/tabula/venv
fi
/opt/tabula/venv/bin/pip install --quiet --upgrade pip
/opt/tabula/venv/bin/pip install --quiet numpy "pymunk>=7"
/opt/tabula/venv/bin/python -c "import torch" 2>/dev/null || \
    /opt/tabula/venv/bin/pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu

cat > /etc/systemd/system/tabula.service <<'UNIT'
[Unit]
Description=Tabula: a creature living online (kosmo-stars.ru/tabula/)
After=network.target

[Service]
User=tabula
WorkingDirectory=/opt/tabula/app
Environment=TABULA_LIVES=/opt/tabula/lives
Environment=OMP_NUM_THREADS=1
Environment=MKL_NUM_THREADS=1
ExecStart=/opt/tabula/venv/bin/python -u -m tabula.server --port 8790
Nice=19
CPUWeight=10
CPUQuota=60%
MemoryMax=900M
Restart=always
RestartSec=10
KillSignal=SIGTERM
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
UNIT

EXT=/www/server/panel/vhost/nginx/extension/kosmo-stars.ru
mkdir -p $EXT
cat > $EXT/tabula.conf <<'NGINX'
# Tabula online: the creature's API (tabula/server.py on 127.0.0.1:8790)
location ^~ /tabula/api/ {
    proxy_pass http://127.0.0.1:8790/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1h;
    access_log off;
}
NGINX
nginx -t
nginx -s reload

systemctl daemon-reload
systemctl enable tabula >/dev/null
echo "setup done"
