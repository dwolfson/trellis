/* The file system's folder survey card (Files step 2).
 *
 * One card, on the file system's survey pane:
 *
 *   - the probe's ONE sentence and its date ("Egeria can read <container path> · checked <date>" or "only Resource
 *     Explorer can read this path · checked <date>"), read from the stored probe rows, and who leads. "Not checked yet"
 *     and "could not tell" are their own states and are never drawn as either outcome;
 *   - the press: "Survey" runs the probe first, then the lead's survey. Egeria's Folder Survey is submitted (minutes; the
 *     native-survey row below follows its run); Resource Explorer's walk runs here and is stored;
 *   - the results, ONE shape for both leads: file types, counts, the inaccessible files, and (Resource Explorer's walk)
 *     the declared limits with "capped" said plainly. The surveyor is named on the results and on the report.
 *   - the price line BEFORE the press (Files F12): the last walk's files, bytes and time on this machine, capped or not,
 *     what was not walked and where the bulk sits; "not priced" until a walk has measured the tree;
 *   - "Derived from the walk" (Files build step 6): the Analytic Library steps over the kept per-file rows, each with its
 *     stored state and its own words; "not run yet" until one has run, "not installed" naming the package;
 *   - "Narrative files, read in full" (Files build step 7, F11's long form): the price before the press (the files the
 *     walk found, their bytes), then the run's counts; every passage is a proposal stated by its file;
 *   - "Personal or sensitive data" (Files build step 8, F7): data_class_match over the file profiles, what the press reads
 *     before it, then the run's counts and the proposals by file and column, with the names that suggest personal data.
 *
 * Every status here comes from a stored row the server read (the probe row, the run row, the walk's own limits), never
 * from which button was pressed. A number the survey did not carry is "–", never 0.
 */
import { esc } from '/static/next/app.js';
import { getFolderSurvey, runFolderSurvey, publishFolderSurvey, checkFilesystemReach, runWalkExtensions, publishWalkExtensions,
  runFileProfiles, readFileProfilesFromEgeria, publishFileProfiles, runFilesystemAnalysis, runNarrativeDocs, runClassMatch,
  pollActivity, activityFailure, failureText } from '/static/re-api.js';
import { enhanceTable } from '/static/next/colresize.js';
import { fmtBytes } from '/static/next/stages/native-report.js';

