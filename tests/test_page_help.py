"""page.py card help: FA.help / FA.armHelp / modal composition / FA.flow / FA.readGrid, checked in Chrome."""
from __future__ import annotations

from page_dom import audit_html, requires_chrome
from second_opinion import page


def _page(body: str, script: str) -> str:
    return page.render(title="t", data={}, body=body, script=script)


@requires_chrome
def test_audit_hook_reports_cards(tmp_path) -> None:
    a = audit_html(_page('<section class="card" id="c"><h2>Plain</h2><p>x</p></section>', ""), tmp_path)
    assert a["help_links"] == 0
    assert a["cards"] == [{"h2": "Plain", "hidden": False, "help": "none", "buttons": 0, "modal": None}]


CARD = '<section class="card" id="c"><h2>DCF {t}</h2><p>{body}</p></section>'


@requires_chrome
def test_term_has_no_help_link_and_fallback_lists_terms(tmp_path) -> None:
    body = CARD.format(t="", body="")
    script = "document.querySelector('#c p').innerHTML = FA.term('wacc','WACC') + ' ' + FA.term('beta') + ' ' + FA.term('wacc','again') + ' ' + FA.term('not-a-key');"
    a = audit_html(_page(body, script), tmp_path)
    c = a["cards"][0]
    assert a["help_links"] == 0 and c["help"] == "fallback" and c["buttons"] == 1
    assert c["modal"]["terms"] == ["wacc", "beta"] and c["modal"]["sections"] == [] and c["modal"]["lead"] == ""
    assert all(link.startswith("https://") for link in c["modal"]["links"])


@requires_chrome
def test_authored_help_shows_lead_sections_then_terms(tmp_path) -> None:
    script = ("const c = document.getElementById('c'); c.querySelector('p').innerHTML = FA.term('wacc','WACC');"
              "FA.help(c, {lead: 'What one share is worth.', sections: [{title: 'How it adds up', html: '<p>x</p>'}, {title: 'Grid', render: el => { el.textContent = 'drawn'; }}]});")
    c = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]
    assert c["help"] == "authored" and c["buttons"] == 1
    assert c["modal"]["lead"] == "What one share is worth." and c["modal"]["sections"] == ["How it adds up", "Grid"]
    assert "drawn" in c["modal"]["text"] and c["modal"]["terms"] == ["wacc"] and c["modal"]["title"] == "DCF"


@requires_chrome
def test_rewritten_heading_keeps_its_button(tmp_path) -> None:
    script = ("const c = document.getElementById('c'); FA.help(c, {lead: 'L'});"
              "c.querySelector('h2').innerHTML = 'Renamed';")
    c = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]
    assert c["h2"] == "Renamed" and c["help"] == "authored" and c["buttons"] == 1


@requires_chrome
def test_arm_help_twice_adds_one_button(tmp_path) -> None:
    script = ("const c = document.getElementById('c'); c.querySelector('p').innerHTML = FA.term('beta');"
              "FA.armHelp(c); FA.armHelp(c); FA.armHelp(document); FA.help(c, {lead: 'L'}); FA.help(c, {lead: 'L2'});")
    c = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]
    assert c["buttons"] == 1 and c["modal"]["lead"] == "L2"


@requires_chrome
def test_a_throwing_section_does_not_break_the_modal(tmp_path) -> None:
    script = ("const c = document.getElementById('c'); c.querySelector('p').innerHTML = FA.term('beta');"
              "FA.help(c, {lead: 'L', sections: [{title: 'Bad', render: () => { throw new Error('x'); }}, {title: 'Good', html: 'ok'}]});")
    m = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]["modal"]
    assert m["sections"] == ["Bad", "Good"] and "Diagram unavailable" in m["text"] and m["terms"] == ["beta"]


@requires_chrome
def test_exempt_and_termless_cards(tmp_path) -> None:
    body = ('<section data-help="none"><h2>Flags</h2><p id="f"></p></section>'
            '<div class="card"><h2>No terms</h2></div>'
            '<div class="card" hidden id="h"><h2>Hidden</h2></div>')
    script = "document.getElementById('f').innerHTML = FA.term('beta'); FA.help(document.getElementById('h'), {lead: 'L'});"
    cards = {c["h2"]: c for c in audit_html(_page(body, script), tmp_path)["cards"]}
    assert cards["Flags"]["help"] == "exempt" and cards["Flags"]["buttons"] == 0
    assert cards["No terms"]["help"] == "none"
    assert cards["Hidden"]["hidden"] is True


@requires_chrome
def test_flow_and_read_grid_render_in_a_modal(tmp_path) -> None:
    script = ("const c = document.getElementById('c'); FA.help(c, {lead: 'L', sections: ["
              "{title: 'Adds up', html: FA.flow([{label: 'stage 1', value: '$20.0B'}, {op: '+', label: 'terminal', value: '$23.5B'}, {op: '=', label: 'enterprise value', value: '$43.6B'}])},"
              "{title: 'Grid', html: FA.readGrid({rowLabel: 'discount rate', colLabel: 'growth'})}]});")
    m = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]["modal"]
    for s in ("stage 1", "$20.0B", "+", "terminal", "=", "enterprise value", "$43.6B", "discount rate", "growth", "base case"):
        assert s in m["text"], s


@requires_chrome
def test_section_titles_and_lead_text_are_escaped_once(tmp_path) -> None:
    script = ("FA.help(document.getElementById('c'), {lead: 'L', sections: [{title: 'D R HORTON <\\/script> & CO', html: FA.flow([{label: 'A&B <x>', value: '$1'}])}]});")
    m = audit_html(_page(CARD.format(t="", body=""), script), tmp_path)["cards"][0]["modal"]
    assert m["sections"] == ["D R HORTON </script> & CO"] and "A&B <x>" in m["text"] and "&lt;" not in m["text"] and "&amp;" not in m["text"]
