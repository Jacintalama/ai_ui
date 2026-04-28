-- Supabase Auth is managed by the platform; no manual setup needed.
-- Run this in the Supabase SQL editor to create tables and RLS policies.

-- ---- tasks ------------------------------------------------------------------
create table if not exists public.tasks (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  title       text not null,
  description text,
  due_date    date,
  done        boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

alter table public.tasks enable row level security;

create policy "tasks: owner select"  on public.tasks for select  using (auth.uid() = user_id);
create policy "tasks: owner insert"  on public.tasks for insert  with check (auth.uid() = user_id);
create policy "tasks: owner update"  on public.tasks for update  using (auth.uid() = user_id);
create policy "tasks: owner delete"  on public.tasks for delete  using (auth.uid() = user_id);

-- Auto-set user_id on insert
create or replace function public.set_task_user_id()
returns trigger language plpgsql security definer as $$
begin
  new.user_id := auth.uid();
  return new;
end;
$$;

create trigger tasks_set_user_id
  before insert on public.tasks
  for each row execute procedure public.set_task_user_id();

-- Auto-update updated_at
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger tasks_updated_at
  before update on public.tasks
  for each row execute procedure public.set_updated_at();

-- ---- task_comments ----------------------------------------------------------
create table if not exists public.task_comments (
  id         uuid primary key default gen_random_uuid(),
  task_id    uuid not null references public.tasks(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  body       text not null,
  created_at timestamptz not null default now()
);

alter table public.task_comments enable row level security;

create policy "comments: task owner select" on public.task_comments for select
  using (exists (select 1 from public.tasks where id = task_id and user_id = auth.uid()));

create policy "comments: task owner insert" on public.task_comments for insert
  with check (
    auth.uid() = user_id and
    exists (select 1 from public.tasks where id = task_id and user_id = auth.uid())
  );

create policy "comments: owner update" on public.task_comments for update
  using (auth.uid() = user_id);

create policy "comments: owner delete" on public.task_comments for delete
  using (auth.uid() = user_id);

create trigger comments_set_user_id
  before insert on public.task_comments
  for each row execute procedure public.set_task_user_id();
