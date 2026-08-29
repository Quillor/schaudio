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

-- ===== Playlists & sharing (2026-08-28) =====================================
create extension if not exists pgcrypto;

create table if not exists public.playlists (
  id          uuid primary key default gen_random_uuid(),
  owner_id    uuid not null references auth.users (id) on delete cascade,
  title       text not null check (char_length(title) between 1 and 60),
  description text not null default '' check (char_length(description) <= 240),
  items       jsonb not null default '[]'::jsonb,
  share_token text unique,
  share_notes boolean not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create table if not exists public.playlist_members (
  playlist_id    uuid not null references public.playlists (id) on delete cascade,
  user_id        uuid not null references auth.users (id) on delete cascade,
  display_name   text not null default '',
  share_my_notes boolean not null default true,
  joined_at      timestamptz not null default now(),
  primary key (playlist_id, user_id)
);

create table if not exists public.playlist_notes (
  id          uuid primary key default gen_random_uuid(),
  playlist_id uuid not null references public.playlists (id) on delete cascade,
  user_id     uuid not null references auth.users (id) on delete cascade,
  client_id   text not null,
  slug        text not null,
  chapter     int  not null,
  p int not null, w0 int not null, w1 int not null,
  cat_name    text not null default '',
  cat_color   text not null default 'accent',
  quote       text not null default '',
  note        text not null default '',
  created_at  timestamptz not null default now(),
  unique (playlist_id, user_id, client_id)
);

alter table public.playlists        enable row level security;
alter table public.playlist_members enable row level security;
alter table public.playlist_notes   enable row level security;

create or replace function public.is_playlist_member(pl uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from playlists p
                 where p.id = pl and p.owner_id = auth.uid())
      or exists (select 1 from playlist_members m
                 where m.playlist_id = pl and m.user_id = auth.uid());
$$;

drop policy if exists "members read playlists" on public.playlists;
create policy "members read playlists" on public.playlists
  for select using (public.is_playlist_member(id));
drop policy if exists "owners insert playlists" on public.playlists;
create policy "owners insert playlists" on public.playlists
  for insert with check (auth.uid() = owner_id);
drop policy if exists "owners update playlists" on public.playlists;
create policy "owners update playlists" on public.playlists
  for update using (auth.uid() = owner_id) with check (auth.uid() = owner_id);
drop policy if exists "owners delete playlists" on public.playlists;
create policy "owners delete playlists" on public.playlists
  for delete using (auth.uid() = owner_id);

drop policy if exists "members read members" on public.playlist_members;
create policy "members read members" on public.playlist_members
  for select using (public.is_playlist_member(playlist_id));
drop policy if exists "self update membership" on public.playlist_members;
create policy "self update membership" on public.playlist_members
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "self leave or owner remove" on public.playlist_members;
create policy "self leave or owner remove" on public.playlist_members
  for delete using (auth.uid() = user_id
    or exists (select 1 from playlists p
               where p.id = playlist_id and p.owner_id = auth.uid()));
-- no INSERT policy: joining goes through join_playlist() only

drop policy if exists "read shared notes" on public.playlist_notes;
create policy "read shared notes" on public.playlist_notes
  for select using (
    user_id = auth.uid()
    or ( public.is_playlist_member(playlist_id)
         and exists (select 1 from playlists p
                     where p.id = playlist_id and p.share_notes)
         and exists (select 1 from playlist_members m
                     where m.playlist_id = playlist_notes.playlist_id
                       and m.user_id = playlist_notes.user_id
                       and m.share_my_notes) )
  );
drop policy if exists "authors write notes" on public.playlist_notes;
create policy "authors write notes" on public.playlist_notes
  for insert with check (auth.uid() = user_id and public.is_playlist_member(playlist_id));
drop policy if exists "authors update notes" on public.playlist_notes;
create policy "authors update notes" on public.playlist_notes
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "authors delete notes" on public.playlist_notes;
create policy "authors delete notes" on public.playlist_notes
  for delete using (auth.uid() = user_id);

create or replace function public.share_playlist(pl uuid)
returns text language plpgsql security definer set search_path = public, extensions as $$
declare tok text;
begin
  select share_token into tok from playlists where id = pl and owner_id = auth.uid();
  if not found then raise exception 'not owner'; end if;
  if tok is null then
    tok := encode(gen_random_bytes(16), 'hex');
    update playlists set share_token = tok, updated_at = now() where id = pl;
  end if;
  insert into playlist_members (playlist_id, user_id, display_name)
    values (pl, auth.uid(),
            coalesce((auth.jwt() -> 'user_metadata' ->> 'full_name'), ''))
    on conflict do nothing;
  return tok;
end $$;

create or replace function public.unshare_playlist(pl uuid)
returns void language sql security definer set search_path = public as $$
  update playlists set share_token = null, updated_at = now()
  where id = pl and owner_id = auth.uid();
$$;

create or replace function public.join_playlist(tok text)
returns uuid language plpgsql security definer set search_path = public as $$
declare pl uuid;
begin
  select id into pl from playlists where share_token = tok;
  if not found then raise exception 'invalid link'; end if;
  insert into playlist_members (playlist_id, user_id, display_name)
    values (pl, auth.uid(),
            coalesce((auth.jwt() -> 'user_metadata' ->> 'full_name'), ''))
    on conflict do nothing;
  return pl;
end $$;

-- Guest path: anonymous, listen-safe fields plus note COUNTS only. Real note
-- content is structurally unreachable to anon.
create or replace function public.get_shared_playlist(tok text)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'id', p.id,
    'title', p.title,
    'description', p.description,
    'items', p.items,
    'share_notes', p.share_notes,
    'note_counts', case when p.share_notes then coalesce((
        select jsonb_object_agg(k, c) from (
          select n.slug || ':' || n.chapter as k, count(*) as c
          from playlist_notes n
          join playlist_members m
            on m.playlist_id = n.playlist_id
           and m.user_id = n.user_id and m.share_my_notes
          where n.playlist_id = p.id
          group by 1) t), '{}'::jsonb)
      else '{}'::jsonb end)
  from playlists p
  where p.share_token = tok;
$$;

-- Functions default to EXECUTE for PUBLIC; revoking from anon alone leaves
-- that grant in place, so revoke from public and re-grant to authenticated.
revoke execute on function public.share_playlist(uuid) from public, anon;
revoke execute on function public.unshare_playlist(uuid) from public, anon;
revoke execute on function public.join_playlist(text) from public, anon;
grant execute on function public.share_playlist(uuid) to authenticated;
grant execute on function public.unshare_playlist(uuid) to authenticated;
grant execute on function public.join_playlist(text) to authenticated;
grant execute on function public.get_shared_playlist(text) to anon, authenticated;
