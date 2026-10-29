#!/usr/bin/env bash
echo "Iniciando servidor na porta 8080"
timeout 380 python3 -m http.server 8080 --bind 127.0.0.1 || [ $? -eq 124 ]