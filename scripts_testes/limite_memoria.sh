#!/usr/bin/env bash
echo "=== TESTE DE LIMITE DE MEMÓRIA (OOM KILLER) ==="
echo "Limites configurados no Kernel (memory.max / memory.swap.max):"
cat /sys/fs/cgroup/*/memory.max /sys/fs/cgroup/*/memory.swap.max 2>/dev/null | head -n 5 || true
echo "Tentando alocar 700 MB de RAM na memória (Limite do ambiente: 512 MB)..."

python3 -c "
import time
print('Alocando 200 MB...')
bloco1 = bytearray(200 * 1024 * 1024)
time.sleep(2)
print('200 MB alocados com sucesso!')

print('Tentando alocar mais 500 MB (Total 700 MB -> Deve acionar OOM Killer)...')
bloco2 = bytearray(500 * 1024 * 1024)
print('ERRO: O limite de memória não funcionou!')
"

echo "Se esta linha aparecer, o Cgroup de memória falhou."