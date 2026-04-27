-- Todos table with row-level security
create table if not exists todos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade not null,
  title text not null check (length(title) > 0 and length(title) <= 200),
  completed boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists todos_user_created_idx on todos(user_id, created_at desc);

alter table todos enable row level security;

create policy "users see own todos"
  on todos for select
  using (auth.uid() = user_id);

create policy "users insert own todos"
  on todos for insert
  with check (auth.uid() = user_id);

create policy "users update own todos"
  on todos for update
  using (auth.uid() = user_id);

create policy "users delete own todos"
  on todos for delete
  using (auth.uid() = user_id);
