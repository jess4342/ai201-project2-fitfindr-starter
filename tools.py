"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
    require_color: bool = False,
    require_style: bool = False,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    normalized_query = description.lower().strip()
    if not normalized_query:
        return []

    query_terms = re.findall(r"\w+", normalized_query)
    CLOTHING_TYPE_MAP = {
        "jacket": ["outerwear"],
        "track": ["outerwear"],
        "coat": ["outerwear"],
        "blazer": ["outerwear"],
        "hoodie": ["tops"],
        "sweater": ["tops"],
        "cardigan": ["tops"],
        "shirt": ["tops"],
        "tee": ["tops"],
        "tshirt": ["tops"],
        "top": ["tops"],
        "dress": ["bottoms"],
        "skirt": ["bottoms"],
        "jeans": ["bottoms"],
        "pant": ["bottoms"],
        "pants": ["bottoms"],
        "trousers": ["bottoms"],
        "shorts": ["bottoms"],
        "sneaker": ["shoes"],
        "sneakers": ["shoes"],
        "shoe": ["shoes"],
        "boots": ["shoes"],
        "boot": ["shoes"],
        "bag": ["accessories"],
        "belt": ["accessories"],
        "hat": ["accessories"],
        "scarf": ["accessories"],
    }
    query_category_preferences = []
    for term in query_terms:
        if term in CLOTHING_TYPE_MAP:
            query_category_preferences.extend(CLOTHING_TYPE_MAP[term])

    filtered = []
    # detect simple color and style tokens from the description when requested
    COMMON_COLORS = {
        "black",
        "white",
        "brown",
        "tan",
        "beige",
        "red",
        "blue",
        "green",
        "yellow",
        "pink",
        "purple",
        "gray",
        "grey",
        "navy",
        "olive",
        "gold",
        "silver",
    }
    color_in_query = None
    for c in COMMON_COLORS:
        if re.search(rf"\b{re.escape(c)}\b", normalized_query):
            color_in_query = c
            break

    STYLE_KEYWORDS = {"combat", "chelsea", "ankle", "platform", "chunky", "sneaker", "oxford", "loafer"}
    style_in_query = None
    for s in STYLE_KEYWORDS:
        if re.search(rf"\b{re.escape(s)}\b", normalized_query):
            style_in_query = s
            break

    for listing in listings:
        price = listing.get("price")
        if max_price is not None and price is not None and price > max_price:
            continue

        listing_size = str(listing.get("size", "")).upper().strip()
        if size:
            requested_size = size.upper().strip()
            size_tokens = [token.strip() for token in listing_size.split("/") if token.strip()]
            if requested_size not in size_tokens and requested_size != listing_size:
                continue

        title = str(listing.get("title", "")).lower()
        description_text = str(listing.get("description", "")).lower()
        category = str(listing.get("category", "")).lower()
        brand = str(listing.get("brand") or "").lower()
        tags = " ".join(listing.get("style_tags", [])).lower()

        # enforce color if requested and a color exists in the query
        if require_color and color_in_query:
            colors_field = listing.get("colors") or []
            colors_field = [c.lower() for c in colors_field] if isinstance(colors_field, list) else [str(colors_field).lower()]
            if color_in_query not in colors_field and color_in_query not in title and color_in_query not in description_text:
                continue

        # enforce style token if requested and found in query
        if require_style and style_in_query:
            if style_in_query not in tags and style_in_query not in title and style_in_query not in description_text:
                continue

        score = 0
        for term in query_terms:
            if term in title:
                score += 3
            if term in description_text:
                score += 2
            if term in tags:
                score += 3
            if term == category or term in category.split():
                score += 1
            if brand and (term == brand or term in brand.split()):
                score += 1

        if query_category_preferences:
            for preferred_category in query_category_preferences:
                if listing.get("category", "").lower() == preferred_category:
                    score += 8

            for term in query_terms:
                if term in CLOTHING_TYPE_MAP:
                    if term in title:
                        score += 4
                    if term in description_text:
                        score += 4

        if score > 0:
            filtered.append((score, listing))

    filtered.sort(key=lambda entry: (-entry[0], entry[1].get("price", float("inf"))))
    return [listing for _, listing in filtered]


def compare_price(new_item: dict, listings: list[dict]) -> str:
    """
    Compare the selected item price to similar listings and return a reasoning note.
    """
    category = str(new_item.get("category", "")).lower()
    style_tags = {tag.lower() for tag in new_item.get("style_tags", [])}
    similar = []
    for listing in listings:
        if str(listing.get("category", "")).lower() != category:
            continue
        other_tags = {tag.lower() for tag in listing.get("style_tags", [])}
        if style_tags and style_tags.intersection(other_tags):
            similar.append(listing)
    if not similar:
        similar = [listing for listing in listings if str(listing.get("category", "")).lower() == category]

    if not similar:
        return "I couldn't find comparable items to assess the price right now."

    similar_prices = [listing.get("price", 0.0) for listing in similar if listing.get("price") is not None]
    if not similar_prices:
        return "I couldn't find comparable prices to assess this item."

    avg_price = sum(similar_prices) / len(similar_prices)
    item_price = new_item.get("price", 0.0)
    price_diff = item_price - avg_price
    percent_diff = (price_diff / avg_price) * 100 if avg_price else 0

    if percent_diff <= -20:
        assessment = "This item is priced strongly below comparable listings, so it looks like a good deal."
    elif percent_diff <= 10:
        assessment = "This item is priced in line with similar listings, so it feels like a reasonable find."
    else:
        assessment = "This item is priced above comparable listings, so it may be a splurge unless you really love it."

    return (
        f"Price comparison: {assessment} "
        f"The average price among {len(similar)} similar items is ${avg_price:.0f}, "
        f"while this one is ${item_price:.0f}."
    )


