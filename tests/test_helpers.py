"""Pure helpers: title matching, spec terms, JAXB unwrapping and categories."""

from kleinanzeigen import api, categories, matching, summaries


def test_tokens_split_fused_model_codes():
    assert matching.tokens("Gigabyte RTX4070 Windforce") == {"gigabyte", "rtx", "4070", "windforce"}
    assert matching.tokens("Grün") == {"grun"}


def test_a_number_with_its_unit_matches_however_it_is_spelled():
    forms = matching.term_forms("128 GB")
    for title in ("iPhone 13 128GB", "iPhone 13 128 GB", "iPhone 13 128gb"):
        assert matching.has_term(matching.tokens(title), forms), title
    assert not matching.has_term(matching.tokens("iPhone 13 256GB"), forms)


def test_exclude_matches_words_and_compound_tails_but_not_prefixes():
    pro = matching.term_forms("pro")
    assert matching.has_term(matching.tokens("iPhone 13 Pro"), pro)
    assert not matching.has_term(matching.tokens("Intel Prozessor"), pro)
    assert matching.has_term(matching.tokens("USB Ladekabel"), matching.term_forms("kabel"))


def test_jaxb_values_and_namespaced_collections_unwrap():
    assert api.unwrap({"value": 3}) == 3 and api.unwrap(None, "x") == "x"
    assert api.collection({"{http://x/v1}ads": {"value": {"ad": []}}}, "ads") == {"ad": []}


def test_descriptions_lose_their_html():
    assert summaries.clean_description("Zeile 1<br />Zeile 2 &amp; mehr<b></b>") == "Zeile 1\nZeile 2 & mehr"


def test_categories_resolve_by_id_or_name():
    assert categories.resolve(225) == 225
    assert categories.resolve("PC-Zubehör & Software") == 225
    assert categories.resolve("handy") == 173
