#!/bin/bash

clear
echo "======================================="
echo "   🚀 Marzneshin Installer"
echo "======================================="
echo ""
echo "Select Database Type:"
echo "1) SQLite (ساده / تست)"
echo "2) MySQL"
echo "3) MariaDB (پیشنهادی 🔥)"
echo ""

read -p "Enter your choice [1-3]: " choice

case $choice in
  1)
    echo "👉 Installing with SQLite..."
    bash install/install-sqlite.sh
    ;;
  2)
    echo "👉 Installing with MySQL..."
    bash install/install-mysql.sh
    ;;
  3)
    echo "👉 Installing with MariaDB..."
    bash install/install-mariadb.sh
    ;;
  *)
    echo "❌ Invalid choice! لطفاً عدد 1 تا 3 وارد کن"
    exit 1
    ;;
esac

echo ""
echo "✅ Installation process finished!"
