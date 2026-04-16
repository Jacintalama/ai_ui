-- Meeting Knowledge Base tables
-- Run this on existing deployments: psql -f scripts/migrate-meeting-kb.sql

CREATE EXTENSION IF NOT EXISTS vector;

-- Updated_at trigger function (reusable)
CREATE OR REPLACE FUNCTION mcp_proxy.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TABLE IF NOT EXISTS mcp_proxy.meeting_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(512) NOT NULL,
    summary TEXT NOT NULL,
    meeting_date TIMESTAMPTZ NOT NULL,
    participants TEXT[] DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    source VARCHAR(128) DEFAULT 'manual',
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_date
    ON mcp_proxy.meeting_summaries (meeting_date DESC);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_participants
    ON mcp_proxy.meeting_summaries USING GIN (participants);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_tags
    ON mcp_proxy.meeting_summaries USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_embedding
    ON mcp_proxy.meeting_summaries USING hnsw (embedding vector_cosine_ops);

-- Updated_at trigger
DROP TRIGGER IF EXISTS update_meeting_summaries_updated_at ON mcp_proxy.meeting_summaries;
CREATE TRIGGER update_meeting_summaries_updated_at
    BEFORE UPDATE ON mcp_proxy.meeting_summaries
    FOR EACH ROW EXECUTE FUNCTION mcp_proxy.update_updated_at_column();

-- API keys for upload authentication
CREATE TABLE IF NOT EXISTS mcp_proxy.meeting_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    description VARCHAR(256) DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
