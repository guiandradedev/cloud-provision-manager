#!/usr/bin/env bash
set -euo pipefail
ENV_NAME="${1:?Informe o nome do ambiente}"

if [[ ! "$ENV_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Nome de ambiente inválido" >&2
    exit 2
fi

CGROUP="/sys/fs/cgroup/$ENV_NAME"

if [[ ! -d "$CGROUP" ]]; then
    echo "Cgroup não encontrado: $CGROUP" >&2
    exit 1
fi

# CORREÇÃO: Coloca o PID atual no Cgroup e mantém a sessão ativa de forma simples.
# O isolamento via 'unshare' será injetado no momento da execução de cada job.
echo "$$" > "$CGROUP/cgroup.procs"

exec sleep infinity