/** Placeholder words, in one table, for the designer. */
export const FOLDER_SURVEY_WORDS = {
  heading: 'Folder survey',
  press: 'Survey',
  pressing: 'Surveying…',
  check: 'Check again',
  checking: 'Checking…',
  publish: 'Publish this walk to Egeria',
  publishing: 'Publishing…',
  led: (who) => `led by ${who}`,
  noLead: 'no one can be named to lead yet',
  noSurvey: 'no folder survey yet',
  surveyedBy: (who, date) => `surveyed by ${who}${date ? ` · ${date}` : ''}`,
  capped: (why) => `capped${why ? ` (${why})` : ''} · not the whole tree`,
  complete: 'walked to the end of every folder it entered',
  published: (guid, landed) => `published${landed ? ` · ${landed}` : ''}${guid ? ` · report ${String(guid).slice(0, 8)}` : ''}`,
  notPublished: 'kept here · not published to Egeria',
  notPublishedWhy: (why) => `not published · ${why}`,
  pathChecked: (p) => `path checked: ${p}`,
  brokenLinks: (n) => `${n} broken link${n === 1 ? '' : 's'} (target gone) · counted, not walked`,
  egeriaList: "the names are in Egeria's own file · not read here",
  // Walk measures (Files build step 1): what Egeria's Folder Survey does not keep.
  measureBeside: "Measure beside Egeria's survey",
  measuringBeside: 'Measuring…',
  publishMeasures: 'Publish these measures to Egeria',
  measuresHeading: 'Walk measures',
  measuresBy: (date, led) => `measured by Resource Explorer${date ? ` · ${date}` : ''}${led === 'egeria' ? " · beside Egeria's Folder Survey" : ''}`,
  noMeasures: 'not measured yet',
  rowsKept: (n, runs) => `per-file rows kept · ${num(n)} files${runs > 1 ? ` · ${num(runs)} runs held` : ''}`,
  rowsNotKept: (why) => `per-file rows not kept${why ? ` · ${why}` : ''}`,
  hashesOff: 'hashing off · no content hash taken',
  hashed: (n, limit) => `${num(n)} files hashed (SHA-256) · files over ${fmtBytes(limit)} are not hashed`,
  notHashed: (over, secret, linked, unreadable) => [
    over ? `${num(over)} over the size limit` : '', secret ? `${num(secret)} with a secret-looking name` : '',
    linked ? `${num(linked)} linked` : '', unreadable ? `${num(unreadable)} unreadable` : ''].filter(Boolean).join(' · '),
  noNarratives: 'no README-type file found',
  narrativeLine: (file, when) => `described by ${file}${when ? ` · modified ${when}` : ''}`,
  proposal: 'a proposal · confirm it on Curate',
  // Data-file profiles (Files build step 5).
  profilesHeading: 'Data-file profiles',
  profilePress: 'Profile data files',
  profiling: 'Profiling…',
  readEgeria: "Read Egeria's reports",
  reading: 'Reading…',
  publishProfiles: 'Publish these profiles to Egeria',
  noProfiles: 'not profiled yet',
  profiledAt: (date) => `profiled${date ? ` · ${date}` : ''}`,
  sampled: 'sampled',
  submitted: (n) => `${num(n)} CSV file${n === 1 ? '' : 's'} submitted to Egeria's CSV Survey Service · its reports not read back yet`,
  notInstalled: (n) => `not installed · Egeria's CSV Survey Service is not installed where its engine host runs · ${num(n)} CSV file${n === 1 ? '' : 's'} not profiled`,
  egeriaUnchecked: (n) => `could not check whether Egeria's CSV Survey Service is installed · ${num(n)} CSV file${n === 1 ? '' : 's'} not profiled`,
  submitFailed: (n) => `${num(n)} CSV file${n === 1 ? '' : 's'} refused by Egeria`,
  fsNameUnknown: (n) => `the name Egeria uses for this file system could not be established · ${num(n)} CSV file${n === 1 ? '' : 's'} not read or created in Egeria`,
  otherStates: (c) => [c.over_limit ? `${num(c.over_limit)} over the limit in a format read only whole` : '',
    c.unreadable ? `${num(c.unreadable)} could not be parsed` : '',
    c.secret_name ? `${num(c.secret_name)} with a secret-looking name · not opened` : '',
    c.link_not_followed ? `${num(c.link_not_followed)} linked · not followed` : '',
    c.no_columns ? `${num(c.no_columns)} read back from Egeria with no column profile` : '',
    c.not_reachable ? `${num(c.not_reachable)} not reachable from here · the mount point could not be reached` : '',
    c.header_suspect ? `${num(c.header_suspect)} with a header that looks like data · those names not published` : ''].filter(Boolean).join(' · '),
  // Files build step 6: the derived steps, and F12's price line.
  derivedHeading: 'Derived from the walk',
  derivePress: 'Derive',
  deriving: 'Deriving…',
  notRun: 'not run yet',
  derivedAt: (date) => `derived${date ? ` · ${date}` : ''}`,
  notPriced: 'not priced',
  derivedKept: "kept here · sent to Egeria in the walk's own survey report when that walk is published",
  derivedPublished: (guid) => `in Egeria · report ${String(guid || '').slice(0, 8)}`,
  // Files build step 7: the narrative files read in full (F11's long form).
  narrativeHeading: 'Narrative files, read in full',
  narrativePress: 'Read narrative files',
  narrativeReading: 'Reading…',
  narrativeNotRead: 'not read yet',
  narrativeReadAt: (date) => `read${date ? ` · ${date}` : ''}`,
  narrativeStale: 'a newer walk found these files · read them again to bring the index up to date',
  // Files build step 8: data_class_match over the file profiles (F7).
  classHeading: 'Personal or sensitive data',
  classPress: 'Match data classes',
  classMatching: 'Matching…',
  classNotRun: 'not matched yet',
  classAt: (date) => `matched${date ? ` · ${date}` : ''}`,
  classStale: 'newer profiles exist · match again to bring this up to date',
  classNames: (n) => `${num(n)} file${n === 1 ? '' : 's'} whose name suggests personal data · on the name only`,
};

const dash = '–';
const num = (n) => (typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString('en-US') : dash);
const MONTHS = { Jan: '01', Feb: '02', Mar: '03', Apr: '04', May: '05', Jun: '06', Jul: '07', Aug: '08', Sep: '09', Oct: '10', Nov: '11', Dec: '12' };
/** The date part of a stored time: ISO ("2026-10-19T08:00:00") or Egeria's Java `Date.toString()` ("Mon Oct 19 08:00:00 UTC 2026"). */
export const day = (value) => {
  const text = String(value || '').trim();
  const java = /^[A-Za-z]{3} ([A-Za-z]{3}) (\d{1,2}) \d{1,2}:\d{2}:\d{2} \S+ (\d{4})$/.exec(text);
  if (java && MONTHS[java[1]]) return `${java[3]}-${MONTHS[java[1]]}-${java[2].padStart(2, '0')}`;
  return text.slice(0, 10);
};

/** The probe line: the sentence exactly as stored, a cue glyph for the state, and who leads. */
export function reachLineHtml(reach) {
  const r = reach || {};
  const glyph = { egeria: '✓', expected: '◔', mounts_unknown: '?', re_only: '✓', egeria_cannot: '⚠', nobody: '⚠', connection_broken: '⚠',
    undecided: '?', not_checked: '◔' }[r.state] || '◔';
  const lead = r.surveyor ? FOLDER_SURVEY_WORDS.led(r.surveyor) : FOLDER_SURVEY_WORDS.noLead;
  return `<div data-fs-reach data-reach-state="${esc(r.state || 'not_checked')}" class="text-caveat text-ink">
    <span class="font-glyph" aria-hidden="true">${glyph}</span> ${esc(r.sentence || 'not checked yet')}
    <span class="text-ink-muted"> · ${esc(lead)}</span>
    ${r.path ? `<div class="text-provenance text-ink-muted" data-fs-reach-path>${esc(FOLDER_SURVEY_WORDS.pathChecked(r.path))}</div>` : ''}
    ${r.why ? `<div class="text-provenance text-ink-muted" data-fs-reach-why>${esc(r.why)}</div>` : ''}
  </div>`;
}

