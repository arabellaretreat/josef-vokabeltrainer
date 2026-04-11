-- ══════════════════════════════════════════════════════════
-- Josef's Vokabeltrainer – Supabase SQL Schema
-- Dieses Script im Supabase SQL-Editor ausführen:
-- https://supabase.com/dashboard/project → SQL Editor → New query
-- ══════════════════════════════════════════════════════════

-- Vokabeln
CREATE TABLE IF NOT EXISTS vocabulary (
  id            TEXT PRIMARY KEY,
  deutsch       TEXT NOT NULL,
  italienisch   TEXT NOT NULL,
  category      TEXT DEFAULT '',
  added_date    TEXT,
  correct_count INTEGER DEFAULT 0,
  wrong_count   INTEGER DEFAULT 0,
  streak        INTEGER DEFAULT 0,
  last_practiced TEXT
);

-- Tests
CREATE TABLE IF NOT EXISTS tests (
  id          TEXT PRIMARY KEY,
  date        TEXT,
  direction   TEXT,
  total       INTEGER,
  correct     INTEGER,
  percentage  INTEGER,
  grade       INTEGER,
  grade_text  TEXT,
  grade_emoji TEXT,
  results     JSONB DEFAULT '[]'
);

-- Einstellungen (Key-Value)
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- Standard-Einstellungen
INSERT INTO settings (key, value) VALUES
  ('student_name', 'Josef'),
  ('api_key', '')
ON CONFLICT (key) DO NOTHING;

-- Row Level Security deaktivieren (Single-User App)
ALTER TABLE vocabulary DISABLE ROW LEVEL SECURITY;
ALTER TABLE tests      DISABLE ROW LEVEL SECURITY;
ALTER TABLE settings   DISABLE ROW LEVEL SECURITY;
