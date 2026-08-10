/** Content-scans the served static index.html for utility classes actually
 * used, since this app has no JS framework/template files to scan — it's
 * one static HTML file with inline <script>-built strings using Tailwind
 * classes (template literals count as plain text to Tailwind's scanner). */
module.exports = {
  darkMode: 'class',
  content: ['../resource_explorer/web/static/index.html'],
  theme: { extend: {} },
  plugins: [],
};
