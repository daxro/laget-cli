"""Tests for laget_cli.api.news."""

import pytest

from unittest.mock import MagicMock

from laget_cli.api.news import _parse_article, _parse_comments, fetch_article

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

ARTICLE_HTML = """\
<div class="box__content padding--full text--breakWord">
  <h3 class="headline">Cupen i Alvik 12-13 april</h3>

  <div class="hidden--mobile">
    <small class="meta--singleLine">
      <span class="meta__item float--left tooltip tooltipstered" style="margin-top: 6px;">
        <i class="icon-time color2Text meta__icon"></i> 28 aug 2023
      </span>
      <span class="meta__item float--left" style="margin-top: 6px;">
        <i class="icon-eye-open color2Text meta__icon"></i> 718 <span class="hidden--mobile"> visningar</span>
      </span>
    </small>
  </div>

  <div id="anchor-comments"></div>
  <p class="link-color--underline">
    Vi ar anmalda till cupen i Alvik den 12-13 april.<br>
    Samling kl 08:30 vid Aspuddens IP.
  </p>

  <div class="author">
    <img class="author__image" src="https://example.cdn.laget.se/avatar.png">
    <span class="author__name">Johan Andersson</span>
    <span class="author__role">Tränare</span>
  </div>

  <div class="socialShare__outer--borderTop">
    <!-- share buttons -->
  </div>
</div>
"""

ARTICLE_NO_AUTHOR_HTML = """\
<div class="box__content padding--full text--breakWord">
  <h3 class="headline">Infomeddelande</h3>

  <div class="hidden--mobile">
    <small class="meta--singleLine">
      <span class="meta__item float--left tooltip tooltipstered">
        <i class="icon-time color2Text meta__icon"></i> 5 mar 2024
      </span>
      <span class="meta__item float--left">
        <i class="icon-eye-open color2Text meta__icon"></i> 42 <span class="hidden--mobile"> visningar</span>
      </span>
    </small>
  </div>

  <div id="anchor-comments"></div>
  <p class="link-color--underline">
    Kort meddelande utan forfattare.
  </p>

  <div class="socialShare__outer--borderTop">
    <!-- share buttons -->
  </div>
</div>
"""

ARTICLE_HTML_ENTITIES = """\
<div class="box__content padding--full text--breakWord">
  <h3 class="headline">Mål &amp; Assist: Säsongen 2023/24</h3>

  <div class="hidden--mobile">
    <small class="meta--singleLine">
      <span class="meta__item float--left tooltip tooltipstered">
        <i class="icon-time color2Text meta__icon"></i> 15 jun 2024
      </span>
      <span class="meta__item float--left">
        <i class="icon-eye-open color2Text meta__icon"></i> 100 <span class="hidden--mobile"> visningar</span>
      </span>
    </small>
  </div>

  <div id="anchor-comments"></div>
  <p class="link-color--underline">Bra säsong!</p>

  <div class="author">
    <span class="author__name">Åsa &amp; Erik</span>
  </div>

  <div class="socialShare__outer--borderTop"></div>
</div>
"""

COMMENTS_HTML = """\
<div id="comments" class="box">
  <ul id="news-comment-list" class="commentList--clean">

    <li id="comment-111" class="commentList__itemInner padding">
      <div class="commentList__content--withAvatar">
        <span class="commentList__time float--right tooltip tooltipstered">15 jun 2019</span>
        <b class="commentList__name">Maria Nilsson</b>
        <p class="commentList__text">
          Bra, vi kommer!
        </p>
      </div>
    </li>

    <li id="comment-222" class="commentList__itemInner padding">
      <div class="commentList__content--withAvatar">
        <span class="commentList__time float--right tooltip tooltipstered">28 aug 2023</span>
        <b class="commentList__name">Erik Johansson</b>
        <p class="commentList__text">
          Vi ocksa!
          <img class="emoji__text" src="https://example.cdn.laget.se/soccer.png">
        </p>
      </div>
    </li>

    <li id="comment-333" class="commentList__itemInner padding">
      <div class="commentList__content--withAvatar">
        <span class="commentList__time float--right tooltip tooltipstered">5 mar 2024</span>
        <b class="commentList__name">Anna Svensson</b>
        <p class="commentList__text">Sista hemma matchen!</p>
      </div>
    </li>

  </ul>
</div>
"""

ARTICLE_WITH_COMMENTS_HTML = ARTICLE_HTML + COMMENTS_HTML

