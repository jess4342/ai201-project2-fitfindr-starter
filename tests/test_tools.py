import pytest

from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe


def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_suggest_outfit_empty_wardrobe():
    new_item = {
        "title": "Vintage graphic tee",
        "category": "tops",
        "price": 25.0,
        "platform": "depop",
        "description": "A faded band tee",
        "size": "M",
        "style_tags": ["vintage", "graphic"],
    }
    outfit = suggest_outfit(new_item, get_empty_wardrobe())
    assert isinstance(outfit, str)
    assert outfit.strip() != ""


def test_create_fit_card_empty_outfit():
    caption = create_fit_card("", {"title": "Vintage graphic tee", "price": 25.0, "platform": "depop"})
    assert isinstance(caption, str)
    assert "couldn't create a fit card" in caption.lower()


def test_create_fit_card_returns_caption():
    caption = create_fit_card(
        "Pair this tee with black jeans, a denim jacket, and chunky sneakers.",
        {"title": "Vintage graphic tee", "price": 25.0, "platform": "depop"},
    )
    assert isinstance(caption, str)
    assert caption.strip() != ""
