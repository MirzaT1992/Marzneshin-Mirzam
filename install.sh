#!/bin/bash

clear
echo "======================================="
echo "   🚀 Marzneshin Installer"
echo "======================================="
echo ""

# ====== تنظیمات ======
REPO="https://github.com/MirzaT1992/Marzneshin-Mirzam.git"
BRANCH="EryX0-master"
INSTALL_DIR="/opt/marz"

# ====== نصب پیش‌نیازها ======
echo "📦 Checking dependencies..."

if ! command -v git &> /dev/null
then
    echo "➡️ Installing git..."
    apt update && apt install git -y
fi

# ====== دریافت پروژه ======
echo "📥 Preparing project..."

if [ -d "$INSTALL_DIR" ]; then
    echo "🔄 Project exists, updating..."
    cd $INSTALL_DIR && git pull
else
    echo "⬇️ Cloning project..."
    git clone -b $BRANCH $REPO $INSTALL_DIR
    cd $INSTALL_DIR || exit
fi

# ====== دسترسی اجرا ======
chmod +x install/*.sh 2>/dev/null

# ====== انتخاب دیتابیس ======
echo ""
echo "Select Database Type:"
echo "1) SQLite (ساده)"
echo "2) MySQL"
echo "3) MariaDB 🔥"
echo ""

read -p "Enter your choice [1-3]: " choice

# ====== اجرای نصب ======
case $choice in
  1)
    echo "⚠️ SQLite not implemented yet"
    ;;
  2)
    echo "⚠️ MySQL not implemented yet"
    ;;
  3)
    if [ -f "install/install-mariadb.sh" ]; then
        bash install/install-mariadb.sh
    else
        echo "❌ Error: install-mariadb.sh not found!"
        exit 1
    fi
    ;;
  *)
    echo "❌ Invalid choice"
    exit 1
    ;;
esac

echo ""
echo "✅ Installation step finished!"
