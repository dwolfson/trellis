/** The Egeria survey report viewer: header summary, groups by annotation kind (collapsed), element names and
 *  measured values per row, the generic description once per group on hover, large groups capped. */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { makeDomEnvironment, ensureLoaderRegistered } from './dom-harness.mjs';

ensureLoaderRegistered();
const { document } = makeDomEnvironment();
const m = await import('/static/next/stages/native-report.js');
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

const ann = (type, summary, props, qn) => ({
  annotation_type: type, summary,
  detail: { json_properties: JSON.stringify(props), qualified_name: `Annotation::${type}::${qn}::g1` },
});
const TABLE = 'Capture Database Table Measurements';
const COLUMN = 'Capture Database Column Measurements';
const tableAnn = (n) => ann(TABLE, 'Capture summary statistics about a database table.',
  { tableName: `t${n}`, qualifiedTableName: `db.s.t${n}`, tableSize: 2048 * n, tableType: 'Table', columnCount: n, numberOfRowsInserted: 7 }, `db.s.t${n}`);
const colAnn = (t, c) => ann(COLUMN, 'Capture summary statistics about a database column.',
  { qualifiedColumnName: `db.s.${t}.${c}`, columnName: c, columnDataType: 'varchar', columnSize: 43, columnNotNull: true, numberOfDistinctValues: 5 }, `db.s.${t}.${c}`);
const REP = { report_at: '2026-10-03T18:00:00', engine_action_guid: 'ea-9', process_qualified_name: 'Survey PostgreSQL Database',
  annotations: [
    ann('Capture Database Measurements', 'Capture summary statistics about a database.', { resourceName: 'db', schemaCount: 1, tableCount: 2, size: 5242880 }, 'db'),
    ann('Capture Database Schema Measurements', 'x', { qualifiedSchemaName: 'db.s', tableCount: 2, viewCount: 0 }, 'db.s'),
    tableAnn(1), tableAnn(2), colAnn('t1', 'id'), colAnn('t1', 'name'), colAnn('t2', 'id')] };

test('header summary counts annotations by kind and names the report time and engine action', () => {
  const h = m.reportViewerHtml(REP);
  assert.equal(text(h.match(/data-report-summary[^>]*>([\s\S]*?)<\/div>/)[1]), '7 annotations · 1 database · 1 schema · 2 tables · 3 columns');
  assert.match(text(h), /report from 2026-10-03T18:00:00 · Survey PostgreSQL Database · engine action ea-9/);
});

test('groups are collapsed, in database/schema/table/column order, each with its count', () => {
  const root = document.createElement('div'); root.innerHTML = m.reportViewerHtml(REP);
  const groups = [...root.querySelectorAll('details[data-report-group]')];
  assert.deepEqual(groups.map((g) => g.dataset.reportKind), ['database', 'schema', 'table', 'column']);
  assert.ok(groups.every((g) => !g.hasAttribute('open')), 'collapsed by default');
  assert.match(text(groups[2].querySelector('summary').innerHTML), /Capture Database Table Measurements · 2/);
});

test('a row is the element name (database prefix dropped) with its measured values', () => {
  const root = document.createElement('div'); root.innerHTML = m.reportViewerHtml(REP);
  const col = root.querySelector('[data-report-kind="column"]');
  const rows = [...col.querySelectorAll('[data-report-row]')].map((r) => text(r.innerHTML));
  assert.deepEqual(rows, ['s.t1.id varchar 43 yes – 5', 's.t1.name varchar 43 yes – 5', 's.t2.id varchar 43 yes – 5']);
  const tbl = [...root.querySelectorAll('[data-report-kind="table"] [data-report-row]')].map((r) => text(r.innerHTML));
  assert.equal(tbl[0], 's.t1 Table 2.0 KB 1 7 – –', 'size is humanised; a value the annotation does not carry is a dash, not 0');
  const heads = [...col.querySelectorAll('th')].map((t) => t.textContent);
  assert.deepEqual(heads, ['Element', 'Type', 'Size', 'Not null', 'Avg width', 'Distinct']);
});

test('the generic description shows once per group, on hover, never in a row', () => {
  const html = m.reportViewerHtml(REP);
  assert.equal(html.split('Capture summary statistics about a database column.').length - 1, 1);
  const root = document.createElement('div'); root.innerHTML = html;
  assert.equal(root.querySelector('[data-report-kind="column"] summary').getAttribute('title'), 'Capture summary statistics about a database column.');
  assert.doesNotMatch(text(root.querySelector('[data-report-kind="column"] tbody').innerHTML), /Capture summary/);
});

test('a large group is capped, with "show all N" that draws the rest', () => {
  const rep = { ...REP, annotations: Array.from({ length: 60 }, (_, i) => tableAnn(i + 1)) };
  const root = document.createElement('div'); root.innerHTML = m.reportViewerHtml(rep);
  m.bindReportViewer(root, rep);
  assert.equal(root.querySelectorAll('[data-report-row]').length, m.GROUP_CAP);
  const btn = root.querySelector('[data-report-show-all]');
  assert.match(btn.textContent, /show all 60/);
  btn.click();
  assert.equal(root.querySelectorAll('[data-report-row]').length, 60);
  assert.equal(root.querySelector('[data-report-show-all]'), null);
});

test('a stored row with no element name says so instead of inventing one', () => {
  const rep = { annotations: [{ annotation_type: TABLE, summary: 's', detail: { json_properties: '{"tableSize":1}' } }] };
  const html = m.reportViewerHtml(rep);
  assert.match(text(html), /1 of 1 stored annotations carry no element name/);
  assert.match(text(html), /no name stored/);
});

test('an empty report says so', () => {
  assert.match(text(m.reportViewerHtml({ annotations: [] })), /holds no annotations/);
});
