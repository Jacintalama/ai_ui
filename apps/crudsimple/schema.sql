-- CRUDSimple — generic schema template
-- Replace "records" with your actual table name and adjust columns as needed.

create table if not exists records (
  id         bigint generated always as identity primary key,
  user_id    uuid    not null references auth.users(id) on delete cascade,
  name       text    not null,
  notes      text,
  created_at timestamptz default now()
);

-- Row-level security: each user only sees/edits their own rows
alter table records enable row level security;

create policy "Users can manage their own records"
  on records
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Index for faster user-scoped queries
create index if not exists records_user_id_idx on records(user_id);