def get_trend_insight(new_item: dict) -> str:
    """
    Return a short trend insight based on the item's category and style tags.
    """
    style_tags = [tag.lower() for tag in new_item.get("style_tags", []) if isinstance(tag, str)]
    category = str(new_item.get("category", "")).lower()
    trend_map = {
        "vintage": "Vintage and nostalgia-driven pieces are trending now, especially band tees and 90s-inspired silhouettes.",
        "y2k": "Y2K revival is still strong, so playful denim, glittery accessories, and low-rise shapes are in style.",
        "grunge": "Grunge-inspired layering and chunky boots remain popular this season.",
        "cottagecore": "Soft cottagecore layers and flowy textures are currently fashionable among secondhand shoppers.",
        "streetwear": "Bold streetwear silhouettes and logo-focused styling are very on trend right now.",
        "boho": "Boho-inspired texture mixing and earthy tones are trending for casual, worn-in looks.",
    }
    for tag in style_tags:
        if tag in trend_map:
            return trend_map[tag]
    if category in {"shoes", "boots"}:
        return "Comfortable, chunky footwear is trending, so pairing this item with solid boots or sneakers is a strong choice."
    if category in {"tops", "outerwear"}:
        return "Layered tops and statement outerwear are on trend; think easy layering and relaxed fits."
    return "This item is in a style category that is getting attention right now, so lean into its visual mood when styling it."


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict, trend_context: str | None = None, style_profile: dict | None = None) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.
        trend_context: Optional trend information to influence the recommendation.
        style_profile: Optional memory of the user's style preferences.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    items = []
    if isinstance(wardrobe, dict):
        items = wardrobe.get("items") or []
    if not isinstance(items, list):
        items = []

    if items:
        summary_lines = []
        for item in items:
            name = item.get("name", "Unnamed piece")
            category = item.get("category", "piece")
            color = item.get("color") or item.get("colors") or ""
            if isinstance(color, list):
                color = ", ".join(color)
            summary_lines.append(f"- {name} ({category}, {color})".strip())
        wardrobe_summary = "\n".join(summary_lines)
        wardrobe_prompt = (
            "Here are some items from the user's wardrobe:\n" + wardrobe_summary +
            "\n\nUse these pieces to suggest one or two full outfits that include the thrifted item. "
            "Mention which wardrobe pieces to pair with the new item by name, and prefer varied combinations rather than always using the same basics."
        )
    else:
        wardrobe_prompt = (
            "The user has an empty wardrobe. "
            "Give general styling advice for the new item, including the types of pieces, colors, and shoes that would work best."
        )

    style_note = ""
    if style_profile and isinstance(style_profile, dict):
        preferred_styles = style_profile.get("preferred_styles") or []
        notes = style_profile.get("notes") or ""
        if preferred_styles:
            style_note = (
                "The user prefers " + ", ".join(preferred_styles) + ". "
            )
        if notes:
            style_note += notes + " "

    trend_note = ""
    if trend_context:
        trend_note = f"Trend insight: {trend_context} "

    system_message = (
        "You are a helpful fashion stylist. Generate a concise, friendly outfit recommendation "
        "for a thrifted item and the user's existing wardrobe, or general styling advice if the wardrobe is empty. "
        "Keep the response in natural language and mention the focal piece clearly."
    )

    user_message = (
        f"Thrift item: {new_item.get('title', 'Unknown item')}\n"
        f"Category: {new_item.get('category', 'unknown')}\n"
        f"Price: ${new_item.get('price', 'unknown')}\n"
        f"Platform: {new_item.get('platform', 'unknown')}\n"
        f"Description: {new_item.get('description', '')}\n\n"
        f"{wardrobe_prompt}\n\n"
        f"{style_note}{trend_note}"
        "Use the style profile and trend information to make the outfit feel current and aligned with the user's preferences."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        model="llama-3.3-70b-versatile",
        temperature=0.9,
        max_tokens=300,
    )

    choice = getattr(response, "choices", [])
    if not choice:
        return "I couldn't create outing advice right now. Please try again later."

    content = getattr(choice[0].message, "content", None)
    return str(content).strip() if content else "I couldn't create outing advice right now. Please try again later."


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return (
            "I couldn't create a fit card because the outfit suggestion was unavailable. "
            "Please try again or search for a different item."
        )

    system_message = (
        "You are a content writer for social outfit captions. Write a short 2-4 sentence caption that feels authentic, "
        "mentions the item name, price, and platform naturally, and captures the outfit vibe in specific terms. "
        "Avoid sounding like a product description."
    )

    user_message = (
        f"Item: {new_item.get('title', 'Unknown item')}\n"
        f"Price: ${new_item.get('price', 'unknown')}\n"
        f"Platform: {new_item.get('platform', 'unknown')}\n"
        f"Outfit advice: {outfit.strip()}\n"
        "Write a 2-4 sentence social caption that feels casual and shareable."
    )

    client = _get_groq_client()
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        model="llama-3.3-70b-versatile",
        temperature=1.0,
        max_tokens=200,
    )

    choice = getattr(response, "choices", [])
    if not choice:
        return (
            "I couldn't create a fit card from that outfit suggestion. "
            "Please try again or search for a different item."
        )

    content = getattr(choice[0].message, "content", None)
    caption = str(content).strip() if content else ""
    if not caption:
        return (
            "I couldn't create a fit card from that outfit suggestion. "
            "Please try again or search for a different item."
        )
    return caption
