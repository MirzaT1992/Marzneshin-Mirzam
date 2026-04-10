#!/bin/bash

echo "🔥 Installing MariaDB..."

apt update
apt install mariadb-server -y

systemctl enable mariadb
systemctl start mariadb

echo "✅ MariaDB Installed"
