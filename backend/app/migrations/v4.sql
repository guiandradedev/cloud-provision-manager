-- Adicionar limite agregado de leitura e escrita em bytes por segundo.
ALTER TABLE environments
ADD COLUMN io_limit_bps BIGINT NOT NULL DEFAULT 0;
