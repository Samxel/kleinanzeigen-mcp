"""Pure helpers: title matching, spec terms, JAXB unwrapping and categories."""

import main


def test_tokens_split_fused_model_codes():
    assert main._tokens("Gigabyte RTX4070 Windforce") == {"gigabyte", "rtx", "4070", "windforce"}
    assert main._tokens("Grün") == {"grun"}


def test_a_number_with_its_unit_matches_however_it_is_spelled():
    forms = main._term_forms("128 GB")
    for title in ("iPhone 13 128GB", "iPhone 13 128 GB", "iPhone 13 128gb"):
        assert main._has_term(main._tokens(title), forms), title
    assert not main._has_term(main._tokens("iPhone 13 256GB"), forms)


def test_exclude_matches_words_and_compound_tails_but_not_prefixes():
    pro = main._term_forms("pro")
    assert main._has_term(main._tokens("iPhone 13 Pro"), pro)
    assert not main._has_term(main._tokens("Intel Prozessor"), pro)
    assert main._has_term(main._tokens("USB Ladekabel"), main._term_forms("kabel"))


def test_jaxb_values_and_namespaced_collections_unwrap():
    assert main._v({"value": 3}) == 3 and main._v(None, "x") == "x"
    assert main._ns({"{http://x/v1}ads": {"value": {"ad": []}}}, "ads") == {"ad": []}


def test_descriptions_lose_their_html():
    assert main._clean_description("Zeile 1<br />Zeile 2 &amp; mehr<b></b>") == "Zeile 1\nZeile 2 & mehr"


def test_categories_resolve_by_id_or_name():
    assert main._resolve_category(225) == 225
    assert main._resolve_category("PC-Zubehör & Software") == 225
    assert main._resolve_category("handy") == 173
