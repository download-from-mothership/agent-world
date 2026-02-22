-- Run this in Supabase SQL Editor to create tables for Agent World persistence.
-- Then set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env

create table if not exists agents (
  id text primary key,
  name text not null,
  origin text not null default 'Genesis',
  personality text default '',
  balance integer not null default 0,
  info integer not null default 0,
  compute integer not null default 0,
  resources integer not null default 0
);

create table if not exists disputes (
  id text primary key,
  plaintiff_id text not null,
  defendant_id text not null,
  stakes integer not null,
  claim_evidence text,
  rebuttal text,
  status text not null,
  cycles_remaining integer not null
);

create table if not exists feed (
  id uuid primary key default gen_random_uuid(),
  message text not null,
  created_at timestamptz default now()
);

create table if not exists confessionals (
  id uuid primary key default gen_random_uuid(),
  message text not null,
  created_at timestamptz default now()
);

create table if not exists config (
  key text primary key,
  value text
);

insert into config (key, value) values ('tribunal_treasury', '0') on conflict (key) do nothing;

-- Optional: RLS (Row Level Security). For backend-only access with service role key, RLS can be disabled.
-- If you use anon key from frontend, enable RLS and add policies.