const statRow = (label, value) =>
  `<div class="flex gap-s2 text-caveat"><span class="w-[16ch] shrink-0 text-ink-muted">${esc(label)}</span><span class="text-ink">${esc(value)}</span></div>`;

/** "12 directories not walked: .git, node_modules, .venv" (the names met and skipped), or "no directories skipped". */
export function notWalkedWords(limits) {
  const n = Number(limits.not_walked_directories || 0);
  const names = (limits.not_walked_names_found || []).join(', ');
  const linked = limits.symlinked_directories_not_followed
    ? `, ${num(limits.symlinked_directories_not_followed)} linked folders not followed` : '';
  if (!n) return `no directories skipped${linked}`;
  return `${num(n)} director${n === 1 ? 'y' : 'ies'} not walked${names ? `: ${names}` : ''}${linked}`;
}

function limitsHtml(limits) {
  if (!limits) return '';
  const cap = limits.capped
    ? `<div data-fs-capped class="text-caveat text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(FOLDER_SURVEY_WORDS.capped((limits.capped_reasons || []).join(', ')))}</div>`
    : `<div data-fs-not-capped class="text-provenance text-ink-muted">${esc(FOLDER_SURVEY_WORDS.complete)}</div>`;
  return `<div class="mt-s2" data-fs-limits>
    ${cap}
    <div class="text-provenance text-ink-muted">limits: depth ${num(limits.max_depth)}, entries ${num(limits.max_entries)}
      · examined ${num(limits.entries_examined)}, deepest level ${num(limits.deepest_level_reached)}</div>
    <div class="text-provenance text-ink-muted" data-fs-not-walked>${esc(notWalkedWords(limits))}</div>
    ${limits.broken_symlink_count ? `<div class="text-provenance text-ink-muted" data-fs-broken-links>${esc(FOLDER_SURVEY_WORDS.brokenLinks(limits.broken_symlink_count))}</div>` : ''}
  </div>`;
}

function inaccessibleHtml(inacc) {
  if (!inacc || inacc.count == null) return statRow('Inaccessible', dash);
  const list = Array.isArray(inacc.listed) ? inacc.listed : null;
  return `<div data-fs-inaccessible>${statRow('Inaccessible', num(inacc.count))}${
    inacc.count && list
      ? `<div class="ml-[16ch] text-provenance text-ink-muted">${list.slice(0, 20).map(esc).join('<br>')}${
        list.length > 20 ? `<br>and ${num(list.length - 20)} more` : ''}</div>`
      : inacc.count ? `<div class="ml-[16ch] text-provenance text-ink-muted">${esc(FOLDER_SURVEY_WORDS.egeriaList)}</div>` : ''}</div>`;
}

const typeRows = (title, rows) => (rows && rows.length
  ? `<div class="mt-s2" data-fs-profile="${esc(title)}"><div class="text-caps uppercase tracking-caps text-ink-muted">${esc(title)}</div>
      ${rows.slice(0, 12).map((r) => `<div class="flex gap-s2 text-caveat"><span class="w-[28ch] shrink-0 truncate text-ink" title="${esc(r.name)}">${esc(r.name)}</span><span class="text-ink-muted">${num(r.count)}</span></div>`).join('')}
      ${rows.length > 12 ? `<div class="text-provenance text-ink-muted">and ${num(rows.length - 12)} more</div>` : ''}</div>`
  : '');

/** A publish read back before the latest Egeria reset (the server's `pre_reset` {at, words}): the ◌ lane with the
 *  server's words "published before the <date> reset · not in Egeria now", never "published" (fix round 1). */
function preResetHtml(claim) {
  return `<span data-fs-pre-reset class="font-glyph" aria-hidden="true" title="${esc(`Egeria reset ${claim.at || ''}`)}">◌</span> ${esc(claim.words || 'not in Egeria now')}`;
}

/** Published means what landed, read back: "published · N of M annotations in Egeria", else "not published · why". An
 *  Egeria-led survey is Egeria's own report. Returns HTML (escaped here). */
function publishWords(v) {
  const W = FOLDER_SURVEY_WORDS;
  const pre = v.pre_reset || (v.publish && v.publish.pre_reset);
  if (pre) return preResetHtml(pre);
  if (v.surveyor === "Egeria's Folder Survey") return esc(W.published(v.report_guid, ''));
  return esc(publishWordsRe(v));
}

function publishWordsRe(v) {
  const W = FOLDER_SURVEY_WORDS;
  const p = v.publish;
  if (!p) return W.notPublished;
  return p.published ? W.published(v.report_guid, p.landed_words) : W.notPublishedWhy(p.not_published_why || 'unknown');
}

