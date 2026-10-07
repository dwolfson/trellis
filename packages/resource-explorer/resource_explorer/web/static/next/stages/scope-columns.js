/* Column specs for the Curate scope page's two tables (see colresize.js for the spec shape).
 * Kept free of imports so a plain page can load them: the real-browser layout checks do. */

/* The scope tree. Defaults in px; "Schema / table" is a fixed-width column like the rest. */
export const SCOPE_COLS = {
  id: 'curate-scope-tree', chrome: 80,
  columns: [
    { key: 'sel', def: 24, min: 24, resizable: false },
    { key: 'choice', def: 200, min: 90 },
    { key: 'name', def: 280, min: 120, align: 'left' },
    { key: 'rows', def: 84, min: 48 },
    { key: 'size', def: 84, min: 48 },
    { key: 'act', def: 150, min: 70 },
    { key: 'cls', def: 150, min: 70 },
    { key: 'egeria', def: 240, min: 90 },
  ],
};

/* "What this commit does": row label (left), what, how many, when. Fixed px, never ch: a ch is
 * the width of a zero in the cell's own font, so a header in a smaller type than its cells sat
 * at a different left edge from them. */
export const MANIFEST_COLS = {
  id: 'curate-commit-manifest', chrome: 30,
  columns: [
    { key: 'who', def: 130, min: 70, align: 'left' },
    { key: 'what', def: 200, min: 80 },
    { key: 'many', def: 230, min: 80 },
    { key: 'when', def: 200, min: 80 },
  ],
};
