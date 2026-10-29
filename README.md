# Cloud Provision Manager

Aplicação web para criar ambientes isolados com namespaces e cgroups v2. O sistema permite definir limites de recursos, executar scripts shell, acompanhar a saída e encerrar ambientes e jobs.

## Requisitos

- Vagrant
- VirtualBox
- Pelo menos 6 GB de memória disponível no computador

## Inicialização

Na raiz do projeto, entre no diretório `infra` e inicie as máquinas:

```powershell
cd infra
vagrant up
```

O provisionamento instala e configura o frontend, o backend e o banco de dados. Quando terminar, acesse:

```text
http://localhost:8069
```

Para verificar o estado das máquinas:

```powershell
vagrant status
```

Para desligá-las:

```powershell
vagrant halt
```

As configurações de repositório, branch, banco e memória podem ser alteradas copiando `infra/.env.example` para `infra/.env` antes de executar o provisionamento.
