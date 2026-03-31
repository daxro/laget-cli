from unittest.mock import MagicMock

from laget_cli.api.teams import _parse_teams, _parse_children, filter_teams_by_club, fetch_teams, fetch_children
from laget_cli.errors import ParseError


# HTML fixtures matching the real laget.se structure observed during reverse engineering

TEAMS_HTML = '''
<ul class="popoverList">
    <li>
        <div class="popoverList__itemInner padding--none">
            <a class="popoverList__contentWrapper" href="https://www.laget.se/TeamAlpha-P2021">
                <span class="popoverList__icon--angle"><i class="icon-angle-right"></i></span>
                <div class="popoverList__image--emblem"></div>
                <div class="popoverList__textWrapper">
                    <p class="popoverList__name"><b>P2021</b></p>
                    <small class="popoverList__club">Team Alpha FK</small>
                </div>
            </a>
        </div>
    </li>
    <li>
        <div class="popoverList__itemInner padding--none">
            <a class="popoverList__contentWrapper" href="https://www.laget.se/TeamBeta-F2019">
                <span class="popoverList__icon--angle"><i class="icon-angle-right"></i></span>
                <div class="popoverList__image--emblem"></div>
                <div class="popoverList__textWrapper">
                    <p class="popoverList__name"><b>F2019</b></p>
                    <small class="popoverList__club">Team Beta IK</small>
                </div>
            </a>
        </div>
    </li>
    <li>
        <div class="popoverList__itemInner padding--none">
            <a class="popoverList__contentWrapper" href="https://www.laget.se/TeamAlpha-P2019Vast">
                <span class="popoverList__icon--angle"><i class="icon-angle-right"></i></span>
                <div class="popoverList__image--emblem"></div>
                <div class="popoverList__textWrapper">
                    <p class="popoverList__name"><b>P2019 V&#228;st</b></p>
                    <small class="popoverList__club">Team Alpha FK</small>
                </div>
            </a>
        </div>
    </li>
</ul>
'''

CHILDREN_HTML = '''
<!DOCTYPE HTML>
<html>
<head><title>Mina uppgifter</title></head>
<body>
<div>
    <ul>
        <li>
            <a href="javascript:ShowChildProfileSettings('1234567');">
                <span><i class="user"></i></span><span>Alice Testsson</span>
            </a>
        </li>
        <li>
            <a href="javascript:ShowChildProfileSettings('7654321');">
                <span><i class="user"></i></span><span>Bob Testsson</span>
            </a>
        </li>
    </ul>
</div>
</body>
</html>
'''

CHILDREN_HTML_SINGLE = '''
<ul>
    <li>
        <a href="javascript:ShowChildProfileSettings('9999999');">
            <span>Only Child</span>
        </a>
    </li>
</ul>
'''

EMPTY_HTML = '<html><body>No data</body></html>'


class TestParseTeams:
    def test_parses_multiple_teams(self):
        teams = _parse_teams(TEAMS_HTML)
        assert len(teams) == 3
        assert teams[0] == {"name": "P2021", "club": "Team Alpha FK", "team_slug": "TeamAlpha-P2021"}
        assert teams[1] == {"name": "F2019", "club": "Team Beta IK", "team_slug": "TeamBeta-F2019"}
        assert teams[2] == {"name": "P2019 Väst", "club": "Team Alpha FK", "team_slug": "TeamAlpha-P2019Vast"}

    def test_empty_html_returns_empty_list(self):
        teams = _parse_teams(EMPTY_HTML)
        assert teams == []

    def test_raises_parse_error_on_broken_popover_list(self):
        broken = '<ul class="popoverList"><li>broken content</li></ul>'
        try:
            _parse_teams(broken)
            assert False, "Should have raised ParseError"
        except ParseError as e:
            assert "popoverList" in str(e)


class TestParseChildren:
    def test_parses_multiple_children(self):
        children = _parse_children(CHILDREN_HTML)
        assert len(children) == 2
        assert children[0] == {"name": "Alice Testsson", "id": "1234567"}
        assert children[1] == {"name": "Bob Testsson", "id": "7654321"}

    def test_parses_single_child(self):
        children = _parse_children(CHILDREN_HTML_SINGLE)
        assert len(children) == 1
        assert children[0] == {"name": "Only Child", "id": "9999999"}

    def test_empty_html_returns_empty_list(self):
        children = _parse_children(EMPTY_HTML)
        assert children == []


class TestFilterTeamsByClub:
    def test_filters_by_club_name(self):
        teams = [
            {"name": "P2021", "club": "Team Alpha FK", "team_slug": "a"},
            {"name": "F2019", "club": "Team Beta IK", "team_slug": "b"},
            {"name": "P2019", "club": "Team Alpha FK", "team_slug": "c"},
        ]
        result = filter_teams_by_club(teams, "Team Alpha")
        assert len(result) == 2
        assert all(t["club"] == "Team Alpha FK" for t in result)

    def test_case_insensitive(self):
        teams = [{"name": "T1", "club": "Test Club", "team_slug": "a"}]
        assert len(filter_teams_by_club(teams, "test club")) == 1
        assert len(filter_teams_by_club(teams, "TEST CLUB")) == 1

    def test_no_filter_returns_all(self):
        teams = [{"name": "T1", "club": "A", "team_slug": "a"}, {"name": "T2", "club": "B", "team_slug": "b"}]
        assert len(filter_teams_by_club(teams, None)) == 2
        assert len(filter_teams_by_club(teams, "")) == 2

    def test_no_match_returns_empty(self):
        teams = [{"name": "T1", "club": "A", "team_slug": "a"}]
        assert filter_teams_by_club(teams, "nonexistent") == []


class TestFetchTeams:
    def test_fetch_teams_calls_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = TEAMS_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        teams = fetch_teams(session)
        assert len(teams) == 3
        session.get.assert_called_once()
        assert "/Common/UserMenu/Pages" in session.get.call_args[0][0]


class TestFetchChildren:
    def test_fetch_children_calls_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = CHILDREN_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        children = fetch_children(session)
        assert len(children) == 2
        session.get.assert_called_once()
        assert "/User/Children" in session.get.call_args[0][0]
