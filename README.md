# AI Workflow – WhatsApp Bot (Intermediate Server)

Connects WhatsApp (Whatabot) with SambaNova LLM and Tavily Search.
Acts as an AI assistant with authentication, memory, and time‑based availability.

## Features
- User authentication via `i_am_user` command
- Persistent login (survives restarts) using Supabase
- Works only 6 AM to 10 PM IST
- Model selection (`sambanova_model_select`)
- Custom system prompt (`llm_change_system`)
- Auto web search when LLM decides it's needed
- Stores user preferences & facts in Supabase
- Logout with `logout`
- UptimeRobot keeps the Render free service alive

## Tech Stack
- Flask, Gunicorn
- Supabase (PostgreSQL)
- Whatabot, SambaNova, Tavily APIs
- Render + GitHub
- UptimeRobot

## Prerequisites
- Whatabot API key and a registered WhatsApp number
- SambaNova API key
- Tavily MCP URL (or API key)
- Supabase project with required tables
- Render account
- UptimeRobot account

## Supabase Tables (run in SQL Editor)
```sql
create table auth (
  id int primary key default 1,
  user_id text,
  password text,
  logged_in boolean default false
);

create table settings (
  key text primary key,
  value text
);

create table conversations (
  id bigserial primary key,
  phone text,
  role text,
  content text,
  created_at timestamptz default now()
);

create table memory (
  phone text primary key,
  data jsonb
);