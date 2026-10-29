#!/usr/bin/env bash
echo "=== TESTE DE ESTRESSE DE CPU (CGROUPS) ==="
echo "Cgroup atual do processo:"
cat /proc/self/cgroup

echo "Limite configurado no Kernel (cpu.max):"
# Tenta ler o limite diretamente se acessível ou apenas inicia o estresse
cat /sys/fs/cgroup/*/cpu.max 2>/dev/null | head -n 5 || true

echo -e "\nIniciando loop intenso de CPU por 25 segundos..."
echo "Abra o 'htop' na VM (vagrant ssh webserver) para conferir o limite de 50%!"

timeout 25 bash -c 'while true; do :; done'

echo "Estresse de CPU finalizado com sucesso!"