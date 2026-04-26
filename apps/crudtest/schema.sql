-- CrudTest app schema
-- Table: items
-- Run this in your Supabase SQL editor before using the app.

create table if not exists items (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        not null    default auth.uid(),
  name        text        not null,
  description text,
  status      text        not null    default 'active'
                check (status in ('active', 'inactive', 'pending')),
  created_at  timestamptz not null    default now(),
  updated_at  timestamptz not null    default now()
);

-- Keep updated_at current automatically
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger items_updated_at
  before update on items
  for each row execute procedure set_updated_at();

-- Row-level security
alter table items enable row level security;

create policy "select_own" on items
  for select using (auth.uid() = user_id);

create policy "insert_own" on items
  for insert with check (auth.uid() = user_id);

create policy "update_own" on items
  for update using (auth.uid() = user_id);

create policy "delete_own" on items
  for delete using (auth.uid() = user_id);
