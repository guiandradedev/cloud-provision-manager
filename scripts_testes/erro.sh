#!/usr/bin/env bash
echo "Iniciando operação crítica..."
sleep 2

echo "Erro fatal: Tentativa de acessar recurso inexistente!" >&2
ls /diretorio_que_nao_existe_no_container

# Retorna código de saída diferente de zero para sinalizar falha ao worker
exit 42