/** The results, one shape for both leads. */
export function folderResultsHtml(view) {
  const v = view || {};
  if (v.state !== 'measured') {
    return `<div data-fs-results data-fs-state="none" class="mt-s2 text-caveat text-ink-muted">${esc(FOLDER_SURVEY_WORDS.noSurvey)}</div>`;
  }
  const r = v.results || {};
  const c = r.counts || {};
  const t = r.times || {};
  return `<div data-fs-results data-fs-state="measured" data-fs-surveyor="${esc(v.surveyor)}" class="mt-s2">
    <div data-fs-surveyed-by class="text-caveat text-ink">${esc(FOLDER_SURVEY_WORDS.surveyedBy(v.surveyor, day(v.surveyed_at)))}
      <span class="text-ink-muted"> · ${esc(v.report_sentence || '')}</span></div>
    <div class="text-provenance text-ink-muted" data-fs-published>${publishWords(v)}</div>
    ${(v.detail_lines || []).map((l) => `<div class="text-provenance text-ink-muted" data-fs-detail>${esc(l)}</div>`).join('')}
    ${limitsHtml(v.limits)}
    ${(v.broken_symlinks || []).length ? `<div class="text-provenance text-ink-muted" data-fs-broken-list>${
      v.broken_symlinks.slice(0, 20).map(esc).join('<br>')}${v.broken_symlinks.length > 20 ? `<br>and ${num(v.broken_symlinks.length - 20)} more` : ''}</div>` : ''}
    <div class="mt-s2">
      ${statRow('Files', num(c.files))}
      ${statRow('Folders', num(c.subdirectories))}
      ${statRow('Total size', c.total_size_bytes == null ? dash : fmtBytes(c.total_size_bytes))}
      ${statRow('File types', num(c.file_types))}
      ${statRow('Unclassified', num(c.unclassified))}
      ${statRow('Last modified', t.last_modified ? day(t.last_modified) : dash)}
      ${inaccessibleHtml(r.inaccessible)}
    </div>
    ${typeRows('File types', r.file_types)}
    ${typeRows('File extensions', r.extensions)}
  </div>`;
}

const th = (t) => `<th scope="col" class="px-2 py-[2px] text-left font-normal text-ink-muted">${esc(t)}</th>`;
const tdText = (t) => `<td class="max-w-[48ch] truncate px-2 py-[2px] text-ink" title="${esc(t)}">${esc(t)}</td>`;
const tdNum = (t) => `<td class="px-2 py-[2px] text-right text-ink">${esc(t)}</td>`;

/** A small data table: a real `<table>` with a header row, so its columns resize (colresize.js) and a long cell scrolls or
 *  truncates inside its own box rather than overrunning at the largest text. */
export function measureTableHtml(id, title, headers, rows) {
  return `<div class="mt-s2" data-fs-measure-table="${esc(id)}">
    <div class="text-caps uppercase tracking-caps text-ink-muted">${esc(title)}</div>
    <div class="max-w-full overflow-x-auto">
      <table data-rc-id="fs-measure-${esc(id)}" class="w-full border-collapse text-caveat">
        <thead><tr>${headers.map(th).join('')}</tr></thead>
        <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i === 0 ? tdText(c) : tdNum(c))).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>
  </div>`;
}

/** The walk's extensions (Files build step 1): bulk and depth per folder, owner and mode, hashes, noise directories, and each
 *  folder's own narrative as a proposal. What it says about the rows and about publishing comes from the view's stored proof. */
