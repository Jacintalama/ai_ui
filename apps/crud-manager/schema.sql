-- CRUD Manager: Items Table
-- Run this in your Supabase SQL editor

create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  description text,
  category text,
  status text not null default 'active' check (status in ('active', 'inactive', 'pending')),
  priority text not null default 'medium' check (priority in ('low', 'medium', 'high')),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Auto-update updated_at on row change
create or replace function update_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace trigger items_updated_at
  before update on items
  for each row execute function update_updated_at();

-- RLS: anonymous read/write (single-user / unlocked app)
alter table items enable row level security;

create policy "anon_all" on items
  for all to anon
  using (true)
  with check (true);

-- Seed data
insert into items (name, description, category, status, priority, notes) values
  ('Website Redesign', 'Overhaul the company website with new branding', 'Projects', 'active', 'high', 'Design mockups approved'),
  ('Q2 Budget Review', 'Review and approve department budgets for Q2', 'Finance', 'pending', 'high', 'Waiting on HR figures'),
  ('Onboarding Docs', 'Update employee onboarding documentation', 'HR', 'active', 'medium', 'New hire starts May 1'),
  ('Server Migration', 'Migrate legacy servers to cloud infrastructure', 'IT', 'inactive', 'low', 'Scheduled for next quarter'),
  ('Product Roadmap', 'Draft 12-month product roadmap for stakeholders', 'Strategy', 'active', 'medium', 'Initial draft done');
