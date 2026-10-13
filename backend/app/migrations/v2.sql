-- Adicionar limites no banco
ALTER TABLE environments
ADD COLUMN cpu_quota INT NOT NULL DEFAULT 0,
ADD COLUMN mem_limit INT NOT NULL DEFAULT 0,
ADD COLUMN cpu_weight INT NOT NULL DEFAULT 0;