const PALETTE = [
  { type: 'text',     label: 'Short text',      icon: '🔤' },
  { type: 'textarea', label: 'Long text',       icon: '📝' },
  { type: 'radio',    label: 'Single choice',   icon: '⦿' },
  { type: 'checkbox', label: 'Multiple choice', icon: '☑' },
  { type: 'number',   label: 'Number',          icon: '#' },
  { type: 'date',     label: 'Date',            icon: '📅' },
  { type: 'email',    label: 'Email',           icon: '✉' },
  { type: 'url',      label: 'URL',             icon: '🔗' },
];

function uid() {
  return 'f_' + Math.random().toString(36).slice(2, 9);
}

function defaultField(type) {
  const base = {
    id: uid(),
    type,
    label: PALETTE.find(p => p.type === type)?.label || 'Field',
    placeholder: '',
    required: false,
  };
  if (type === 'radio' || type === 'checkbox') {
    base.options = ['Option 1', 'Option 2', 'Option 3'];
  }
  if (type === 'email') base.placeholder = 'you@example.com';
  if (type === 'url')   base.placeholder = 'https://';
  return base;
}

export function formBuilder() {
  return {
    tabs: [
      { id: 'builder',   label: 'Builder' },
      { id: 'preview',   label: 'Preview' },
      { id: 'responses', label: 'Responses' },
    ],
    tab: 'builder',
    palette: PALETTE,
    form: {
      id: uid(),
      title: 'Untitled form',
      fields: [
        { id: uid(), type: 'text',  label: 'Your name',  placeholder: 'Jane Doe',         required: true },
        { id: uid(), type: 'email', label: 'Email',      placeholder: 'you@example.com',  required: true },
        { id: uid(), type: 'radio', label: 'How did you hear about us?', required: false, options: ['Friend', 'Search', 'Social media', 'Other'] },
      ],
    },
    selectedId: null,
    draft: {},
    responses: [],
    lastSubmitted: false,
    dragOverIndex: null,
    _dragFieldIndex: null,
    shareNote: 'This is a UI demo — link is illustrative; responses live in this browser tab only.',

    get selectedField() {
      return this.form.fields.find(f => f.id === this.selectedId) || null;
    },
    get shareUrl() {
      const base = window.location.origin + window.location.pathname;
      return `${base}?form=${this.form.id}`;
    },

    paletteLabel(type) {
      return PALETTE.find(p => p.type === type)?.label || type;
    },

    addField(type) {
      const f = defaultField(type);
      this.form.fields.push(f);
      this.selectedId = f.id;
    },
    removeField(id) {
      this.form.fields = this.form.fields.filter(f => f.id !== id);
      if (this.selectedId === id) this.selectedId = null;
    },
    moveUp(i) {
      if (i <= 0) return;
      const a = this.form.fields;
      [a[i-1], a[i]] = [a[i], a[i-1]];
    },
    moveDown(i) {
      const a = this.form.fields;
      if (i >= a.length - 1) return;
      [a[i+1], a[i]] = [a[i], a[i+1]];
    },

    onPaletteDragStart(e, type) {
      e.dataTransfer.setData('text/x-palette', type);
      e.dataTransfer.effectAllowed = 'copy';
    },
    onFieldDragStart(e, index) {
      this._dragFieldIndex = index;
      e.dataTransfer.setData('text/x-field-index', String(index));
      e.dataTransfer.effectAllowed = 'move';
    },
    onCanvasDragOver(e) {
      e.dataTransfer.dropEffect = e.dataTransfer.types.includes('text/x-palette') ? 'copy' : 'move';
    },
    onCanvasDrop(e) {
      const type = e.dataTransfer.getData('text/x-palette');
      if (type) this.addField(type);
    },
    onFieldDrop(e, targetIndex) {
      const paletteType = e.dataTransfer.getData('text/x-palette');
      if (paletteType) {
        const f = defaultField(paletteType);
        this.form.fields.splice(targetIndex, 0, f);
        this.selectedId = f.id;
        return;
      }
      const src = this._dragFieldIndex;
      if (src === null || src === targetIndex) return;
      const arr = this.form.fields;
      const [moved] = arr.splice(src, 1);
      arr.splice(targetIndex, 0, moved);
      this._dragFieldIndex = null;
    },

    toggleCheckbox(fieldId, opt, checked) {
      const cur = Array.isArray(this.draft[fieldId]) ? this.draft[fieldId].slice() : [];
      const idx = cur.indexOf(opt);
      if (checked && idx === -1) cur.push(opt);
      if (!checked && idx !== -1) cur.splice(idx, 1);
      this.draft[fieldId] = cur;
    },

    submitResponse() {
      this.responses.push({
        submitted_at: new Date().toISOString(),
        answers: JSON.parse(JSON.stringify(this.draft)),
      });
      this.draft = {};
      this.lastSubmitted = true;
      setTimeout(() => { this.lastSubmitted = false; }, 2500);
    },

    formatAnswer(v) {
      if (v == null || v === '') return '—';
      if (Array.isArray(v)) return v.join(', ');
      return String(v);
    },

    exportCsv() {
      const headers = ['submitted_at', ...this.form.fields.map(f => f.label || 'Untitled')];
      const rows = this.responses.map(r => [
        r.submitted_at,
        ...this.form.fields.map(f => this.formatAnswer(r.answers[f.id])),
      ]);
      const esc = (s) => {
        const str = String(s ?? '');
        return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
      };
      const csv = [headers, ...rows].map(row => row.map(esc).join(',')).join('\n');
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(this.form.title || 'form').replace(/[^a-z0-9-_]+/gi,'_')}_responses.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    clearResponses() {
      if (confirm('Clear all responses for this session?')) this.responses = [];
    },

    async copyShare() {
      try {
        await navigator.clipboard.writeText(this.shareUrl);
      } catch (_) {
        /* clipboard may be unavailable in sandboxed contexts */
      }
    },
  };
}
