#!/usr/bin/env bash
echo "=== TESTE DE LIMITE DE I/O (CGROUPS) ==="
echo "Cgroup atual do processo:"
cat /proc/self/cgroup

echo "Limite configurado no Kernel (io.max):"
cat /sys/fs/cgroup/*/io.max 2>/dev/null | head -n 5 || true

# /var/tmp fica no disco raiz (mesmo dispositivo limitado no io.max); /tmp pode ser tmpfs
ARQUIVO="/var/tmp/cpm-io-teste-$$.bin"
TAMANHO_MB=16

echo -e "\nGravando ${TAMANHO_MB} MB com escrita direta (sem page cache)..."
echo "Com io_limit_bps = 1048576 (1 MB/s), deve levar ~${TAMANHO_MB} segundos."

inicio=$(date +%s.%N)
dd if=/dev/zero of="$ARQUIVO" bs=1M count="$TAMANHO_MB" oflag=direct status=none
fim=$(date +%s.%N)
duracao=$(awk "BEGIN { printf \"%.2f\", $fim - $inicio }")
echo "Escrita: ${duracao}s (~$(awk "BEGIN { printf \"%.2f\", $TAMANHO_MB / $duracao }") MB/s)"

echo -e "\nLendo ${TAMANHO_MB} MB com leitura direta (sem page cache)..."
inicio=$(date +%s.%N)
dd if="$ARQUIVO" of=/dev/null bs=1M iflag=direct status=none
fim=$(date +%s.%N)
duracao=$(awk "BEGIN { printf \"%.2f\", $fim - $inicio }")
echo "Leitura: ${duracao}s (~$(awk "BEGIN { printf \"%.2f\", $TAMANHO_MB / $duracao }") MB/s)"

rm -f "$ARQUIVO"
echo -e "\nSe as taxas ficaram próximas do limite configurado, o Cgroup de I/O funcionou."
echo "=== FIM DO TESTE ==="
