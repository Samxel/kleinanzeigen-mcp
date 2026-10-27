"""Raw ads cut down to the fields the model needs."""

import html
import re
from typing import Optional

from . import api


def image_urls(pictures: dict) -> list[str]:
    urls = []
    for pic in (pictures or {}).get("picture", []):
        for link in pic.get("link", []):
            if link.get("rel") == "large":
                urls.append(link["href"])
                break
    return urls


def clean_description(value: Optional[str]) -> str:
    """Ad descriptions come as HTML (``<br />`` line breaks, entities);
    render them as plain, readable text."""
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def ad_url(ad_id) -> Optional[str]:
    """The ad's web page. The site finds an ad by its id alone, so the title
    slug and category in the link the API returns are only extra tokens."""
    return f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}" if ad_id else None


def _price(ad: dict) -> dict:
    """The price fields worth sending: the currency only when it is not EUR,
    and the price type only when it says more than "this is the price" (VB,
    zu verschenken, ...)."""
    price = ad.get("price") or {}
    currency = api.unwrap(api.unwrap(price.get("currency-iso-code")))
    price_type = api.unwrap(price.get("price-type"))
    return {
        "price_amount": api.unwrap(price.get("amount")),
        "price_currency": currency if currency != "EUR" else None,
        "price_type": price_type if price_type != "SPECIFIED_AMOUNT" else None,
    }


def _shipping(ad: dict) -> list[str]:
    return [o["id"] for o in (ad.get("shipping-options") or {}).get("shipping-option", [])]


def summarize_ad_hit(ad: dict) -> dict:
    address = ad.get("ad-address") or {}
    features = (ad.get("features-active") or {}).get("feature-active", [])
    return {
        "id": ad.get("id"),
        "title": html.unescape(api.unwrap(ad.get("title")) or ""),
        "description": clean_description(api.unwrap(ad.get("description"))),
        **_price(ad),
        "location": api.unwrap(address.get("state")),
        "zip_code": api.unwrap(address.get("zip-code")),
        "ships": bool(_shipping(ad)),
        "category_id": (ad.get("category") or {}).get("id"),
        "seller_id": api.unwrap(ad.get("user-id")),
        "store_title": api.unwrap(ad.get("store-title")),
        "seller_account_type": api.unwrap(ad.get("seller-account-type")),
        "is_top_ad": any(f.get("name") == "TOPAD" for f in features) or None,
        "start_date": (api.unwrap(ad.get("start-date-time")) or "")[:16] or None,
        # the photos themselves are in get_ad_images
        "image_count": len((ad.get("pictures") or {}).get("picture", [])),
        "url": ad_url(ad.get("id")),
    }


def _summarize_attributes(attributes: dict) -> dict:
    """Flatten an ad's `attributes.attribute[]` list into {label: value}, e.g.
    {"Zustand": "Neu"}. The labels are what the ad page shows; the filter keys
    behind them ("pc_zubehoer_software.condition") come from
    get_category_filters."""
    out = {}
    for attr in (attributes or {}).get("attribute", []):
        values = attr.get("value") or []
        label = ", ".join(v.get("localized-label", v.get("value", "")) for v in values)
        out[attr.get("localized-label") or attr.get("name")] = label
    return out


def summarize_ad_detail(ad: dict) -> dict:
    address = ad.get("ad-address") or {}
    category = ad.get("category") or {}
    ad_type = api.unwrap(ad.get("ad-type"))
    status = api.unwrap(ad.get("ad-status"))
    return {
        "id": ad.get("id"),
        "title": html.unescape(api.unwrap(ad.get("title")) or ""),
        "description": clean_description(api.unwrap(ad.get("description"))),
        # only the unusual cases: a wanted ad, or one no longer active
        "ad_type": ad_type if ad_type != "OFFERED" else None,
        "ad_status": status if status != "ACTIVE" else None,
        **_price(ad),
        "location": api.unwrap(address.get("state")),
        "zip_code": api.unwrap(address.get("zip-code")),
        "category_id": category.get("id"),
        "category_name": api.unwrap(category.get("localized-name")),
        "seller_id": api.unwrap(ad.get("user-id")),
        "seller_name": api.unwrap(ad.get("contact-name")),
        "seller_account_type": api.unwrap(ad.get("seller-account-type")),
        "seller_rating": api.unwrap((ad.get("user-rating") or {}).get("averageRating")),
        "attributes": _summarize_attributes(ad.get("attributes")),
        "shipping_options": _shipping(ad),
        "buy_now": (ad.get("buy-now") or {}).get("selected") == "true" or None,
        "start_date": (api.unwrap(ad.get("start-date-time")) or "")[:16] or None,
        "image_count": len(image_urls(ad.get("pictures"))),
        "url": ad_url(ad.get("id")),
    }
