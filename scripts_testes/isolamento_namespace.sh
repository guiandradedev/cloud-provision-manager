#!/usr/bin/env bash
echo "=== TESTE DE ISOLAMENTO (NAMESPACES) ==="
echo "Hostname do ambiente (UTS Namespace):"
hostname

echo -e "\nProcessos visíveis dentro do ambiente (PID & Mount Namespace):"
ps aux

echo -e "\nVerificando quem é o PID 1 (deve ser o processo âncora/sleep):"
cat /proc/1/cmdline | tr '\0' ' '
echo -e "\n=== FIM DO TESTE ==="