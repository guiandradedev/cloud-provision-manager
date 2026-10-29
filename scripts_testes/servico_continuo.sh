#!/usr/bin/env bash
echo "=== INICIANDO SERVIÇO CONTÍNUO ==="
CONTADOR=1

while true; do
    echo "[STDOUT] Batimento cardíaco do serviço #$CONTADOR - $(date '+%H:%M:%S')"
    
    # A cada 3 ciclos, gera um alerta no stderr para testar a separação de streams na UI
    if (( CONTADOR % 3 == 0 )); then
        echo "[STDERR] Alerta simulado de monitoramento no ciclo #$CONTADOR" >&2
    fi
    
    CONTADOR=$((CONTADOR + 1))
    sleep 3
done