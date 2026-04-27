-- Events table for analytics dashboard
create table if not exists events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete cascade,
  event_type text not null check (length(event_type) > 0 and length(event_type) <= 80),
  details jsonb,
  created_at timestamptz not null default now()
);

create index if not exists events_user_idx on events(user_id, created_at desc);
create index if not exists events_type_idx on events(event_type, created_at desc);

alter table events enable row level security;

create policy "users see own events"
  on events for select
  using (auth.uid() = user_id);

create policy "users insert own events"
  on events for insert
  with check (auth.uid() = user_id);
