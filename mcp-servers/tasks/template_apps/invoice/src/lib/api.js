import { supabase, supabaseConnected } from './supabase.js';

// Demo data — used as both the fallback dataset and the seed when not connected.
const DEMO_CUSTOMERS = [
  { id: 'c1', name: 'Northwind Coffee', email: 'ap@northwind.coffee', address: '12 Cedar St, Brooklyn NY' },
  { id: 'c2', name: 'Globex Industries', email: 'billing@globex.io', address: '500 Market St, San Francisco CA' },
  { id: 'c3', name: 'Loftwork Studio', email: 'hello@loftwork.co', address: 'Rua das Flores 12, Lisbon' }
];

const DEMO_INVOICES = [
  {
    id: 'i1', invoice_number: 'INV-1024', customer_id: 'c1', customer_name: 'Northwind Coffee', customer_email: 'ap@northwind.coffee',
    customer_address: '12 Cedar St, Brooklyn NY', issue_date: '2026-04-01', due_date: '2026-04-15',
    status: 'paid', notes: 'Thanks for your business.', tax_rate: 8.5,
    items: [
      { id: 'l1', description: 'Brand identity package', quantity: 1, unit_price: 4500, line_total: 4500 },
      { id: 'l2', description: 'Web design (5 pages)', quantity: 1, unit_price: 2800, line_total: 2800 }
    ],
    subtotal: 7300, tax_total: 620.5, total: 7920.5
  },
  {
    id: 'i2', invoice_number: 'INV-1025', customer_id: 'c2', customer_name: 'Globex Industries', customer_email: 'billing@globex.io',
    customer_address: '500 Market St, San Francisco CA', issue_date: '2026-04-10', due_date: '2026-04-24',
    status: 'sent', notes: '', tax_rate: 8.5,
    items: [
      { id: 'l3', description: 'Quarterly retainer', quantity: 1, unit_price: 6000, line_total: 6000 }
    ],
    subtotal: 6000, tax_total: 510, total: 6510
  },
  {
    id: 'i3', invoice_number: 'INV-1026', customer_id: 'c3', customer_name: 'Loftwork Studio', customer_email: 'hello@loftwork.co',
    customer_address: 'Rua das Flores 12, Lisbon', issue_date: '2026-04-18', due_date: '2026-05-02',
    status: 'draft', notes: '', tax_rate: 8.5,
    items: [
      { id: 'l4', description: 'Workshop facilitation', quantity: 2, unit_price: 1500, line_total: 3000 }
    ],
    subtotal: 3000, tax_total: 255, total: 3255
  },
  {
    id: 'i4', invoice_number: 'INV-1023', customer_id: 'c1', customer_name: 'Northwind Coffee', customer_email: 'ap@northwind.coffee',
    customer_address: '12 Cedar St, Brooklyn NY', issue_date: '2026-03-15', due_date: '2026-03-29',
    status: 'overdue', notes: '', tax_rate: 8.5,
    items: [
      { id: 'l5', description: 'Photography day rate', quantity: 1, unit_price: 1800, line_total: 1800 }
    ],
    subtotal: 1800, tax_total: 153, total: 1953
  }
];

// In-memory store for demo / fallback mode
const demo = {
  customers: [...DEMO_CUSTOMERS],
  invoices: [...DEMO_INVOICES],
  company: { company_name: 'Your Company, Inc.', logo_url: '', address: '', tax_rate: 8.5 }
};

// ---------- Customers ----------
export async function listCustomers(userId) {
  if (!supabaseConnected) return [...demo.customers];
  const { data, error } = await supabase.from('customers').select('*').eq('user_id', userId).order('name');
  if (error) throw error;
  return data || [];
}
export async function upsertCustomer(userId, c) {
  if (!supabaseConnected) {
    if (c.id) {
      const idx = demo.customers.findIndex(x => x.id === c.id);
      if (idx >= 0) demo.customers[idx] = { ...demo.customers[idx], ...c };
      return demo.customers[idx];
    }
    const created = { ...c, id: 'c' + Date.now() };
    demo.customers.push(created);
    return created;
  }
  if (c.id) {
    const { data, error } = await supabase.from('customers').update(c).eq('id', c.id).select().single();
    if (error) throw error;
    return data;
  }
  const { data, error } = await supabase.from('customers').insert({ ...c, user_id: userId }).select().single();
  if (error) throw error;
  return data;
}
export async function deleteCustomer(id) {
  if (!supabaseConnected) { demo.customers = demo.customers.filter(c => c.id !== id); return; }
  const { error } = await supabase.from('customers').delete().eq('id', id);
  if (error) throw error;
}

