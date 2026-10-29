-- Persistir o estado do runtime sem alterar as migrations já aplicadas.
ALTER TABLE environments
ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending',
ADD COLUMN anchor_pid INT NULL,
ADD COLUMN cgroup_name VARCHAR(128) NULL,
ADD COLUMN error_message TEXT NULL;

ALTER TABLE jobs
ADD COLUMN cgroup_name VARCHAR(128) NULL;
