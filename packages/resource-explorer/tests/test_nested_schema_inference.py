"""Phase 1 slice 11 — the reusable JSON/XML schema-inference core.

`nested_schema_inference.py` has zero database coupling on purpose (design
§5.4: "reused by §6's `nested_schema_profile`"), so it is tested purely
against Python values here — no fake connection, no Postgres SQL shape. The
Postgres-specific glue (`nested_columns_step.py`) has its own test file.

Covers: key-frequency/type-consistency inference including the case §5.4/the
task brief calls out by name — inconsistent types across the sample for the
same key, which is a real, useful finding and must not read as an error; XML
root/element/attribute name sampling; and every absence/label state
(`empty`, `scalar_only`, `mixed`, `structured`, `unparseable`).
"""
from __future__ import annotations

from resource_explorer.surveyors.nested_schema_inference import (
    JSON_TYPE_BOOLEAN,
    JSON_TYPE_NULL,
    JSON_TYPE_NUMBER,
    JSON_TYPE_OBJECT,
    JSON_TYPE_STRING,
    LABEL_EMPTY,
    LABEL_MIXED,
    LABEL_SCALAR_ONLY,
    LABEL_STRUCTURED,
    LABEL_UNPARSEABLE,
    NO_SCHEMA_LABELS,
    classify_json_sample,
    classify_xml_sample,
    infer_json_schema,
    infer_xml_schema,
    json_value_type,
)


# ── json_value_type ──────────────────────────────────────────────────────────

class TestJsonValueType:
    def test_bool_is_boolean_not_number(self):
        # bool is an int subclass in Python — the classic trap.
        assert json_value_type(True) == JSON_TYPE_BOOLEAN
        assert json_value_type(False) == JSON_TYPE_BOOLEAN

    def test_int_and_float_are_number(self):
        assert json_value_type(3) == JSON_TYPE_NUMBER
        assert json_value_type(3.5) == JSON_TYPE_NUMBER

    def test_none_is_null(self):
        assert json_value_type(None) == JSON_TYPE_NULL

    def test_dict_and_list(self):
        assert json_value_type({}) == JSON_TYPE_OBJECT
        assert json_value_type([]) == "array"


# ── infer_json_schema: key frequency and type consistency ──────────────────

