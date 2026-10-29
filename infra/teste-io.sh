#!/usr/bin/env bash
set -e
arquivo="/var/tmp/cpm-io-$$.bin"

inicio=$(date +%s)
dd if=/dev/zero of="$arquivo" bs=1M count=8 oflag=direct status=none
fim=$(date +%s)

rm -f "$arquivo"
echo "Duração: $((fim - inicio)) segundos"