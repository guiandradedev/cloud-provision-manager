-- Criar ambiente
CREATE TABLE IF NOT EXISTS environments (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL
);

-- Criar jobs
CREATE TABLE IF NOT EXISTS jobs (
    id VARCHAR(36) PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    pid INT NULL,
    exit_code INT NULL,
    env_id VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL
);

CREATE TABLE IF NOT EXISTS job_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    stream VARCHAR(10) NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME NOT NULL,

    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

-- Criar arquivos
CREATE TABLE IF NOT EXISTS files (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    name VARCHAR(255) NOT NULL,
    path VARCHAR(255) NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);