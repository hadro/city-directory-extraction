// Gated Sonnet fan-out for Trow column_count + page_offset.
// Run with: Workflow({ scriptPath: ".../data_prep/trow_fanout.workflow.js", args: <packet> })
// where <packet> is the JSON array printed by data_prep/trow_fanout_prep.py.
//
// Each volume -> one Sonnet (cheap-tier) agent reads its 2 listing pages and returns
// structured output. An arithmetic sanity GATE then accepts page_offset only when the
// read is self-consistent (printed in (0, total]; offset in [-25, 60]); otherwise the
// volume's offset is marked ESCALATE for an Opus re-read. column_count is always returned
// (the cheap tier was validated as reliable for it in the session-4 pilot).
export const meta = {
  name: 'trow-fanout-read',
  description: 'Gated Sonnet fan-out: read Trow listing pages -> column_count + page_offset, arithmetic gate on offsets',
  phases: [{ title: 'Read', detail: 'one Sonnet agent per volume, 2 listing pages, structured output + offset gate' }],
}

const CARD = `Reference — Trow New York City Directory (style card):
- Trow listings are DENSE alphabetical residential entries (surname, occupation, address). The 1890s
  layout is 3 columns, but EARLY Trow (through ~1857) is 2 columns — report what you actually see.
- Listing pages carry ADVERTISING (horizontal banners top/bottom, sometimes thin margin strips). Do
  NOT count ad strips as text columns, and NEVER read a page number out of an ad.
- A leading dash "—" repeats the prior surname (ditto).`;

const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    listing_columns: { type: 'integer', description: 'text columns in the alphabetical listing body, ignoring ad strips' },
    page1_printed_page: { type: ['integer', 'null'], description: 'page number in the TOP OUTER CORNER of image 1; null if absent or covered by an ad' },
    page2_printed_page: { type: ['integer', 'null'], description: 'page number in the TOP OUTER CORNER of image 2; null if absent or covered by an ad' },
    looks_like_trow_listing: { type: 'boolean' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    notes: { type: 'string' },
  },
  required: ['listing_columns', 'page1_printed_page', 'page2_printed_page', 'looks_like_trow_listing', 'confidence', 'notes'],
};

const pkt = Array.isArray(args) ? args : [];
if (!pkt.length) { log('empty packet — nothing to read'); return []; }

phase('Read');
const raw = await parallel(pkt.map(v => () =>
  agent(
    `${CARD}\n\nTrow volume "${v.id}" (catalog year ${v.year}). Two mid-volume listing pages:\n` +
    `- PAGE 1: ${v.p1}\n- PAGE 2: ${v.p2}\n\nRead BOTH images. Report: listing_columns (ignore ad strips); ` +
    `page1_printed_page / page2_printed_page taken ONLY from the top outer corner (null if covered by an ad ` +
    `banner — never read a number from an ad); looks_like_trow_listing; confidence; notes. Read only these two images.`,
    { label: `read:${v.year}`, phase: 'Read', model: 'sonnet', schema: SCHEMA }
  ).then(r => ({ ...r, _v: v })).catch(() => null)
));

// arithmetic offset gate
const gate = (printed, leaf, total) =>
  printed != null && printed > 0 && (total ? printed <= total : true) &&
  (leaf - printed) >= -25 && (leaf - printed) <= 60;

const out = raw.filter(Boolean).map(r => {
  const v = r._v;
  const o1 = gate(r.page1_printed_page, v.l1, v.total) ? v.l1 - r.page1_printed_page : null;
  const o2 = gate(r.page2_printed_page, v.l2, v.total) ? v.l2 - r.page2_printed_page : null;
  const off = o1 != null ? o1 : o2;
  return {
    id: v.id, year: v.year, column_count: r.listing_columns,
    page_offset: off ?? null, offset_status: off != null ? 'ok' : 'ESCALATE',
    confidence: r.confidence, looks_like_trow: r.looks_like_trow_listing,
    p1: { leaf: v.l1, printed: r.page1_printed_page, offset: o1 },
    p2: { leaf: v.l2, printed: r.page2_printed_page, offset: o2 },
    notes: r.notes,
  };
});
out.forEach(s => log(`${s.year} ${s.id}: col=${s.column_count} off=${s.page_offset ?? '—'}(${s.offset_status}) conf=${s.confidence}`));
return out;
