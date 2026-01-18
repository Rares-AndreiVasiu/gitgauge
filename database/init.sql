CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    owner VARCHAR(255) NOT NULL,
    repo VARCHAR(255) NOT NULL,
    ref VARCHAR(255) NOT NULL,
    summary TEXT,
    analysis TEXT NOT NULL,
    files_analyzed INTEGER NOT NULL,
    batches_processed INTEGER,
    batches_failed INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(owner, repo, ref)
);

CREATE INDEX IF NOT EXISTS idx_analyses_owner_repo_ref ON analyses(owner, repo, ref);

