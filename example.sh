#!/bin/bash
echo "Iniciando estresse de CPU por 30 segundos..."
# Cria um loop infinito de 30 segundos
timeout 30 bash -c 'while true; do true; done'
echo "Fim do teste de CPU."