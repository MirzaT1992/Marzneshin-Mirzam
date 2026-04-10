#!/bin/bash

set -e

echo "🚀 Installing Mirzam Panel..."

apt update
apt install -y git curl docker.io docker-compose

systemctl enable docker
systemctl start docker

git clone https://github.com/MirzaT1992/Marzneshin-Mirzam /opt/marzneshin
cd /opt/marzneshin

docker-compose up -d

echo "✅ Done!"
