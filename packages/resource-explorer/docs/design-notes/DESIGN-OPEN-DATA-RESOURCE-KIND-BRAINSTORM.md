# DESIGN — An external and open data resource kind: questions and surveys (brainstorm, 2026-10-20)

From the design session at the owner's request ("we should start to
brainstorm about an external data/open data resource type and questions
and surveys for that"). A brainstorm, not a decision; the open-data row
in `PLAN-OPEN-FRONTS-2026-10-14.md` §2.6 is its origin.

## 1. What the kind is

An **external data resource**: data someone else publishes, that we may
want to use, cite or redistribute, and that we do not host. Three shapes
share one kind, with a `source_kind` facet:

| Shape | Examples | What a survey reads |
|---|---|---|
| Open data portal dataset | data.gov, EU data portal, a city's CKAN or Socrata, Eurostat, World Bank | the portal's catalogue API (CKAN package, DCAT, Socrata metadata), then the distributions (CSV, JSON, Parquet, API) |
| Published dataset with a landing page | Kaggle, Zenodo, Hugging Face datasets, a university's repository | DCAT or schema.org/Dataset markup, a README, a data card, the files |
| Open model | Hugging Face model, a vendor's model page | the model card (base model, licence, training data named, evaluation, intended use), the weights' size and format |

Most of what matters is **metadata someone else wrote**: licence,
publisher, update cadence, coverage in time and place, provenance.
RE's job is to read it as evidence, keep it with its source and date,
measure what can be measured from the files, and publish the whole as an
Egeria asset whose provenance says it is external.

## 2. Why it is a different kind, not a file system with a URL

- The authoritative description lives outside RE and changes without
  notice: the survey must store the portal's metadata with a retrieved-at
  and compare on the next run (what changed on their side).
- Licence and terms decide everything downstream (can we redistribute,
  must we attribute, is commercial use allowed); they are the first
  question, not the twelfth.
- The data may be large or an API only; "survey" often means "profile a
  sample through the API", with the sample size stated.
- The same dataset may exist on several portals (harvested copies); the
  identity is the publisher's identifier (a DOI, a DCAT identifier), not
  the URL.
- A model is not tabular; its "schema" is its card.

## 3. Questions (proposed; the catalog assigns ids)

| # | Question | Stage | Answered by |
|---|---|---|---|
| O1 | Who publishes this, under what licence and terms, and may we use, modify and redistribute it? | Scouting | `external_metadata` (licence id against SPDX and the open-data licence list, attribution and share-alike flags, terms link), with the sentence of the licence quoted |
| O2 | What is it, in the publisher's words: title, description, keywords, themes? | Scouting | `external_metadata` |
| O3 | When was it last updated, how often is it updated, and is it still maintained? | Scouting | `external_metadata` (modified, accrual periodicity, issued) plus `external_change` on the second run |
| O4 | What does it cover: time period, geography, population, grain? | Discovery | `external_metadata` (DCAT temporal and spatial) confirmed by `external_profile` (min and max of date and location columns in the sample) |
| O5 | In what formats and through which access methods is it available, and are they open formats? | Discovery | `external_distributions` (format, size, API versus download, open-format flag) |
| O6 | What is the structure: files, columns, types, and a data dictionary if one is published? | Discovery | `external_profile` (sample profile) plus the dictionary file when linked |
| O7 | How large is it, and what would it cost to fetch, store and refresh? | Discovery | `external_distributions` sizes plus the cost line |
| O8 | How good is it: completeness, nulls, duplicates, consistency with the dictionary, on a stated sample? | Analysis | `external_profile` with the sample size on every number |
| O9 | Does it contain personal data, and what does the publisher say about it? | Analysis | `data_class_match` over the sample plus the publisher's statement, kept apart |
| O10 | Where does it come from: provenance, lineage the publisher states, and which other portals carry the same dataset? | Analysis | `external_provenance` (DCAT prov, DOI, harvested-from, duplicates by identifier across registered portals) |
| O11 | Is it the same as, or a version of, data we already hold? | Analysis | the fingerprint analysis against registered databases and file systems |
| O12 | Who else uses it, and how is it cited? | Analysis | citations where the publisher exposes them (DOI metadata), else "not reported by this source" |
| O13 | What changed since we last looked, on their side? | Discovery | `external_change` (metadata diff, distribution diff, size and modified diff) |
| M1 | For a model: base model, size, licence, training data named, intended and out-of-scope uses, evaluation results, as the card states them | Scouting | `model_card` (the card's fields, each with "stated by the publisher") |
| M2 | For a model: can we run it, at what size, and under which licence for our use? | Assessment | `model_card` plus the cost line |

The common questions (`*`) apply unchanged: owner, already catalogued,
existing use, feedback, licence (O1 answers Q-0012 and Q-0030), fit with
governance and security, data-product readiness (Q-0058), defined need
(Q-0059).

## 4. Surveys

| Survey definition | Steps | Fetch |
|---|---|---|
| `ExternalDataScout` | `external_metadata`, `external_distributions` | API only, seconds |
| `ExternalDataProfile` | the scout plus `external_profile` (sample), `data_class_match`, `external_provenance` | one sample per distribution, size-capped, stated |
| `ExternalDataRefresh` | `external_change` over two scouts | API only |
| `OpenModelScout` | `model_card` | one page |

Every step records the publisher's metadata verbatim with a retrieved-at,
and every measured number carries its sample size. "Not reported by this
source" is the word for a missing field; never blank.

## 5. Discovery sources

The discovery-sources generalisation (the designer's reply) is the way
in: a portal is a source of kind `external_data` whose "Run" lists
candidates (datasets by theme, keyword, publisher, licence), with the
preview-then-import confirm and the CSV in and out the reply designed.
A dataset's candidate row carries publisher, licence, modified, formats
and size, each "not reported by this source" when absent.

## 6. Publishing to Egeria

- The dataset as an asset of the nearest native type (a `DataSet` or
  `DataFile` set behind a `DeployedAPI` where the access is an API),
  with the publisher's identifier as the external identifier and the
  portal as the asset's origin (`DigitalResourceOrigin` naming the
  publisher).
- Licence as Egeria's licence type with the SPDX id; terms as an
  external reference; the publisher as an organisation actor profile.
- Coverage as `DataScope` (time and place), the data-scope note's home.
- Everything measured as survey annotations with the sample size; the
  publisher's statements as annotations marked "stated by the publisher".
- A model as an asset of the model-card shape Egeria offers (to confirm
  with the Egeria leads which type; a `DeployedAnalyticsModel` or similar
  exists in the AI area), its card fields as properties.

## 7. What to settle before an ask or a brief

- [ ] The kind's name on screen ("External data"? "Open data"?) and
      whether open models are the same kind or a sibling.
- [ ] Which portal API first (CKAN is the most common; DCAT covers the
      EU portal and data.gov's catalogue; Socrata for US cities).
- [ ] Egeria's types for a published dataset's distributions and for a
      model, with the Egeria leads.
- [ ] Whether the first instance is a demo portal (a CKAN demo instance)
      or a real one the owner cares about.
- [ ] Sample sizes and the fetch cap.

The next step, if the owner wants it: a designer ask for the candidate
row and the resource page of an external dataset, and a brief for
`external_metadata` on one CKAN portal as the walking slice.