NO_COMMENTS_HTML = """\
<div id="comments" class="box">
  <!-- no ul#news-comment-list present -->
</div>
"""

EMPTY_COMMENT_LIST_HTML = """\
<ul id="news-comment-list" class="commentList--clean">
</ul>
"""


# ---------------------------------------------------------------------------
# fetch_article
# ---------------------------------------------------------------------------

class TestFetchArticle:
    def test_fetch_article_calls_endpoint(self):
        session = MagicMock()
        resp = MagicMock()
        resp.text = ARTICLE_HTML
        resp.raise_for_status = MagicMock()
        session.get.return_value = resp

        result = fetch_article(session, "TestTeam", "9876")
        session.get.assert_called_once()
        assert "/TestTeam/News/9876" in session.get.call_args[0][0]
        assert result["id"] == "9876"
        assert result["title"] == "Cupen i Alvik 12-13 april"


# ---------------------------------------------------------------------------
# _parse_article
# ---------------------------------------------------------------------------

class TestParseArticle:
    def test_title(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert result["title"] == "Cupen i Alvik 12-13 april"

    def test_author(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert result["author"] == "Johan Andersson"

    def test_date(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert result["date"] == "2023-08-28T00:00:00"

    def test_view_count(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert result["view_count"] == 718

    def test_body_br_converted_to_newlines(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert "Vi ar anmalda till cupen i Alvik den 12-13 april." in result["body"]
        assert "\n" in result["body"]
        assert "Samling kl 08:30 vid Aspuddens IP." in result["body"]

    def test_body_stripped_of_html(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert "<" not in result["body"]

    def test_team_slug_preserved(self):
        result = _parse_article(ARTICLE_HTML, "MyTeam-Slug", "9876")
        assert result["team_slug"] == "MyTeam-Slug"

    def test_id_as_string(self):
        result = _parse_article(ARTICLE_HTML, "TeamSlug", 9876)
        assert result["id"] == "9876"

    def test_team_is_none(self):
        # team name resolution happens in CLI layer, not parser
        result = _parse_article(ARTICLE_HTML, "TeamSlug", "9876")
        assert result["team"] is None

    def test_no_author_returns_none(self):
        result = _parse_article(ARTICLE_NO_AUTHOR_HTML, "TeamSlug", "1111")
        assert result["author"] is None

    def test_no_author_body_still_parsed(self):
        result = _parse_article(ARTICLE_NO_AUTHOR_HTML, "TeamSlug", "1111")
        assert result["body"] is not None
        assert "Kort meddelande utan forfattare" in result["body"]

    def test_html_entities_in_title_unescaped(self):
        result = _parse_article(ARTICLE_HTML_ENTITIES, "TeamSlug", "2222")
        assert result["title"] == "Mål & Assist: Säsongen 2023/24"

    def test_html_entities_in_author_unescaped(self):
        result = _parse_article(ARTICLE_HTML_ENTITIES, "TeamSlug", "2222")
        assert result["author"] == "Åsa & Erik"

    def test_comments_returned(self):
        result = _parse_article(ARTICLE_WITH_COMMENTS_HTML, "TeamSlug", "9876")
        assert len(result["comments"]) == 3

    def test_no_comments_returns_empty_list(self):
        result = _parse_article(ARTICLE_HTML + NO_COMMENTS_HTML, "TeamSlug", "9876")
        assert result["comments"] == []


# ---------------------------------------------------------------------------
# _parse_comments
# ---------------------------------------------------------------------------

class TestParseComments:
    def test_parses_all_comments_with_correct_fields(self):
        result = _parse_comments(COMMENTS_HTML)
        assert len(result) == 3
        assert result[0]["author"] == "Maria Nilsson"
        assert result[0]["date"] == "2019-06-15T00:00:00"
        assert result[0]["text"] == "Bra, vi kommer!"

    def test_emoji_img_stripped_from_comment_text(self):
        result = _parse_comments(COMMENTS_HTML)
        assert "<img" not in result[1]["text"]
        assert "Vi ocksa!" in result[1]["text"]

    def test_empty_comment_list_returns_empty(self):
        result = _parse_comments(EMPTY_COMMENT_LIST_HTML)
        assert result == []

    def test_no_comment_ul_returns_empty(self):
        result = _parse_comments(NO_COMMENTS_HTML)
        assert result == []

    def test_order_is_ascending(self):
        result = _parse_comments(COMMENTS_HTML)
        dates = [c["date"] for c in result]
        assert dates == sorted(dates)
