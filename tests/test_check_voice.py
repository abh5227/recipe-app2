"""The mechanical voice checker, and specifically the three cases that made it wrong.

Every test here is a recorded false positive or false negative, not a hypothetical.
"""
import check_voice


def write(tmp_path, body, name="entry.toml"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_a_citation_key_is_not_a_british_spelling(tmp_path):
    """⚠️ THE CASE THAT SET THE EXCLUSION LIST. Eriksson et al. 2012 is published in
    Flavour, a BMC journal. Americanizing the key breaks the reference."""
    p = write(tmp_path, '''
id = "coriandrum-sativum"
[[claims]]
text = "Some people taste cilantro as soapy."
  [[claims.chain]]
  source = "eriksson-2012-flavour-1-22"
  taken = "GWAS, 14,604 participants."
''')
    violations, quoted = check_voice.check(p)
    assert violations == []
    assert quoted == []


def test_a_verbatim_source_name_is_not_our_prose(tmp_path):
    """`form` holds names copied verbatim. build_library.py invents no name anywhere."""
    p = write(tmp_path, '''
[[forms]]
form = "Bourbon vanilla flavouring"
note = "A source name, kept exactly as written."
''')
    violations, _ = check_voice.check(p)
    assert violations == []


def test_labeled_with_one_l_is_american_and_passes(tmp_path):
    """⚠️ `labell?ed` matched the AMERICAN spelling and reported 11 correct words."""
    p = write(tmp_path, '[[prose]]\nbody = "Two jars labeled the same can differ."\n')
    assert check_voice.check(p)[0] == []


def test_labelled_with_two_ls_is_british_and_fails(tmp_path):
    p = write(tmp_path, '[[prose]]\nbody = "Oats labelled gluten free are grown apart."\n')
    violations, _ = check_voice.check(p)
    assert [v[1] for v in violations] == ["British spelling"]


def test_a_decree_number_is_not_a_range(tmp_path):
    """⚠️ `n°88-1204` counts DOWN and follows a number sign. Both guards catch it."""
    p = write(tmp_path, '[[prose]]\nbody = "Set by décret n°88-1204 of 30 December 1988."\n')
    assert check_voice.check(p)[0] == []


def test_a_real_range_still_fails(tmp_path):
    p = write(tmp_path, '[[prose]]\nbody = "It swells between 62-72 degrees."\n')
    violations, _ = check_voice.check(p)
    assert [v[1] for v in violations] == ["range not written out"]


def test_em_dash_and_semicolon_are_violations(tmp_path):
    p = write(tmp_path, '[[prose]]\nbody = "One thing — another; a third."\n')
    names = sorted(v[1] for v in check_voice.check(p)[0])
    assert names == ["em dash", "semicolon"]


def test_a_quoted_source_name_is_reported_separately(tmp_path):
    """A name quoted inside a diagnostic is neither clean nor a violation."""
    p = write(tmp_path, '''
[row_diagnostic]
detail = "It carries 'vanilla flavouring', which is a source name."
''')
    violations, quoted = check_voice.check(p)
    assert violations == []
    assert [q[1] for q in quoted] == ["British spelling"]
