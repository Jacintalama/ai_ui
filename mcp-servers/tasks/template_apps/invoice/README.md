# <%= APP_NAME %> — Invoice Manager

A multi-tenant invoicing app: customers, invoices with line items, status workflow (draft → sent → paid / overdue), and per-user company settings.

## Tables required

See `schema.sql`:
- `customers` — per-user customer records
- `invoices` — invoice header + status enum
- `invoice_items` — line items, scoped via parent invoice
- `company_settings` — one row per user (company name, logo, tax rate)

All tables have RLS policies that restrict access to `auth.uid()`.

## Pages

```
#/login                 Email/password sign in or sign up
#/                      Dashboard (KPIs + recent invoices)
#/customers             Customer list + add/edit modal
#/invoices              Invoice list with status & date filters
#/invoices/new          New invoice form (auto-totals)
#/invoices/{id}         Printable invoice detail + Mark as paid
#/settings              Company settings (logo, address, tax rate)
```

## Structure

```
index.html              Single shell — section x-show by route
schema.sql              Postgres + RLS
styles/main.css
src/main.js             Alpine bootstrap
src/lib/
  supabase.js           Client init from window.SUPABASE_URL / window.SUPABASE_ANON_KEY
  api.js                CRUD wrappers; demo data when not connected
  format.js             Money & date formatting + status colors
src/components/
  AppShell.js           Routing, session, sidebar links
  LoginForm.js
  DashboardPage.js
  CustomersPage.js
  InvoicesListPage.js
  InvoiceFormPage.js
  InvoiceDetailPage.js
  SettingsPage.js
```

## Customizing

- Currency: edit `Intl.NumberFormat` in `src/lib/format.js`.
- Tax rate per invoice (rather than per-user): add a `tax_rate numeric` column to `invoices` and read it in `flattenInvoice`.
- PDF: the detail page uses `window.print()` — pair with a print stylesheet for proper paper output.
