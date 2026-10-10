#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${1:?Informe o nome do ambiente}"

# Aceita somente nomes seguros, sem caminhos.
if [[ ! "$ENV_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Nome de ambiente inválido" >&2
    exit 2
fi

# O cgroup pode usar underscore, mas hostname segue as regras de nomes DNS.
HOSTNAME_VALUE="${ENV_NAME//_/-}"
if [[ ! "$HOSTNAME_VALUE" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
    echo "Nome de hostname inválido ou maior que 63 caracteres" >&2
    exit 2
fi

CGROUP="/sys/fs/cgroup/$ENV_NAME"

if [[ ! -d "$CGROUP" ]]; then
    echo "Cgroup não encontrado: $CGROUP" >&2
    exit 1
fi

# Move este processo para o cgroup antes de criar os filhos.
printf '%s\n' "$$" > "$CGROUP/cgroup.procs"

# Cria os namespaces e inicia um supervisor provisório.
exec /usr/bin/unshare \
    --mount \
    --pid \
    --fork \
    --uts \
    --ipc \
    --mount-proc \
    /usr/bin/bash -c '
        set -e
        hostname "$1"
        exec sleep infinity
    ' bash "$HOSTNAME_VALUE"
