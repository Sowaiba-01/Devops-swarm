-- PostgreSQL init script
-- Tables are created by SQLAlchemy on startup via init_db().
-- This file exists as a hook for future migrations or seed data.

-- Enable UUID extension (optional, we generate UUIDs in Python)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