class TestInferJsonSchema:
    def test_key_present_in_every_document_gets_fraction_one(self):
        docs = [{"id": 1}, {"id": 2}, {"id": 3}]
        schema = infer_json_schema(docs)
        by_path = {k.path: k for k in schema.keys}
        assert by_path["id"].presence_fraction == 1.0

    def test_optional_key_gets_a_fraction_below_one(self):
        docs = [{"id": 1, "note": "x"}, {"id": 2}, {"id": 3}]
        schema = infer_json_schema(docs)
        by_path = {k.path: k for k in schema.keys}
        assert by_path["note"].presence_fraction == 1 / 3

    def test_inconsistent_types_for_the_same_key_is_a_real_finding(self):
        """The case the task brief names specifically: a column that stores
        an `age` key as a number in most rows and a string in a few must
        report BOTH observed types and `type_consistent=False` — not raise,
        not silently pick one, not drop the key."""
        docs = [{"age": 30}, {"age": 41}, {"age": "unknown"}, {"age": 22}]
        schema = infer_json_schema(docs)
        by_path = {k.path: k for k in schema.keys}
        age = by_path["age"]
        assert age.observed_types[JSON_TYPE_NUMBER] == 3
        assert age.observed_types[JSON_TYPE_STRING] == 1
        assert age.type_consistent is False
        assert age.dominant_type == JSON_TYPE_NUMBER

    def test_null_does_not_count_as_a_competing_type(self):
        """A nullable string field is still a string field — null must not
        make it read as inconsistent."""
        docs = [{"note": "a"}, {"note": None}, {"note": "b"}]
        schema = infer_json_schema(docs)
        by_path = {k.path: k for k in schema.keys}
        note = by_path["note"]
        assert note.type_consistent is True
        assert note.dominant_type == JSON_TYPE_STRING

    def test_a_key_that_is_only_ever_null_has_no_dominant_type(self):
        docs = [{"x": None}, {"x": None}]
        schema = infer_json_schema(docs)
        by_path = {k.path: k for k in schema.keys}
        assert by_path["x"].type_consistent is True
        assert by_path["x"].dominant_type is None

    def test_nested_object_keys_use_dot_paths(self):
        docs = [{"address": {"city": "London"}}, {"address": {"city": "Leeds"}}]
        schema = infer_json_schema(docs)
        paths = {k.path for k in schema.keys}
        assert "address" in paths
        assert "address.city" in paths
        by_path = {k.path: k for k in schema.keys}
        assert by_path["address.city"].depth == 2

    def test_array_of_objects_uses_bracket_marker(self):
        docs = [{"items": [{"sku": "A"}, {"sku": "B"}]}]
        schema = infer_json_schema(docs)
        paths = {k.path for k in schema.keys}
        assert "items[].sku" in paths

    def test_depth_is_bounded(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": 1}}}}}}}
        schema = infer_json_schema([deep], max_depth=3)
        assert schema.max_depth <= 3
        paths = {k.path for k in schema.keys}
        assert "a.b.c" in paths
        assert "a.b.c.d" not in paths

    def test_truncated_flag_set_when_key_cap_hit(self):
        doc = {f"k{i}": i for i in range(10)}
        schema = infer_json_schema([doc], max_keys=5)
        assert schema.truncated is True
        assert len(schema.keys) == 5

    def test_top_level_scalar_counts_as_scalar_not_a_document(self):
        schema = infer_json_schema([1, "x", True, None])
        assert schema.scalar_count == 4
        assert schema.document_count == 0
        assert schema.keys == ()

    def test_top_level_array_of_scalars_contributes_no_documents(self):
        schema = infer_json_schema([[1, 2, 3]])
        assert schema.array_count == 1
        assert schema.document_count == 0

    def test_empty_sample(self):
        schema = infer_json_schema([])
        assert schema.sample_size == 0
        assert schema.keys == ()

    def test_as_dict_round_trips_the_shape(self):
        schema = infer_json_schema([{"id": 1}])
        d = schema.as_dict()
        assert d["document_count"] == 1
        assert d["keys"][0]["path"] == "id"


# ── classify_json_sample ─────────────────────────────────────────────────────

class TestClassifyJsonSample:
    def test_empty_sample_is_empty_label(self):
        assert classify_json_sample(infer_json_schema([])) == LABEL_EMPTY

    def test_all_scalar_is_scalar_only(self):
        assert classify_json_sample(infer_json_schema([1, 2, "x"])) == LABEL_SCALAR_ONLY

    def test_all_objects_is_structured(self):
        schema = infer_json_schema([{"a": 1}, {"a": 2}])
        assert classify_json_sample(schema) == LABEL_STRUCTURED

    def test_a_mix_of_scalar_and_object_is_mixed(self):
        schema = infer_json_schema([{"a": 1}, 42, "plain string"])
        assert classify_json_sample(schema) == LABEL_MIXED

    def test_an_empty_object_is_still_structured_not_scalar(self):
        # {} holds no keys but IS nested data — a real distinction from a
        # bare scalar, which the classifier must not conflate.
        schema = infer_json_schema([{}, {}])
        assert classify_json_sample(schema) == LABEL_STRUCTURED

    def test_scalar_only_and_unparseable_are_the_no_schema_labels(self):
        assert LABEL_SCALAR_ONLY in NO_SCHEMA_LABELS
        assert LABEL_UNPARSEABLE in NO_SCHEMA_LABELS
        assert LABEL_STRUCTURED not in NO_SCHEMA_LABELS
        assert LABEL_MIXED not in NO_SCHEMA_LABELS


# ── infer_xml_schema / classify_xml_sample ──────────────────────────────────

class TestInferXmlSchema:
    def test_root_element_is_counted(self):
        docs = ["<order><id>1</id></order>", "<order><id>2</id></order>"]
        schema = infer_xml_schema(docs)
        assert schema.root_element_counts == {"order": 2}
        assert schema.dominant_root_element == "order"

    def test_element_and_attribute_names_are_collected(self):
        docs = ['<order id="1"><item sku="A"/></order>']
        schema = infer_xml_schema(docs)
        names = {(n.name, n.kind) for n in schema.names}
        assert ("order", "element") in names
        assert ("item", "element") in names
        assert ("id", "attribute") in names
        assert ("sku", "attribute") in names

    def test_namespace_qualified_tags_are_reduced_to_local_name(self):
        docs = ['<a:order xmlns:a="urn:x"><a:id>1</a:id></a:order>']
        schema = infer_xml_schema(docs)
        assert schema.dominant_root_element == "order"
        names = {n.name for n in schema.names}
        assert "id" in names

    def test_presence_fraction_is_against_parsed_count_not_sample_size(self):
        docs = [
            "<order><id>1</id></order>",
            "<order><id>2</id></order>",
            "not xml at all",
        ]
        schema = infer_xml_schema(docs)
        assert schema.sample_size == 3
        assert schema.parsed_count == 2
        assert schema.unparseable_count == 1
        by_name = {n.name: n for n in schema.names}
        assert by_name["id"].presence_fraction == 1.0  # 2 of 2 PARSED, not 2 of 3

    def test_unparseable_value_does_not_raise(self):
        schema = infer_xml_schema(["<not-closed>", "also not xml"])
        assert schema.parsed_count == 0
        assert schema.unparseable_count == 2

    def test_depth_bounded(self):
        doc = "<a><b><c><d><e><f>x</f></e></d></c></b></a>"
        schema = infer_xml_schema([doc], max_depth=2)
        assert schema.max_depth <= 2

    def test_none_values_are_treated_as_unparseable(self):
        schema = infer_xml_schema([None, "<a/>"])
        assert schema.unparseable_count == 1
        assert schema.parsed_count == 1


class TestClassifyXmlSample:
    def test_empty_sample(self):
        assert classify_xml_sample(infer_xml_schema([])) == LABEL_EMPTY

    def test_all_unparseable(self):
        schema = infer_xml_schema(["not xml", "<broken"])
        assert classify_xml_sample(schema) == LABEL_UNPARSEABLE

    def test_all_well_formed_is_structured(self):
        schema = infer_xml_schema(["<a/>", "<a/>"])
        assert classify_xml_sample(schema) == LABEL_STRUCTURED

    def test_a_mix_is_mixed(self):
        schema = infer_xml_schema(["<a/>", "not xml"])
        assert classify_xml_sample(schema) == LABEL_MIXED
