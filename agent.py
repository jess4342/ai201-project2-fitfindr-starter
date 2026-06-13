"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import (
    compare_price,
    create_fit_card,
    get_trend_insight,
    search_listings,
    suggest_outfit,
)
from utils.data_loader import load_listings


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "trend_insight": None,        # trend information for the selected item
        "price_assessment": None,     # assessment from comparable listings
        "fallback_note": None,        # explanation of any retry / loosened search
        "style_profile": None,        # user style memory used across interactions
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


STYLE_PROFILE: dict = {
    "preferred_styles": [],
    "notes": "",
}


def _build_style_profile(query: str, selected_item: dict) -> dict:
    """Create a simple style preference record from the query and selected item."""
    style_keywords = [
        "vintage",
        "y2k",
        "grunge",
        "cottagecore",
        "streetwear",
        "boho",
        "minimal",
        "retro",
        "punk",
        "athleisure",
    ]
    preferences = []
    lowered_query = query.lower()
    for keyword in style_keywords:
        if keyword in lowered_query and keyword not in preferences:
            preferences.append(keyword)

    item_tags = [str(tag).lower() for tag in selected_item.get("style_tags", []) if isinstance(tag, str)]
    for tag in item_tags:
        if tag not in preferences:
            preferences.append(tag)

    if not preferences and item_tags:
        preferences = item_tags[:3]

    note = (
        "The user seems to like "
        + ", ".join(preferences)
        + ". "
        if preferences
        else ""
    )
    return {
        "preferred_styles": preferences[:4],
        "notes": note,
    }


