#!/usr/bin/env bash
echo "=== TESTE DE REUSO DE AMBIENTE ==="
ARQUIVO_COMPARTILHADO="/tmp/estado_ambiente.txt"

if [ -f "$ARQUIVO_COMPARTILHADO" ]; then
    echo "Ambiente reutilizado! Histórico de execuções encontradas:"
    cat "$ARQUIVO_COMPARTILHADO"
else
    echo "Primeira execução detectada neste ambiente."
fi

echo "Execução registrada em $(date '+%H:%M:%S') pelo PID interno $$" >> "$ARQUIVO_COMPARTILHADO"

echo -e "\nMantendo este job ativo por 20 segundos para teste de simultaneidade..."
sleep 20
echo "Processos ativos no namespace neste momento:"
ps aux
echo "=== FIM DO TESTE ==="