// ---------- Invoices ----------
export async function listInvoices(userId) {
  if (!supabaseConnected) return [...demo.invoices];
  const { data, error } = await supabase
    .from('invoices')
    .select('*, customers!inner(name, email, address), invoice_items(*)')
    .eq('user_id', userId)
    .order('issue_date', { ascending: false });
  if (error) throw error;
  return (data || []).map(flattenInvoice);
}
export async function getInvoice(userId, id) {
  if (!supabaseConnected) return demo.invoices.find(i => i.id === id) || null;
  const { data, error } = await supabase
    .from('invoices')
    .select('*, customers!inner(name, email, address), invoice_items(*)')
    .eq('user_id', userId)
    .eq('id', id)
    .single();
  if (error) return null;
  return flattenInvoice(data);
}
export async function createInvoice(userId, payload) {
  // payload: { customer_id, issue_date, due_date, status, notes, tax_rate, items[] }
  const subtotal = payload.items.reduce((s, l) => s + (l.quantity || 0) * (l.unit_price || 0), 0);
  const tax_total = +(subtotal * (payload.tax_rate || 0) / 100).toFixed(2);
  const total = +(subtotal + tax_total).toFixed(2);

  if (!supabaseConnected) {
    const cust = demo.customers.find(c => c.id === payload.customer_id) || {};
    const created = {
      id: 'i' + Date.now(),
      invoice_number: 'INV-' + (1027 + demo.invoices.length),
      customer_id: payload.customer_id,
      customer_name: cust.name, customer_email: cust.email, customer_address: cust.address,
      issue_date: payload.issue_date, due_date: payload.due_date,
      status: payload.status || 'draft', notes: payload.notes || '',
      tax_rate: payload.tax_rate, items: payload.items.map((l, i) => ({ ...l, id: 'l' + Date.now() + i, line_total: (l.quantity||0)*(l.unit_price||0) })),
      subtotal, tax_total, total
    };
    demo.invoices.unshift(created);
    return created;
  }

  // Real Supabase: insert invoice, then items
  const invoiceNumber = await nextInvoiceNumber(userId);
  const { data: inv, error: e1 } = await supabase.from('invoices').insert({
    user_id: userId,
    customer_id: payload.customer_id,
    invoice_number: invoiceNumber,
    issue_date: payload.issue_date,
    due_date: payload.due_date,
    status: payload.status || 'draft',
    notes: payload.notes || ''
  }).select().single();
  if (e1) throw e1;

  const items = payload.items.map(l => ({
    invoice_id: inv.id,
    description: l.description,
    quantity: l.quantity,
    unit_price: l.unit_price,
    line_total: (l.quantity || 0) * (l.unit_price || 0)
  }));
  const { error: e2 } = await supabase.from('invoice_items').insert(items);
  if (e2) throw e2;

  return getInvoice(userId, inv.id);
}
export async function markInvoicePaid(userId, id) {
  if (!supabaseConnected) {
    const inv = demo.invoices.find(i => i.id === id);
    if (inv) inv.status = 'paid';
    return inv;
  }
  const { data, error } = await supabase.from('invoices').update({ status: 'paid' }).eq('id', id).select().single();
  if (error) throw error;
  return data;
}

async function nextInvoiceNumber(userId) {
  const { data } = await supabase.from('invoices').select('invoice_number').eq('user_id', userId).order('created_at', { ascending: false }).limit(1);
  const last = data?.[0]?.invoice_number;
  const n = last ? parseInt(String(last).replace(/\D/g, '')) + 1 : 1024;
  return `INV-${n}`;
}

function flattenInvoice(row) {
  const items = (row.invoice_items || []).map(l => ({ ...l }));
  const subtotal = items.reduce((s, l) => s + Number(l.line_total || 0), 0);
  // We don't have per-invoice tax_rate persisted unless added; use company default at runtime
  return {
    ...row,
    customer_name: row.customers?.name,
    customer_email: row.customers?.email,
    customer_address: row.customers?.address,
    items,
    subtotal,
    tax_rate: row.tax_rate ?? 0,
    tax_total: 0,
    total: subtotal
  };
}

// ---------- Company settings ----------
export async function getCompany(userId) {
  if (!supabaseConnected) return { ...demo.company };
  const { data } = await supabase.from('company_settings').select('*').eq('user_id', userId).maybeSingle();
  return data || { company_name: '', logo_url: '', address: '', tax_rate: 0 };
}
export async function saveCompany(userId, payload) {
  if (!supabaseConnected) { Object.assign(demo.company, payload); return demo.company; }
  const { data, error } = await supabase.from('company_settings')
    .upsert({ user_id: userId, ...payload }, { onConflict: 'user_id' })
    .select().single();
  if (error) throw error;
  return data;
}
