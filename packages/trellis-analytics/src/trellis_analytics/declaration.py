"""The declaration: what an analysis says about its own results, so a screen, a chat answer and an Egeria publish can
use them with no code written for that analysis (design note DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE,
§1 "what a declaration carries", §2 result kinds, §4 confidence forms).

One model, two carriers. A library step carries it as `StepManifest.declaration`; Resource Explorer's own analyses
carry the same fields under `declaration:` in `analysis_catalog.yaml`, validated by this same class
(`analysis_catalog_reader`). The generator copies a step's declaration into its catalogue entry unchanged.

Two levels (owner's answer 2, §1): the **minimum** an experiment runs with is `result_kind`, `measures` and
`absence`, and this class refuses anything less. A repeatable analysis is promoted to a **full** declaration by adding
`extents`, `confidence`, `answers` and `scope`; `missing()` names what a minimum declaration still lacks.

Every refusal is a sentence naming the field and the value refused, as the manifest's own validators word theirs.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: §2: the fixed vocabulary. A ninth kind is a design change, not a value a declaration may invent.
RESULT_KINDS = ("measure", "series", "distribution", "list", "graph", "finding", "proposal", "table")

#: §1's four absences, each a sentence the analysis declares, never one a renderer improvises. How they meet the
#: envelope's states (`envelope.ResultState`): `measured_nothing` is `nothing_found`; `not_measured` and
#: `not_permitted` are both `not_established`, told apart by the reason (could not look, versus not allowed to);
#: `not_applicable` is `not_applicable`.
ABSENCE_STATES = ("not_measured", "not_permitted", "not_applicable", "measured_nothing")

#: §4: a result's confidence is one of five forms, and a score never travels without its basis.
CONFIDENCE_FORMS = ("measured", "estimated", "inferred", "judged", "generated")

#: The forms from strongest to weakest, for §4's "weakest link": a declaration's headline confidence is the weakest
#: of its measures' (project owner, 2026-10-28). A measured read is exact; a judged result carries a person's
#: signature on its evidence; an estimate has a known error; an inferred match a rule or model score; a generated
#: answer is only as good as what it drew on.
CONFIDENCE_STRENGTH = ("measured", "judged", "estimated", "inferred", "generated")

#: §1 `scope`: the level a result is about.
SCOPES = ("resource", "container", "member", "field")

#: The words an extent's truncation sentence must carry for the compiler to fill: "{shown} of {total} ... shown".
TRUNCATION_PLACEHOLDERS = ("{shown}", "{total}")

#: The fields a full declaration adds to the minimum, in the order `missing()` names them.
FULL_FIELDS = ("extents", "confidence", "answers", "scope")


def _words(v: str) -> str:
    return " ".join(str(v or "").split())


class _Strict(BaseModel):
    # An unknown key is refused, so a misspelt field is named rather than silently dropped.
    model_config = ConfigDict(extra="forbid")


class AnnotationDeclaration(_Strict):
    """The Egeria annotation a measure writes as (§1 `annotation`), or absent: "generic measure, no native type
    declared" (owner's answer 1). `properties` maps a result field to the Egeria property it is written to; empty
    means the type is declared and its property map is not."""
    type: str
    properties: dict[str, str] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type(cls, v: str) -> str:
        if not _words(v):
            raise ValueError("annotation type is empty: name the Egeria annotation type, or leave annotation out "
                             "for a generic measure")
        return _words(v)


class MeasureDeclaration(_Strict):
    """One number the analysis reports. A number never travels without its unit and its as-of (§1)."""
    name: str
    #: In words, plural where it counts things: "tables", "rows per day", "days", "fraction of rows (0-1)".
    unit: str
    #: The result field that says when this was measured ("asOf", "surveyed_at", "toAsOf"). A dotted path names a
    #: nested field ("temporal.as_of"); `run.<field>` names a field of the run that produced the result rather than
    #: of the result itself (`run.read_snapshot`: the newest stored row a zero-fetch derivation read).
    as_of: str
    #: The result field holding the value; a dotted path names a nested one ("counts.stale"), and a trailing `[]`
    #: declares the value as the number of items in a list field ("columns_added[]": columns added, counted).
    value_field: str
    #: What it writes as in Egeria; absent is the generic measure route, labelled as such.
    annotation: AnnotationDeclaration | None = None
    #: This measure's own confidence, where it differs from the declaration's (project owner, 2026-10-28: confidence
    #: is per measure). Absent means the declaration's confidence is this measure's.
    confidence: "ConfidenceDeclaration | None" = None

    @model_validator(mode="after")
    def _filled(self) -> "MeasureDeclaration":
        empty = [f for f in ("name", "unit", "as_of", "value_field") if not _words(getattr(self, f))]
        if empty:
            label = f"measure '{self.name}'" if _words(self.name) else "a measure"
            raise ValueError(f"{label} declares no {', '.join(empty)}: a number never travels without its unit "
                             "and its as-of")
        return self


class AbsenceSentences(_Strict):
    """§1 `absence`: the sentence shown for each way a result can be absent. All four are declared."""
    not_measured: str
    not_permitted: str
    not_applicable: str
    measured_nothing: str

    @model_validator(mode="after")
    def _filled(self) -> "AbsenceSentences":
        empty = [s for s in ABSENCE_STATES if not _words(getattr(self, s))]
        if empty:
            raise ValueError(f"absence sentence for {', '.join(empty)} is empty: an absence is declared, never "
                             "improvised")
        return self

    def sentence(self, state: str) -> str:
        return getattr(self, state)


class ExtentDeclaration(_Strict):
    """§3 step 2: one shape the Chat compiler may take from this analysis, and no other."""
    name: str
    fields: list[str]
    #: How many rows the extent carries at most.
    rows: int
    #: The order rows are taken in, in words ("PUBLIC grantees first, then by table"), for an order no `sort` can
    #: say. Not declared beside `sort`: the order is said in one place.
    order: str = ""
    #: The order as keys the compiler applies, each "<field> asc" or "<field> desc" on one of `fields`, first key
    #: first ("row_count desc"); the words are derived from it (`order_words`). Project owner, 2026-10-28.
    sort: list[str] = Field(default_factory=list)
    #: Shown when rows were dropped; carries `{shown}` and `{total}` for the compiler to fill.
    truncation: str
    #: The extent's cost at `rows` rows, in tokens, for the compiler's budget (§3 step 4).
    token_cost: int
    #: How an answer cites a row of this extent ("{analysis} · {scope} · as of {as_of}").
    citation: str
    #: Where the rows are in the result, when that is not a field named like the extent: each a dotted path to a
    #: list (each item a row) or to a mapping (one row), "." the result itself as one row. Several are joined in
    #: order. Empty means the extent's name is the path.
    source: list[str] = Field(default_factory=list)
    #: With several sources: the row field that carries which source a row came from (the path's last part:
    #: "columns_added"), so joined rows stay told apart. Empty for none.
    tag: str = ""

    @field_validator("source", "sort", mode="before")
    @classmethod
    def _one_item(cls, v):
        return [v] if isinstance(v, str) else v

    def sort_keys(self) -> list[tuple[str, bool]]:
        """`sort` as (field, descending) pairs, first key first."""
        out = []
        for key in self.sort:
            field, _, direction = " ".join(key.split()).rpartition(" ")
            out.append((field, direction == "desc"))
        return out

    def order_words(self) -> str:
        """The order in words: derived from `sort` when it is declared, else the declared sentence."""
        if not self.sort:
            return self.order
        return "by " + ", then ".join(f"{f}, {'descending' if d else 'ascending'}" for f, d in self.sort_keys())

    @model_validator(mode="after")
    def _shape(self) -> "ExtentDeclaration":
        label = f"extent '{self.name}'" if _words(self.name) else "an extent"
        if not _words(self.name):
            raise ValueError("an extent declares no name")
        if any(not _words(s) for s in self.source):
            raise ValueError(f"{label} declares an empty source path")
        if _words(self.tag) and _words(self.tag) not in self.fields:
            raise ValueError(f"{label} tags its rows with '{self.tag}', which is not one of its fields: the tag is "
                             "how the rows are told apart, so the compiler must show it")
        if not [f for f in self.fields if _words(f)]:
            raise ValueError(f"{label} declares no fields: the compiler takes the declared fields and no others")
        if self.rows < 1:
            raise ValueError(f"{label} declares rows {self.rows}: an extent carries at least one row")
        if self.token_cost < 1:
            raise ValueError(f"{label} declares token_cost {self.token_cost}: the compiler budgets by it, so it "
                             "must be a positive estimate")
        if not _words(self.citation):
            raise ValueError(f"{label} declares no citation")
        if self.sort and _words(self.order):
            raise ValueError(f"{label} declares both sort and order: the order is said in one place, so leave the "
                             "order sentence out and it is derived from sort")
        if not self.sort and not _words(self.order):
            raise ValueError(f"{label} declares no order: declare sort keys, or the order in words when no key "
                             "can say it")
        for key in self.sort:
            field, _, direction = " ".join(key.split()).rpartition(" ")
            if direction not in ("asc", "desc") or not field:
                raise ValueError(f"{label} sort key '{key}' is not '<field> asc' or '<field> desc'")
            if field not in self.fields:
                raise ValueError(f"{label} sorts by '{field}', which is not one of its fields")
        lacking = [p for p in TRUNCATION_PLACEHOLDERS if p not in self.truncation]
        if lacking:
            raise ValueError(f"{label} truncation sentence '{self.truncation}' lacks {', '.join(lacking)}: it says "
                             "how many rows were shown of how many")
        return self


class ConfidenceDeclaration(_Strict):
    """§4: the form, and the result field that carries its basis. A score never travels without its basis."""
    form: str
    #: The result field carrying the basis: the method or sample ratio (estimated), the rules that matched
    #: (inferred), who and on what evidence (judged), the sources drawn on (generated). Empty for `measured`, whose
    #: basis is its as-of and scope.
    basis: str = ""
    #: The basis in words, which is what a person reads beside the form. Required whenever `basis` names a result
    #: field (a field path is for the code, not the reader); alone it stands for a basis no result field carries: an estimate's
    #: source ("pg_stat_user_tables.n_live_tup, the statistics collector's live-row estimate"). An estimated or
    #: generated result declares a basis field, a method, or both; an inferred or judged one needs its basis field,
    #: because its basis differs per result.
    method: str = ""
    #: The result field carrying the score, for an inferred result; empty where there is none.
    score: str = ""
    #: Inferred only, and required there (§4 "calibration is stated"): is the score a calibrated probability, or a
    #: rule count?
    calibrated: bool | None = None

    @model_validator(mode="after")
    def _form(self) -> "ConfidenceDeclaration":
        if self.form not in CONFIDENCE_FORMS:
            raise ValueError(f"confidence form '{self.form}' is not one of the five forms "
                             f"({', '.join(CONFIDENCE_FORMS)})")
        if self.form in ("inferred", "judged") and not _words(self.basis):
            raise ValueError(f"confidence form '{self.form}' declares no basis: a score never travels without "
                             "its basis, and this form's basis differs per result, so name the field carrying it")
        if self.form in ("estimated", "generated") and not (_words(self.basis) or _words(self.method)):
            raise ValueError(f"confidence form '{self.form}' declares no basis and no method: say how the number "
                             "was arrived at")
        if self.form == "measured" and (_words(self.score) or self.calibrated is not None):
            raise ValueError("confidence form 'measured' declares a score: an exact read has none, because none "
                             "is meaningful")
        if self.form == "inferred" and self.calibrated is None:
            raise ValueError("confidence form 'inferred' does not say whether its score is calibrated: state "
                             "calibrated true (a probability) or false (a rule count)")
        if self.form != "inferred" and self.calibrated is not None:
            raise ValueError(f"confidence form '{self.form}' declares calibrated: only an inferred score is "
                             "calibrated or not")
        if _words(self.basis) and not _words(self.method):
            raise ValueError(f"confidence basis '{self.basis}' names a result field and no method: a person reads "
                             "the method, never a field path, so say the basis in words")
        return self


class Declaration(_Strict):
    """What an analysis declares about its results (§1). `result_kind`, `measures` and `absence` are the minimum."""
    result_kind: str
    #: Required when the kind is `table` (§1: "none fits -> table and say so"): why none of the other seven fits.
    result_kind_note: str = ""
    measures: list[MeasureDeclaration]
    absence: AbsenceSentences
    extents: list[ExtentDeclaration] = Field(default_factory=list)
    confidence: ConfidenceDeclaration | None = None
    #: The question ids this answers. None means not yet declared; [] declares that it answers none, which keeps it
    #: runnable and rendered and out of every chat answer (§3 step 1). For Resource Explorer's own analyses it is
    #: generated from the question catalogue (project owner, 2026-10-28), never written by hand.
    answers: list[str] | None = None
    #: False for an analysis that is registered and declared but has no runner yet (project owner, 2026-10-28:
    #: declare them, marked not built, so they read as "planned, not measured" rather than as nothing).
    built: bool = True
    scope: Literal["resource", "container", "member", "field"] | None = None

    @field_validator("result_kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in RESULT_KINDS:
            raise ValueError(f"result_kind '{v}' is not one of the {len(RESULT_KINDS)} kinds "
                             f"({', '.join(RESULT_KINDS)}); if none fits, declare 'table' and say why in "
                             "result_kind_note")
        return v

    @field_validator("scope", mode="before")
    @classmethod
    def _scope(cls, v):
        if v is not None and v not in SCOPES:
            raise ValueError(f"scope '{v}' is not one of the levels ({', '.join(SCOPES)})")
        return v

    @model_validator(mode="after")
    def _whole(self) -> "Declaration":
        if self.result_kind == "table" and not _words(self.result_kind_note):
            raise ValueError("result_kind 'table' declares no result_kind_note: say why none of the other kinds "
                             "fits")
        if not self.measures:
            raise ValueError("declares no measures: every analysis reports at least one, with its unit and as-of")
        names = [m.name for m in self.measures]
        twice = sorted({n for n in names if names.count(n) > 1})
        if twice:
            raise ValueError(f"measure {', '.join(twice)} is declared more than once")
        extents = [e.name for e in self.extents]
        twice = sorted({n for n in extents if extents.count(n) > 1})
        if twice:
            raise ValueError(f"extent {', '.join(twice)} is declared more than once")
        if self.answers is not None:
            blank = [a for a in self.answers if not _words(a)]
            if blank:
                raise ValueError("answers carries an empty question id")
        generated = [m.name for m in self.measures if m.annotation and self.confidence_of(m)
                     and self.confidence_of(m).form == "generated"]
        if generated:
            raise ValueError("confidence form 'generated' declares an annotation: a generated answer is not "
                             f"published, so it writes as nothing (measure {', '.join(generated)})")
        own = [m.confidence for m in self.measures if m.confidence is not None]
        if own:
            forms = [c.form for c in own] + ([self.confidence.form] if self.confidence and
                                              len(own) < len(self.measures) else [])
            weakest = max(forms, key=CONFIDENCE_STRENGTH.index)
            if self.confidence is None:
                if len(own) < len(self.measures):
                    raise ValueError("a measure declares its own confidence and the declaration none: the measures "
                                     "without one have no confidence to inherit")
                self.confidence = next(c for c in own if c.form == weakest)
            elif self.confidence.form != weakest:
                raise ValueError(f"confidence form '{self.confidence.form}' is not the weakest of its measures' "
                                 f"('{weakest}'): the declaration's confidence is its weakest link")
        return self

    def confidence_of(self, measure: MeasureDeclaration) -> ConfidenceDeclaration | None:
        """A measure's confidence: its own, else the declaration's."""
        return measure.confidence or self.confidence

    def measure(self, name: str) -> MeasureDeclaration | None:
        return next((m for m in self.measures if m.name == name), None)

    def missing(self) -> list[str]:
        """The full-declaration fields this one does not declare yet, in `FULL_FIELDS` order; [] when complete."""
        return [f for f, absent in (("extents", not self.extents), ("confidence", self.confidence is None),
                                    ("answers", self.answers is None), ("scope", self.scope is None)) if absent]

    def is_complete(self) -> bool:
        return not self.missing()


MeasureDeclaration.model_rebuild()


def refusal(exc: Exception) -> str:
    """A validation failure as one sentence per problem, without pydantic's framing ("1 validation error for ..."),
    naming where in the declaration each one is."""
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    parts = []
    for e in errors():
        where = ".".join(str(p) for p in e.get("loc", ()))
        msg = str(e.get("msg", "")).removeprefix("Value error, ")
        if e.get("type") == "extra_forbidden":
            msg = "is not a declaration field"
        elif e.get("type") == "missing":
            msg = "is required"
        parts.append(f"{where} {msg}" if where else msg)
    return "; ".join(parts)
