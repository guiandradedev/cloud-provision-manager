#!/usr/bin/env bash

set -e

export DEBIAN_FRONTEND=noninteractive

dpkg --configure -a
apt-get -f install -y
apt-get update -y
apt-get install -y mysql-server

sed -i 's/bind-address.*/bind-address = 0.0.0.0/' /etc/mysql/mysql.conf.d/mysqld.cnf
systemctl restart mysql

mysql -e "CREATE DATABASE IF NOT EXISTS mydb;"
mysql -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'10.20.30.%' IDENTIFIED BY '${DB_PASS}';"
mysql -e "GRANT ALL PRIVILEGES ON mydb.* TO '${DB_USER}'@'10.20.30.%';"
mysql -e "FLUSH PRIVILEGES;"
