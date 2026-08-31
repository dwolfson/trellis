/** Content-scans the served static index.html for utility classes actually
 * used, since this app has no JS framework/template files to scan — it's
 * one static HTML file with inline <script>-built strings using Tailwind
 * classes (template literals count as plain text to Tailwind's scanner). */
module.exports = {
  darkMode: 'class',
  content: ['../resource_explorer/web/static/index.html'],
  theme: { extend: {} },
  // `prose`/`prose-invert` have been used throughout index.html (the chat
  // answer body, the packed-evidence text) since before this build existed,
  // with no plugin registered to give them effect — the exact silent-no-CI
  // failure this README already warns re-running build:css guards against,
  // just never caught because the classes render as nothing rather than an
  // error. Added 2026-08-31 once a user found the packed-evidence/answer
  // text genuinely unstyled (no heading hierarchy, no list markers).
  plugins: [require('@tailwindcss/typography')],
};
