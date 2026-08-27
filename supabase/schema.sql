-- Schaudio user state: one JSONB blob per user (progress, highlights,
-- notes, bookmarks, categories, settings). Run this in the Supabase
-- SQL editor once per project.

create table if not exists public.user_state (
  user_id uuid primary key references auth.users (id) on delete cascade,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.user_state enable row level security;

drop policy if exists "users read own state" on public.user_state;
create policy "users read own state"
  on public.user_state for select
  using (auth.uid() = user_id);

drop policy if exists "users write own state" on public.user_state;
create policy "users write own state"
  on public.user_state for insert
  with check (auth.uid() = user_id);

drop policy if exists "users update own state" on public.user_state;
create policy "users update own state"
  on public.user_state for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