export function walkMeasuresHtml(ext) {
  const W = FOLDER_SURVEY_WORDS;
  if (!ext) return `<div data-fs-measures data-fs-measures-state="none" class="mt-s3 text-caveat text-ink-muted">${esc(W.measuresHeading)} · ${esc(W.noMeasures)}</div>`;
  const f = ext.folders || {};
  const h = ext.hashing || {};
  const o = ext.owners || {};
  const rows = ext.rows || {};
  const capped = ext.capped_words
    ? `<div data-fs-measures-capped class="text-caveat text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(ext.capped_words)} · not the whole tree</div>`
    : `<div data-fs-measures-not-capped class="text-provenance text-ink-muted">${esc(W.complete)}</div>`;
  const pub = ext.publish && ext.publish.pre_reset
    ? preResetHtml(ext.publish.pre_reset)
    : esc(ext.publish
      ? (ext.publish.published ? W.published(ext.report_guid, ext.publish.landed_words) : W.notPublishedWhy(ext.publish.not_published_why || 'unknown'))
      : W.notPublished);
  const notWalked = Object.entries(ext.not_walked_by_name || {}).map(([n, c]) => `${n} ×${num(c)}`).join(', ');
  const modes = Object.entries(ext.modes || {}).slice(0, 8).map(([m, c]) => `${m} ×${num(c)}`).join(', ');
  const notHashed = W.notHashed(h.over_limit_files, h.secret_named_files, h.symlink_files, h.unreadable_files);
  const narr = ext.narratives || [];
  const ns = ext.narratives_summary || {};
  return `<div data-fs-measures data-fs-measures-state="measured" data-fs-measures-led="${esc(ext.led_by)}" class="mt-s3">
    <div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.measuresHeading)}</div>
    <div class="text-caveat text-ink" data-fs-measures-by>${esc(W.measuresBy(day(ext.surveyed_at), ext.led_by))}
      <span class="text-ink-muted"> · ${esc(ext.report_sentence || '')}</span></div>
    ${capped}
    <div class="text-provenance ${rows.kept ? 'text-ink-muted' : 'text-state-warn'}" data-fs-measures-rows data-fs-rows-kept="${rows.kept ? 'yes' : 'no'}">${esc(rows.kept ? W.rowsKept(rows.files, rows.runs_kept) : W.rowsNotKept(rows.error))}</div>
    <div class="text-provenance text-ink-muted" data-fs-measures-published>${pub}</div>
    <div class="mt-s2">
      ${statRow('Deepest level', num(f.deepest_folder_depth))}
      ${statRow('Folders with files', num(f.folders_with_files))}
      ${statRow('Owners', num(o.distinct_owners))}
      ${statRow('Groups', num(o.distinct_groups))}
      ${statRow('World-readable', num(o.world_readable_files))}
      ${statRow('Modes', modes || dash)}
      ${statRow('Not walked', notWalked || 'none')}
    </div>
    ${h.budget_words ? `<div data-fs-measures-hash-budget class="text-caveat text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(h.budget_words)}</div>` : ''}
    <div class="text-provenance text-ink-muted" data-fs-measures-hash>${esc(h.off ? W.hashesOff : W.hashed(h.hashed_files, h.limit_bytes))}${notHashed ? ` · ${esc(notHashed)}` : ''}</div>
    ${(f.largest_folders || []).length ? measureTableHtml('largest', 'Heaviest folders', ['Folder', 'Depth', 'Files', 'Size'],
      f.largest_folders.map((x) => [x.path, num(x.depth), num(x.files), fmtBytes(x.bytes)])) : ''}
    ${(f.depth_histogram || []).length ? measureTableHtml('depths', 'By depth', ['Depth', 'Folders', 'Files', 'Size'],
      f.depth_histogram.map((x) => [String(x.depth), num(x.folders), num(x.files), fmtBytes(x.bytes)])) : ''}
    <div class="mt-s2" data-fs-narratives>
      <div class="text-caps uppercase tracking-caps text-ink-muted">Folders that describe themselves</div>
      ${narr.length ? narr.map((n) => `<div class="mb-[2px] text-caveat" data-fs-narrative>
        <span class="break-words text-ink">${esc(n.folder || '(root)')}</span>
        <span class="text-ink-muted" title="${esc(n.file || '')}"> · ${esc(W.narrativeLine(n.stated_by, day(n.modified_at)))}${n.licence ? ` · licence ${esc(n.licence)}` : ''}</span>
        <div class="break-words text-provenance text-ink-muted">${esc(n.title || '')}${n.description ? ` · ${esc(n.description)}` : ''} · ${esc(W.proposal)}</div></div>`).join('')
      : `<div class="text-provenance text-ink-muted">${esc(W.noNarratives)}</div>`}
      ${ext.narratives_not_shown ? `<div class="text-provenance text-ink-muted">and ${num(ext.narratives_not_shown)} more</div>` : ''}
      ${ns.stopped_at_read_cap ? `<div class="text-provenance text-state-warn">stopped after ${num(ns.read_cap)} files read · not every folder was looked at</div>` : ''}
    </div>
  </div>`;
}

const STATE_WORDS = {
  measured: 'profiled', sampled: 'profiled · sampled', not_applicable: 'not read · format', not_permitted: 'not permitted',
  over_limit: 'over the limit · not read', unreadable: 'could not be parsed', secret_name: 'secret-looking name · not opened',
  link_not_followed: 'linked · not followed', not_installed: 'not installed', egeria_unchecked: 'could not check Egeria',
  submit_failed: 'refused by Egeria', submitted: "submitted to Egeria", no_columns: 'no column profile in Egeria\'s report',
  not_reachable: 'not reachable from here', header_suspect: 'profiled · header looks like data',
  file_system_name_unknown: "file system's name in Egeria not known",
};
const sourceWords = (s) => (String(s || '').startsWith('egeria:') ? `Egeria · report ${String(s).slice(7, 15)}` : s === 'resource-explorer' ? 'RE' : '');

/** The data-file profiles (Files build step 5): the cost line BEFORE the press, then the run's counts, each from stored rows. */
export function fileProfilesHtml(fp) {
  const W = FOLDER_SURVEY_WORDS;
  if (!fp) return '';
  if (fp.error) return `<div data-fp data-fp-state="error" class="mt-s3 text-provenance text-state-warn">${esc(fp.error)}</div>`;
  const price = fp.price || {};
  const run = fp.run;
  const head = `<div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.profilesHeading)}</div>
    <div data-fp-price class="text-caveat text-ink">${esc(price.words || '')}</div>`;
  if (!run) return `<div data-fp data-fp-state="none" class="mt-s3">${head}<div class="text-provenance text-ink-muted">${esc(W.noProfiles)}</div></div>`;
  const c = run.counts || {};
  const egeriaLines = [c.submitted ? W.submitted(c.submitted) : '', c.not_installed ? W.notInstalled(c.not_installed) : '',
    c.egeria_unchecked ? W.egeriaUnchecked(c.egeria_unchecked) : '', c.submit_failed ? W.submitFailed(c.submit_failed) : '',
    c.file_system_name_unknown ? W.fsNameUnknown(c.file_system_name_unknown) : '']
    .filter(Boolean);
  const other = W.otherStates(c);
  const pub = run.publish && run.publish.pre_reset
    ? preResetHtml(run.publish.pre_reset)
    : esc(run.publish
      ? W.published(run.publish.report_guid, run.publish.annotations_in_egeria != null ? `${num(run.publish.annotations_in_egeria)} of ${num(run.publish.annotation_count)} annotations in Egeria` : '')
      : W.notPublished);
  const rows = (run.files || []).map((f) => [f.file_path, STATE_WORDS[f.state] ? `${STATE_WORDS[f.state]}${f.state === 'not_applicable' ? ` ${f.format || '(none)'}` : ''}` : f.state,
    sourceWords(f.stats_source), f.columns ? num(f.columns) : dash,
    f.sample_ratio != null && f.sample_ratio < 1 ? `${W.sampled} ${(f.sample_ratio * 100).toFixed(1)}%` : '']);
  return `<div data-fp data-fp-state="profiled" class="mt-s3">${head}
    <div data-fp-run class="text-caveat text-ink">${esc(W.profiledAt(day(run.run_id)))} · <span data-fp-words>${esc(run.words || '')}</span></div>
    ${egeriaLines.map((l) => `<div data-fp-egeria class="text-provenance text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(l)}</div>`).join('')}
    ${other ? `<div data-fp-other class="text-provenance text-ink-muted">${esc(other)}</div>` : ''}
    <div data-fp-published class="text-provenance text-ink-muted">${pub}</div>
    ${rows.length ? measureTableHtml('profiles', 'Files', ['File', 'State', 'Source', 'Columns', 'Sampled'], rows) : ''}
    ${run.files_not_shown ? `<div class="text-provenance text-ink-muted">and ${num(run.files_not_shown)} more</div>` : ''}
  </div>`;
}

/** F12: the price line, shown before the Survey press. The server's words, from the stored walk; never a guessed number. */
export function priceLineHtml(price) {
  if (!price) return '';
  return `<div data-fs-price data-fs-priced="${price.priced ? 'yes' : 'no'}" class="mt-[2px] text-caveat text-ink-muted">${esc(price.words || FOLDER_SURVEY_WORDS.notPriced)}</div>`;
}

const STEP_GLYPH = { measured: '●', nothing_found: '○', not_established: '◌', not_applicable: '–' };

/** Files build step 6: the derived steps' stored results, each in the step's own words (state words, summary, and the
 *  reason when it could not measure). A step never run is "not run yet"; an uninstalled one names its package. */
export function derivedHtml(derived) {
  const W = FOLDER_SURVEY_WORDS;
  if (!derived) return '';
  if (derived.error) return `<div data-fs-derived data-fs-derived-state="error" class="mt-s3 text-provenance text-state-warn">${esc(derived.error)}</div>`;
  const steps = derived.steps || [];
  if (!steps.length) return '';
  const rows = steps.map((s) => {
    const head = `<span class="font-medium text-ink">${esc(s.name)}</span>`;
    if (!s.installed) {
      return `<li data-fs-step="${esc(s.step)}" data-fs-step-state="not_installed" class="text-provenance">${head} · <span class="text-state-warn">${esc(s.missing_reason)}</span></li>`;
    }
    if (!s.run) {
      return `<li data-fs-step="${esc(s.step)}" data-fs-step-state="not_run" class="text-provenance">${head} · <span class="text-ink-muted">${esc(W.notRun)}</span></li>`;
    }
    const results = (s.results || []).map((r) => {
      const absent = r.state === 'not_established' || r.state === 'not_applicable';
      return `<div data-fs-result="${esc(r.measure)}" data-fs-result-state="${esc(r.state || 'no_envelope')}" class="ml-s3">
        <span class="font-glyph" aria-hidden="true">${STEP_GLYPH[r.state] || '?'}</span> ${esc(r.state_words || '')} · ${esc(r.summary)}${r.published ? ` <span data-fs-result-published class="text-ink-muted">· ${esc(W.derivedPublished(r.published.report_guid))}</span>` : ''}
        ${absent && r.reason ? `<div class="ml-s3 text-ink-muted">${esc(r.reason)}</div>` : ''}</div>`;
    }).join('');
    return `<li data-fs-step="${esc(s.step)}" data-fs-step-state="run" class="text-provenance">${head} · <span class="text-ink-muted">${esc(W.derivedAt(day(s.run)))}</span>${results}</li>`;
  }).join('');
  return `<div data-fs-derived class="mt-s3">
    <div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.derivedHeading)}</div>
    <div class="text-provenance text-ink-muted">${esc(W.derivedKept)}</div>
    <ul class="m-0 list-none p-0">${rows}</ul>
  </div>`;
}

/** Files build step 7: the narrative files read in full. The price BEFORE the press, then the stored run's own words. */
export function narrativeDocsHtml(nd) {
  const W = FOLDER_SURVEY_WORDS;
  if (!nd) return '';
  if (nd.error) return `<div data-fs-narr data-fs-narr-state="error" class="mt-s3 text-provenance text-state-warn">${esc(nd.error)}</div>`;
  const price = nd.price || {};
  const head = `<div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.narrativeHeading)}</div>
    <div data-fs-narr-price data-fs-narr-priced="${price.priced ? 'yes' : 'no'}" class="text-caveat text-ink">${esc(price.words || W.notPriced)}</div>`;
  const run = nd.run;
  if (!run) return `<div data-fs-narr data-fs-narr-state="none" class="mt-s3">${head}<div class="text-provenance text-ink-muted">${esc(W.narrativeNotRead)}</div></div>`;
  return `<div data-fs-narr data-fs-narr-state="read" class="mt-s3">${head}
    <div data-fs-narr-run class="text-caveat text-ink">${esc(W.narrativeReadAt(day(run.ran_at)))} · <span data-fs-narr-words>${esc(run.words || '')}</span></div>
    ${run.stale ? `<div data-fs-narr-stale class="text-provenance text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(W.narrativeStale)}</div>` : ''}
    <div class="text-provenance text-ink-muted">${esc(run.stated || '')}</div>
    <div class="text-provenance text-ink-muted">${esc(nd.kept || '')}</div>
  </div>`;
}

const VERDICT_WORDS = { matched: 'matches', partial_match: 'partly matches', unmatched_patterned: 'a pattern no class has · proposal',
  no_match: 'no class matched', inconclusive: 'inconclusive', not_sampled: 'not sampled', no_candidates: 'not compared',
  not_applicable: 'not applicable' };

/** Files build step 8: the data-class match over the file profiles. What the press reads BEFORE it, then the stored run's
 *  words, the proposals worth a person's look (privacy-relevant, established, or a pattern no class has), and the names. */
export function classMatchHtml(cm) {
  const W = FOLDER_SURVEY_WORDS;
  if (!cm) return '';
  if (cm.error) return `<div data-fs-class data-fs-class-state="error" class="mt-s3 text-provenance text-state-warn">${esc(cm.error)}</div>`;
  const price = cm.price || {};
  const head = `<div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.classHeading)}</div>
    <div data-fs-class-price data-fs-class-priced="${price.priced ? 'yes' : 'no'}" class="text-caveat text-ink">${esc(price.words || W.notPriced)}</div>`;
  const run = cm.run;
  if (!run) return `<div data-fs-class data-fs-class-state="none" class="mt-s3">${head}<div class="text-provenance text-ink-muted">${esc(W.classNotRun)}</div></div>`;
  const shown = (run.matches || []).filter((m) => m.established || m.verdict === 'unmatched_patterned');
  const rows = shown.map((m) => [m.file_path, m.header_suspect ? '(header looks like data)' : m.column,
    VERDICT_WORDS[m.verdict] || m.verdict, m.matched_display_name || (m.detected_patterns || []).join(', ') || dash,
    m.privacy_relevant ? 'yes' : '', m.statement]);
  const names = (run.name_signals || []).map((n) => [n.file_path, (n.words || []).join(', ')]);
  const notOpened = (run.file_outcomes || {}).egeria_profiled;
  return `<div data-fs-class data-fs-class-state="matched" class="mt-s3">${head}
    <div data-fs-class-run class="text-caveat text-ink">${esc(W.classAt(day(run.ran_at)))} · <span data-fs-class-words>${esc(run.words || '')}</span></div>
    ${run.stale ? `<div data-fs-class-stale class="text-provenance text-state-warn"><span class="font-glyph" aria-hidden="true">⚠</span> ${esc(W.classStale)}</div>` : ''}
    ${notOpened ? `<div data-fs-class-egeria class="text-provenance text-ink-muted">${esc(`${num(notOpened)} file${notOpened === 1 ? '' : 's'} profiled by Egeria · not opened here, so not sampled`)}</div>` : ''}
    <div class="text-provenance text-ink-muted">${esc(run.rule || '')}</div>
    ${rows.length ? measureTableHtml('class-match', 'Proposals', ['File', 'Column', 'Verdict', 'Class or pattern', 'Privacy', 'Statement'], rows) : ''}
    ${names.length ? `<div data-fs-class-names class="text-provenance text-ink">${esc(W.classNames(run.name_signal_files))}</div>
      ${measureTableHtml('class-names', 'Names', ['File', 'Words'], names)}` : ''}
  </div>`;
}

/** The whole card. `busy` is 'survey' | 'check' | 'publish' | 'measure' | 'publish-measures' | 'profile' | 'read-egeria' |
 *  'publish-profiles' | 'derive' | 'read-narratives' | 'match-classes' | ''. */
export function folderSurveyCardHtml(view, { busy = '', error = '' } = {}) {
  const W = FOLDER_SURVEY_WORDS;
  const reach = (view && view.reach) || {};
  const canSurvey = !!reach.surveyor;     // a state that names who leads (Egeria expected or verified; RE-led)
  const needsPublish = view && view.state === 'measured' && view.surveyor && !view.published
    && view.surveyor !== "Egeria's Folder Survey" && reach.surveyor === 'Resource Explorer';
  // Egeria's Folder Survey leads: Resource Explorer's own walk measures what that survey does not keep, beside it.
  const besideEgeria = reach.surveyor === "Egeria's Folder Survey";
  const ext = view && view.extensions;
  const needsPublishMeasures = !!(ext && ext.led_by === 'egeria' && !ext.published && ext.rows && ext.rows.kept);
  const fp = view && view.file_profiles;
  const fpRun = fp && fp.run;
  const btn = (act, label, on) => `<button type="button" data-fs-act="${act}" ${on ? '' : 'disabled'}
    class="shrink-0 cursor-pointer rounded-sm border ${on ? 'border-accent text-accent-ink' : 'border-rule-strong text-ink-muted'} bg-transparent px-2 py-[2px] text-caveat disabled:cursor-default">${esc(label)}</button>`;
  return `<div id="fs-folder-survey" class="mt-s3 mb-s3" data-fs-card>
    <div class="text-caps uppercase tracking-caps text-ink-muted">${esc(W.heading)}</div>
    <div class="mt-[2px] flex flex-wrap items-baseline gap-s2">
      ${reachLineHtml(reach)}
      ${btn('check', busy === 'check' ? W.checking : W.check, !busy)}
      ${btn('survey', busy === 'survey' ? W.pressing : W.press, !busy && canSurvey)}
      ${needsPublish ? btn('publish', busy === 'publish' ? W.publishing : W.publish, !busy) : ''}
      ${besideEgeria ? btn('measure', busy === 'measure' ? W.measuringBeside : W.measureBeside, !busy) : ''}
      ${needsPublishMeasures ? btn('publish-measures', busy === 'publish-measures' ? W.publishing : W.publishMeasures, !busy) : ''}
      ${fp && fp.price && fp.price.walk ? btn('profile', busy === 'profile' ? W.profiling : W.profilePress, !busy) : ''}
      ${fpRun && fpRun.counts && fpRun.counts.submitted ? btn('read-egeria', busy === 'read-egeria' ? W.reading : W.readEgeria, !busy) : ''}
      ${fpRun && !(fpRun.publish && fpRun.publish.complete) && fpRun.counts && fpRun.counts.by_re ? btn('publish-profiles', busy === 'publish-profiles' ? W.publishing : W.publishProfiles, !busy) : ''}
      ${derivable(view).length ? btn('derive', busy === 'derive' ? W.deriving : W.derivePress, !busy) : ''}
      ${view && view.narrative_docs && view.narrative_docs.price && view.narrative_docs.price.files ? btn('read-narratives', busy === 'read-narratives' ? W.narrativeReading : W.narrativePress, !busy) : ''}
      ${view && view.class_match && view.class_match.price && view.class_match.price.columns ? btn('match-classes', busy === 'match-classes' ? W.classMatching : W.classPress, !busy) : ''}
    </div>
    ${priceLineHtml(view && view.price)}
    ${error ? `<div data-fs-error class="mt-[2px] text-provenance text-state-warn">${esc(error)}</div>` : ''}
    ${folderResultsHtml(view)}
    ${walkMeasuresHtml(view && view.extensions)}
    ${narrativeDocsHtml(view && view.narrative_docs)}
    ${fileProfilesHtml(view && view.file_profiles)}
    ${classMatchHtml(view && view.class_match)}
    ${derivedHtml(view && view.derived)}
  </div>`;
}

/** The installed derived steps, by analysis id: what the Derive press runs. Only once a walk has kept rows to read. */
function derivable(view) {
  const ext = view && view.extensions;
  if (!(ext && ext.rows && ext.rows.kept)) return [];
  return ((view.derived && view.derived.steps) || []).filter((s) => s.installed).map((s) => s.analysis_id);
}

/** Mount the card into `host` and wire its presses. `onChange` runs after a press changed what the pane shows (the
 *  native-survey row below follows an Egeria-led run). Returns the repaint function. */
export async function mountFolderSurvey(host, slug, { onChange = () => {} } = {}) {
  if (!host) return () => {};
  let view = null;
  let error = '';
  const paint = (busy = '') => {
    host.innerHTML = folderSurveyCardHtml(view, { busy, error });
    host.querySelectorAll('[data-fs-act]').forEach((b) => b.addEventListener('click', () => press(b.dataset.fsAct)));
    host.querySelectorAll('table[data-rc-id]').forEach((t) => enhanceTable(t));     // every /next data table resizes (colresize.js)
  };
  // A successful re-read keeps the press's own error: it is cleared when the next press starts, never by the read
  // that follows a failed press (which used to wipe every press's failure before it was painted).
  const read = async () => {
    try { view = await getFolderSurvey(slug); } catch (e) { error = `could not read the folder survey: ${e.message}`; }
  };
  const press = async (act) => {
    error = '';
    paint(act);
    try {
      if (act === 'check') await checkFilesystemReach(slug);
      else if (act === 'survey') await runFolderSurvey(slug, { publish: false });
      else if (act === 'publish') await publishFolderSurvey(slug);
      else if (act === 'measure') await runWalkExtensions(slug, { publish: false });
      else if (act === 'publish-measures') await publishWalkExtensions(slug);
      else if (act === 'profile') await runFileProfiles(slug);
      else if (act === 'read-egeria') await readFileProfilesFromEgeria(slug);
      else if (act === 'publish-profiles') await publishFileProfiles(slug);
      else if (act === 'read-narratives') await runNarrativeDocs(slug);
      else if (act === 'match-classes') await runClassMatch(slug);
      else if (act === 'derive') {
        // Each step is queued and polled to its end; a failed one is said with its own reason, the others still run.
        const failed = [];
        for (const id of derivable(view)) {
          const started = await runFilesystemAnalysis(slug, id);
          const f = activityFailure(await pollActivity(started.activity_id, { intervalMs: 500 }));
          if (f) failed.push(`${id}: ${failureText(f)}`);
        }
        if (failed.length) error = failed.join(' · ');
      }
    } catch (e) {
      error = e.message || String(e);
    }
    await read();
    paint('');
    onChange(act);
  };
  await read();
  paint('');
  return () => paint('');
}
