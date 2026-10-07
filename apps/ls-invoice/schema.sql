-- Invoice manager schema with row-level security
-- Run this in Supabase SQL editor (or as a migration).

-- Enum for invoice status
do $$ begin
  create type invoice_status as enum ('draft', 'sent', 'paid', 'overdue');
exception when duplicate_object then null; end $$;

-- 1. Customers
create table if not exists customers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade not null,
  name text not null check (length(name) > 0 and length(name) <= 200),
  email text,
  address text,
  created_at timestamptz not null default now()
);
create index if not exists customers_user_idx on customers(user_id, name);

alter table customers enable row level security;
create policy "customers select own" on customers for select using (auth.uid() = user_id);
create policy "customers insert own" on customers for insert with check (auth.uid() = user_id);
create policy "customers update own" on customers for update using (auth.uid() = user_id);
create policy "customers delete own" on customers for delete using (auth.uid() = user_id);

-- 2. Invoices
create table if not exists invoices (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade not null,
  customer_id uuid references customers(id) on delete restrict not null,
  invoice_number text not null,
  issue_date date not null,
  due_date date not null,
  status invoice_status not null default 'draft',
  notes text,
  created_at timestamptz not null default now(),
  unique (user_id, invoice_number)
);
create index if not exists invoices_user_issue_idx on invoices(user_id, issue_date desc);

alter table invoices enable row level security;
create policy "invoices select own" on invoices for select using (auth.uid() = user_id);
create policy "invoices insert own" on invoices for insert with check (auth.uid() = user_id);
create policy "invoices update own" on invoices for update using (auth.uid() = user_id);
create policy "invoices delete own" on invoices for delete using (auth.uid() = user_id);

-- 3. Invoice items
create table if not exists invoice_items (
  id uuid primary key default gen_random_uuid(),
  invoice_id uuid references invoices(id) on delete cascade not null,
  description text not null,
  quantity numeric(12,2) not null check (quantity >= 0),
  unit_price numeric(12,2) not null check (unit_price >= 0),
  line_total numeric(14,2) not null check (line_total >= 0)
);
create index if not exists invoice_items_invoice_idx on invoice_items(invoice_id);

alter table invoice_items enable row level security;
-- Items are scoped via the parent invoice's user_id
create policy "items select own" on invoice_items for select
  using (exists (select 1 from invoices i where i.id = invoice_items.invoice_id and i.user_id = auth.uid()));
create policy "items insert own" on invoice_items for insert
  with check (exists (select 1 from invoices i where i.id = invoice_items.invoice_id and i.user_id = auth.uid()));
create policy "items update own" on invoice_items for update
  using (exists (select 1 from invoices i where i.id = invoice_items.invoice_id and i.user_id = auth.uid()));
create policy "items delete own" on invoice_items for delete
  using (exists (select 1 from invoices i where i.id = invoice_items.invoice_id and i.user_id = auth.uid()));

-- 4. Company settings (one row per user)
create table if not exists company_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  company_name text,
  logo_url text,
  address text,
  tax_rate numeric(5,2) not null default 0 check (tax_rate >= 0 and tax_rate <= 100)
);

alter table company_settings enable row level security;
create policy "settings select own" on company_settings for select using (auth.uid() = user_id);
create policy "settings insert own" on company_settings for insert with check (auth.uid() = user_id);
create policy "settings update own" on company_settings for update using (auth.uid() = user_id);
create policy "settings delete own" on company_settings for delete using (auth.uid() = user_id);
