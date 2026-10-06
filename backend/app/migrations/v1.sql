CREATE TABLE IF NOT EXISTS jobs (
    id VARCHAR(36) PRIMARY KEY,
    status VARCHAR(20) NOT NULL,
    pid INT NULL,
    exit_code INT NULL,
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