# Walk 3 — Catalog a database

*Screens read on 2026-10-29, Explorer on port 8813, `origin/main` at `afdac240`. Resource: `coco_pharma @ local-docker` (`localhost_docker_coco_pharma`).*

Open the database from the **DBs** list in the sidebar (use the filter box, then the row). Open it through the list rather than a saved address: on this build a direct address can show "not published" for a database that Egeria holds.

## 1. Describe and publish: header, credentials, findable

![The Curate stage, "Describe and publish" tab, for coco_pharma @ local-docker. The tab row reads "Describe and publish · Contents ✓ 4 chosen · ○ 25 undecided · Structure ○ none yet · Questions · Survey & analyses · By analysis · Disposition · Schema Inventory · Table preview". Under the title: "surveyed 5d ago · local survey · published to Egeria", "RE's own survey 10-24: connected as egeria_admin, sees 30 of 30 schemas, SELECT on 266 of 266 relations", and "credential change date not recorded · Change credentials…". Then the FINDABLE section with "RE group egeria-databases" and the tag "coco", and WHAT PEOPLE SAY with one rating.](images/03-database/03-curate-describe-and-publish.webp)

*"surveyed 5d ago · local survey · published to Egeria". "RE's own survey 10-24: connected as egeria_admin, sees 30 of 30 schemas, SELECT on 266 of 266 relations". Beside it: "credential change date not recorded · Change credentials…".*

The line that starts "RE's own survey" says what the connecting account can see. "Change credentials…" is where a person replaces them; this walk did not press it.

## 2. Contents: what gets published, and the chips

![The Contents tab for coco_pharma. "asset c990f349-36de-4489-9338-7974dec54cb0 copy", then "What gets published", the sentence "Database element c990f349 in Egeria · published 10-24 00:45 · zones: none · everyone visible · 4 schemas chosen · 4 schemas attached · cataloguer connector's last refresh 10-24 00:45 (the connector's, not a schema's)", and three chips: "published by RE 2 ✓", "attached 4 schemas ✓" and "cataloged by Egeria 0 schemas ○ not checked since 00:54". Below, "Your scope: 4 of 30 schemas known to RE · declared by erinoverview 10-05 · Egeria's latest survey covers 4 schemas, 55 tables".](images/03-database/03-curate-database-chips.webp)

*The chips read "published by RE 2 ✓", "attached 4 schemas ✓" and "cataloged by Egeria 0 schemas ○ not checked since 00:54".*

A chip is a statement about the last time RE read Egeria, not about Egeria now. The third chip reads "not checked since 00:54", so its "0 schemas" is what RE saw then. The sentence above the chips and the chips both give counts for the same facts ("4 schemas chosen · 4 schemas attached" and "attached 4 schemas ✓"); today they agree. The mark on the cue is ○ on this screen; the user guide writes ◌ for that cue. The sentence spells "cataloguer", while the chip says "cataloged".

## 3. Publish to Egeria

![The foot of the Describe and publish tab. The section "PUBLISH TO EGERIA" reads "◐ partly committed · 4 queued", then "Database element c990f349 in Egeria · Contents ›", then "Egeria reports", a Refresh button, "read 09:20 · 4 reports", and three report rows, each with "copy", "Show annotations" and "Ask about this →".](images/03-database/03-curate-publish-to-egeria.webp)

*"PUBLISH TO EGERIA ◐ partly committed · 4 queued". "Egeria reports · read 09:20 · 4 reports". Each row reads, for example, "Survey: coco_pharma @ local-docker · surveyed 5d ago · 1858 annotations".*

The publish table, the **Publish** press and what it sends are described in [the guide, section 6](../user-guide.md#6-publishing-to-egeria). This walk did not press **Publish**, **Refresh** or **Ask about this →**, and shows no press result.

**Not built yet in this walk:** nothing in the surfaces shown; see [the guide's list](../user-guide.md#10-not-built-yet).