def _search_with_fallback(
    description: str,
    size: str | None,
    max_price: float | None,
    require_color: bool = False,
    require_style: bool = False,
) -> tuple[list[dict], str | None]:
    """Retry a zero-result search with loosened constraints and explain what changed."""
    if size is None and max_price is None:
        return [], None

    # helper to keep results in the same general category as the original query
    def _filter_by_category(results: list[dict], desc: str) -> list[dict]:
        terms = re.findall(r"\w+", desc.lower())
        # only consider tokens that are likely to represent categories
        CATEGORY_KEYWORDS = {
            "shoe",
            "shoes",
            "boot",
            "boots",
            "sneaker",
            "sneakers",
            "sandals",
            "heel",
            "heels",
            "dress",
            "gown",
            "top",
            "tops",
            "tee",
            "tshirt",
            "t-shirt",
            "shirt",
            "shirts",
            "jean",
            "jeans",
            "bottom",
            "bottoms",
            "short",
            "shorts",
            "skirt",
            "coat",
            "jacket",
            "outerwear",
        }
        category_terms = [t for t in terms if t in CATEGORY_KEYWORDS]
        if not category_terms:
            return []
        filtered = []
        for listing in results:
            listing_cat = str(listing.get("category", "")).lower()
            title = str(listing.get("title", "")).lower()
            desc_text = str(listing.get("description", "")).lower()
            if not (listing_cat or title or desc_text):
                continue

            matched = False
            for term in category_terms:
                if not term:
                    continue
                # direct category substring match
                if term in listing_cat or listing_cat in term:
                    matched = True
                    break
                # plural/singular heuristic
                if term.rstrip("s") in listing_cat or listing_cat in term.rstrip("s"):
                    matched = True
                    break
                # check title/description for the category term
                if term in title or term in desc_text:
                    matched = True
                    break
                # map common synonyms: boots -> shoes/boot
                if term in {"boot", "boots"} and ("shoe" in listing_cat or "boot" in listing_cat or "shoe" in title or "boot" in title):
                    matched = True
                    break

            if matched:
                filtered.append(listing)
        return filtered

    # 1) try removing size but keep the same category if possible
    if size is not None:
        relaxed_results = search_listings(
            description, size=None, max_price=max_price, require_color=require_color, require_style=require_style
        )
        cat_filtered = _filter_by_category(relaxed_results, description)
        if cat_filtered:
            return (
                cat_filtered,
                f"No exact match was found for size {size}. I broadened the search by removing the size filter but kept the item's category.",
            )
        if relaxed_results:
            # fallback to relaxed results if no category-preserving matches exist
            return (
                relaxed_results,
                f"No exact match was found for size {size}. I broadened the search by removing the size filter.",
            )

    # 2) try loosening the price while keeping category
    if max_price is not None:
        relaxed_price = max(max_price * 2, max_price + 20)
        relaxed_results = search_listings(
            description, size=size, max_price=relaxed_price, require_color=require_color, require_style=require_style
        )
        cat_filtered = _filter_by_category(relaxed_results, description)
        if cat_filtered:
            return (
                cat_filtered,
                f"No exact match was found within ${max_price:.0f}. I loosened the budget to ${relaxed_price:.0f} and kept the item's category.",
            )
        if relaxed_results:
            return (
                relaxed_results,
                f"No exact match was found within ${max_price:.0f}. I loosened the budget to ${relaxed_price:.0f}.",
            )

    # 3) broaden to all sizes and prices but prefer matches in the same category
    relaxed_results = search_listings(
        description, size=None, max_price=None, require_color=require_color, require_style=require_style
    )
    cat_filtered = _filter_by_category(relaxed_results, description)
    if cat_filtered:
        return (
            cat_filtered,
            "No exact match was found with the original filters. I broadened the search to all sizes and prices but kept the category.",
        )
    if relaxed_results:
        return (
            relaxed_results,
            "No exact match was found with the original filters. I broadened the search to all sizes and prices.",
        )

    return [], None


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict, require_color: bool = False, require_style: bool = False) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query into description, size, and max_price.
    description = query.strip()
    size = None
    max_price = None

    size_match = re.search(r"\b(size\s*([XSML]{1,3}|\d+))\b", query, re.IGNORECASE)
    if size_match:
        size_text = size_match.group(2).upper()
        size = size_text
        description = re.sub(re.escape(size_match.group(0)), "", description, flags=re.IGNORECASE)

    price_match = re.search(r"\$(\d+(?:\.\d+)?)|under\s*\$(\d+(?:\.\d+)?)|below\s*\$(\d+(?:\.\d+)?)|\b(\d+(?:\.\d+)?)\s*dollars\b",
                            query, re.IGNORECASE)
    if price_match:
        for group in price_match.groups():
            if group:
                try:
                    max_price = float(group)
                    break
                except ValueError:
                    continue
        description = re.sub(re.escape(price_match.group(0)), "", description, flags=re.IGNORECASE)

    description = re.sub(r"\b(size|under|below|dollars|\$)\b", "", description, flags=re.IGNORECASE).strip()
    description = re.sub(r"\s{2,}", " ", description)

    session["parsed"] = {
        "description": description,
        "size": size,
        "max_price": max_price,
    }

    # Step 3: search listings
    search_results = search_listings(
        description, size=size, max_price=max_price, require_color=require_color, require_style=require_style
    )
    session["search_results"] = search_results
    if not search_results:
        search_results, fallback_note = _search_with_fallback(
            description, size, max_price, require_color=require_color, require_style=require_style
        )
        session["search_results"] = search_results
        session["fallback_note"] = fallback_note
        if not search_results:
            session["error"] = (
                "No listings matched your description, size, and price. "
                "Try broadening your query or removing the size or price filter."
            )
            return session

    # Step 4: choose top result
    session["selected_item"] = session["search_results"][0]

    # Step 5: enrich the result with trends and price context
    session["trend_insight"] = get_trend_insight(session["selected_item"])
    session["price_assessment"] = compare_price(session["selected_item"], load_listings())

    # Step 6: suggest an outfit
    style_profile = STYLE_PROFILE if STYLE_PROFILE.get("preferred_styles") else None
    outfit_suggestion = suggest_outfit(
        session["selected_item"],
        wardrobe,
        trend_context=session["trend_insight"],
        style_profile=style_profile,
    )
    if not isinstance(outfit_suggestion, str) or not outfit_suggestion.strip():
        session["error"] = (
            "I couldn't create outfit suggestions for that item right now. Please try again later."
        )
        return session
    session["outfit_suggestion"] = outfit_suggestion

    # Step 7: create fit card
    fit_card = create_fit_card(session["outfit_suggestion"], session["selected_item"])
    if not isinstance(fit_card, str) or not fit_card.strip():
        session["error"] = (
            "I couldn't create a fit card from that outfit suggestion. Please try again or search for a different item."
        )
        return session
    session["fit_card"] = fit_card

    # Step 8: update style memory
    updated_profile = _build_style_profile(query, session["selected_item"])
    STYLE_PROFILE["preferred_styles"] = updated_profile["preferred_styles"]
    STYLE_PROFILE["notes"] = updated_profile["notes"]
    session["style_profile"] = STYLE_PROFILE.copy()

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
