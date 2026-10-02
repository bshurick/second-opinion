"""spending: normalize card and bank export rows into the spending transaction contract.

Reads one JSON object from stdin and writes one JSON object to stdout:

    python spendnormalize.py < input.json

Exit code is 0 on success or 2 on invalid input (``{"error": "..."}``).

Input JSON contract (stdin)::

    {"source": "csv" | "ofx" | "rows",        # required
     "account_id": "chase-sapphire-1234",     # required
     "account_kind": "card" | "checking" | "savings",   # required
     "rows": [ {...}, ... ],                  # csv: one object per data row keyed by header text
                                               # rows: one canonical transaction object per row
                                               # (see below)
     "ofx_text": "...",                       # ofx: the whole file as text
     "preset": "amex" | "chase-card" | ...,   # csv: optional; detected from the headers otherwise
     "mapping": {"date": ..., "post_date": ..., "description": ..., "amount": ...,
                 "debit": ..., "credit": ..., "category": ..., "type": ...,
                 "sign": "charges_negative" | "charges_positive"},   # csv: optional ad-hoc preset
     "source_kind": "receipt" | "amazon-chat" | ...,   # rows: required; labels the row source
     "rules": {"categories": [...], "merchants": [...], "transfers": [...], "ignore": [...]},
     "source_name": "activity.csv"}           # stamped into source_id

A ``rows`` row is a canonical transaction, not a raw export line -- it is meant for a
transcribed or tool-produced charge (a chat-imported order, a scanned receipt, a manual
entry) rather than a bank/card export, which goes through ``csv`` or ``ofx`` instead::

    {"date": "2026-09-08",                    # required; any format parse_date understands
     "description": "Grocery Order (15 items)",   # required
     "amount": -66.12,                        # required; account view, spend negative
     "post_date": "2026-09-09",                # optional
     "merchant": "Amazon",                    # optional; skips merchant normalization
     "category": "Groceries",                 # optional; taxonomy name, skips rule/keyword
                                               # categorization
     "detail": "Groceries/Amazon Fresh",       # optional; see detail paths below
     "items": [ {...}, ... ]}                 # optional; see items below

Output JSON contract (stdout)::

    {"preset": "amex" | "mapping" | "ofx" | "rows",
     "account_kind": ...,
     "transactions": [                        # date order, then input order
       {"account_id", "date": "YYYY-MM-DD", "post_date": "YYYY-MM-DD" | null,
        "amount": -54.12,                     # account view: spend negative, credits positive
        "description": "<raw>", "merchant": "<normalized>",
        "merchant_source": "transcribed" | null,   # "transcribed" when the row supplied merchant
        "category": <taxonomy>,
        "category_source": "rule" | "keyword" | "issuer" | "transcribed" | "none",
        "issuer_category": "<issuer label>" | null,
        "type": "purchase" | "refund" | "payment" | "transfer" | "fee" | "interest" |
                "deposit" | "withdrawal" | "other",
        "transfer": bool, "fitid": "..." | null, "source_id": "<source_name>:<row>",
        "source": "preset:<name>" | "mapping" | "ofx" | "transcribed:<source_kind>",
        "detail": "Groceries/Amazon Fresh" | null, "detail_source": "transcribed" | "rule" | null,
        "items": [ {...}, ... ]}],             # present only when the row carried items
     "count": N, "skipped": [{"row": n, "reason": "..."}],
     "date_range": {"start", "end"} | null,
     "categories": {<category>: count}, "uncategorized": N, "transfers_marked": N}

Taxonomy (fixed): the 22 spend categories in ``SPEND_CATEGORIES`` plus Income, Transfer
and Uncategorized. Categorization order: an explicit ``category`` on a ``rows`` row (wins
outright, ``category_source = "transcribed"``), user category rule, fee/interest keyword,
Amazon merchant, issuer category map, built-in merchant keyword, Uncategorized.
Merchant normalization: uppercase, strip processor prefixes (SQ *, TST*, PAYPAL *, ...),
drop store numbers, reference codes, phone numbers and URLs, drop a trailing US city and
state, title-case with a brand exception list, then built-in canonical names, then the
user's merchant rules -- unless the row supplies its own ``merchant``, which is used as-is
and marked ``merchant_source = "transcribed"``. Transfers: keyword patterns (card payments,
autopay, transfers, Zelle, Venmo, brokerage funding) or a user transfer rule;
``match_transfers`` (Task 4) adds cross-account matching. Income: payroll keywords, or any
non-transfer credit on a checking or savings account -- but a user category rule is checked
first and wins even on a bank credit (a rule naming Transfer is honored as a real transfer,
not a silent no-op).

Detail paths: ``detail`` is a slash-separated path such as ``"Groceries/Amazon Fresh"`` or
``"Home/Repairs/Caulk"``, at most ``MAX_DETAIL_DEPTH`` (5) levels deep, with no empty
segment; each segment is stripped of surrounding whitespace. It is meant to drill down
*within* a transaction's category (e.g. a specific store or project under "Groceries" or
"Housing") rather than to re-state the category itself. A transcribed ``detail`` on a
``rows`` row wins outright (``detail_source = "transcribed"``); otherwise a matching
category rule's own ``detail`` fills it in (``detail_source = "rule"``); a transaction with
neither has ``detail: null``.

Items: ``items`` itemizes a single charge into its line items, each
``{"name": str, "amount": float, "category": <taxonomy>, "detail": str | null,
"quantity": int | null, "source": str | null}``. Amounts are signed the same way as the
transaction (spend negative); an item list may not have the opposite sign from the
transaction, and the sum of item amounts may not exceed the transaction amount in magnitude
by more than $0.01 -- the remainder (transaction amount minus the sum of items) is left
implicit rather than requiring a matching "everything else" line.

``apply_rules`` re-derives merchant, category, type, transfer and detail from the current
rules on every row, but never discards what a ``rows`` row transcribed: a transcribed
category, detail or merchant (``*_source == "transcribed"``) is preserved through the
rebuild rather than re-normalized from the raw description, and ``items`` and ``source``
pass through untouched. A rule-derived ``detail`` (``detail_source == "rule"``) does
refresh from the current rules, including clearing back to null when no rule matches
anymore.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime

TAXONOMY = (
    "Groceries",
    "Dining",
    "Coffee",
    "Transport",
    "Fuel",
    "Auto",
    "Housing",
    "Utilities",
    "Subscriptions",
    "Shopping",
    "Amazon",
    "Health",
    "Insurance",
    "Travel",
    "Entertainment",
    "Education",
    "Kids",
    "Pets",
    "Gifts and Charity",
    "Personal Care",
    "Fees and Interest",
    "Taxes and Government",
    "Income",
    "Transfer",
    "Uncategorized",
)
SPEND_CATEGORIES = TAXONOMY[:22]
MAX_DETAIL_DEPTH = 5


def validate_detail(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("detail must be a string path such as Home/Repairs")
    if not raw.strip():
        return None
    segments = [s.strip() for s in raw.split("/")]
    if any(not s for s in segments):
        raise ValueError("detail path has an empty segment")
    if len(segments) > MAX_DETAIL_DEPTH:
        raise ValueError(f"detail path deeper than {MAX_DETAIL_DEPTH} levels")
    return "/".join(segments)


def validate_items(items: object, transaction_amount: float | None = None) -> list[dict]:
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    out = []
    for i, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"item {i} must be an object")
        amount = parse_money(raw.get("amount"))
        if amount is None:
            raise ValueError(f"item {i}: amount is required")
        category = raw.get("category")
        if category not in TAXONOMY:
            raise ValueError(f"item {i}: category must be one of the taxonomy names")
        quantity = raw.get("quantity")
        if quantity is not None and (
            isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0
        ):
            raise ValueError(f"item {i}: quantity must be a non-negative integer")
        out.append(
            {
                "name": str(raw.get("name") or "").strip() or f"item {i}",
                "amount": round(amount, 2),
                "category": category,
                "detail": validate_detail(raw.get("detail")),
                "quantity": quantity,
                "source": str(raw["source"]) if raw.get("source") else None,
            }
        )
    if transaction_amount is not None and out:
        total = sum(it["amount"] for it in out)
        if total and transaction_amount and (total > 0) != (transaction_amount > 0):
            raise ValueError("items and the transaction have opposite signs")
        if abs(total) > abs(transaction_amount) + 0.01:
            raise ValueError(
                f"items total {total:.2f} exceeds the transaction amount {transaction_amount:.2f}"
            )
    return out


# (regex on the uppercased description or normalized merchant, canonical merchant or None, category)
BUILTIN_MERCHANTS: list[tuple[str, str | None, str]] = [
    (r"^(AMZN|AMAZON)", "Amazon", "Amazon"),
    (r"^COSTCO GAS", "Costco Gas", "Fuel"),
    (r"^COSTCO", "Costco", "Groceries"),
    (r"^SAFEWAY FUEL|^FRED MEYER FUEL|^QFC FUEL", None, "Fuel"),
    (r"^SAFEWAY", "Safeway", "Groceries"),
    (r"^QFC", "QFC", "Groceries"),
    (r"^PCC ", "PCC", "Groceries"),
    (r"^TRADER JOE", "Trader Joe's", "Groceries"),
    (r"^(WHOLEFDS|WHOLE FOODS)", "Whole Foods", "Groceries"),
    (r"^KROGER", "Kroger", "Groceries"),
    (r"^FRED MEYER", "Fred Meyer", "Groceries"),
    (r"^METROPOLITAN MARKET", "Metropolitan Market", "Groceries"),
    (r"^H MART|^HMART", "H Mart", "Groceries"),
    (r"^UWAJIMAYA", "Uwajimaya", "Groceries"),
    (r"^99 RANCH", "99 Ranch Market", "Groceries"),
    (r"^SPROUTS", "Sprouts", "Groceries"),
    (r"^(IC\* ?INSTACART|INSTACART)", "Instacart", "Groceries"),
    (r"^7-?ELEVEN", "7-Eleven", "Shopping"),
    (r"^(WALMART|WAL-MART)", "Walmart", "Shopping"),
    (r"^TARGET", "Target", "Shopping"),
    (r"^(THE )?HOME DEPOT", "Home Depot", "Shopping"),
    (r"^LOWES|^LOWE'S", "Lowe's", "Shopping"),
    (r"^IKEA", "IKEA", "Shopping"),
    (r"^BEST BUY", "Best Buy", "Shopping"),
    (r"^REI ", "REI", "Shopping"),
    (r"^NORDSTROM", "Nordstrom", "Shopping"),
    (r"^ETSY", "Etsy", "Shopping"),
    (r"^EBAY", "eBay", "Shopping"),
    (r"^APPLE STORE|^APPLE\.COM(?!/BILL)", "Apple Store", "Shopping"),
    (r"^APPLE\.COM/BILL", "Apple.com/bill", "Subscriptions"),
    (r"^NETFLIX", "Netflix", "Subscriptions"),
    (r"^SPOTIFY", "Spotify", "Subscriptions"),
    (r"^HULU", "Hulu", "Subscriptions"),
    (r"^DISNEY ?PLUS|^DISNEYPLUS", "Disney+", "Subscriptions"),
    (r"^HBO|^MAX\.COM", "Max", "Subscriptions"),
    (r"^YOUTUBE|^GOOGLE \*YOUTUBE", "YouTube", "Subscriptions"),
    (r"^GOOGLE \*?(ONE|STORAGE)|^GOOGLE ONE", "Google One", "Subscriptions"),
    (r"^GOOGLE", "Google", "Subscriptions"),
    (r"^ICLOUD", "iCloud", "Subscriptions"),
    (r"^ADOBE", "Adobe", "Subscriptions"),
    (r"^GITHUB", "GitHub", "Subscriptions"),
    (r"^OPENAI|^CHATGPT", "OpenAI", "Subscriptions"),
    (r"^ANTHROPIC|^CLAUDE\.AI", "Anthropic", "Subscriptions"),
    (r"^MICROSOFT", "Microsoft", "Subscriptions"),
    (r"^DROPBOX", "Dropbox", "Subscriptions"),
    (r"^NYTIMES|^NEW YORK TIMES", "New York Times", "Subscriptions"),
    (r"^AUDIBLE", "Audible", "Subscriptions"),
    (r"^KINDLE", "Kindle", "Subscriptions"),
    (r"^PATREON", "Patreon", "Subscriptions"),
    (r"^PELOTON", "Peloton", "Health"),
    (r"^STARBUCKS", "Starbucks", "Coffee"),
    (r"^PEET", "Peet's", "Coffee"),
    (r"^BLUE BOTTLE", "Blue Bottle Coffee", "Coffee"),
    (r"^DUTCH BROS", "Dutch Bros", "Coffee"),
    (r"\bCOFFEE\b|\bESPRESSO\b|\bCAFE\b", None, "Coffee"),
    (r"^UBER\s*\*?\s*EATS|^UBER EATS", "Uber Eats", "Dining"),
    (r"^DOORDASH|^DD \*DOORDASH", "DoorDash", "Dining"),
    (r"^GRUBHUB", "Grubhub", "Dining"),
    (r"^UBER", "Uber", "Transport"),
    (r"^LYFT", "Lyft", "Transport"),
    (r"^CHIPOTLE", "Chipotle", "Dining"),
    (r"^MCDONALD", "McDonald's", "Dining"),
    (r"^SUBWAY", "Subway", "Dining"),
    (r"^PANERA", "Panera", "Dining"),
    (r"^DOMINO", "Domino's", "Dining"),
    (r"^IN-N-OUT", "In-N-Out Burger", "Dining"),
    (
        r"\b(RESTAURANT|PIZZA|SUSHI|RAMEN|TAQUERIA|BISTRO|GRILL|BURGERS?|THAI|PHO|BAKERY|"
        r"BREWING|BREWERY|TAVERN|BAR & GRILL)\b",
        None,
        "Dining",
    ),
    (r"^SHELL", "Shell", "Fuel"),
    (r"^CHEVRON", "Chevron", "Fuel"),
    (r"^76 |^76-", "76", "Fuel"),
    (r"^ARCO", "Arco", "Fuel"),
    (r"^EXXON|^MOBIL", "Exxon Mobil", "Fuel"),
    (r"^BP ", "BP", "Fuel"),
    (r"^TEXACO", "Texaco", "Fuel"),
    (r"\bFUEL\b|\bGAS STATION\b", None, "Fuel"),
    (r"^(COMCAST|XFINITY)", "Xfinity", "Utilities"),
    (r"^(TMOBILE|T-MOBILE)", "T-Mobile", "Utilities"),
    (r"^VERIZON", "Verizon", "Utilities"),
    (r"^AT&T|^ATT\*", "AT&T", "Utilities"),
    (r"^CENTURYLINK|^LUMEN", "CenturyLink", "Utilities"),
    (r"^WAVE BROADBAND|^ASTOUND", "Astound", "Utilities"),
    (r"^ALASKA AIR", "Alaska Airlines", "Travel"),
    (r"^DELTA AIR", "Delta Air Lines", "Travel"),
    (r"^UNITED AIR|^UNITED 016", "United Airlines", "Travel"),
    (r"^AMERICAN AIR", "American Airlines", "Travel"),
    (r"^SOUTHWEST", "Southwest Airlines", "Travel"),
    (r"^JETBLUE", "JetBlue", "Travel"),
    (r"^AIRBNB", "Airbnb", "Travel"),
    (r"^VRBO", "Vrbo", "Travel"),
    (r"^MARRIOTT", "Marriott", "Travel"),
    (r"^HILTON", "Hilton", "Travel"),
    (r"^HYATT", "Hyatt", "Travel"),
    (r"^EXPEDIA|^HOTELS\.COM|^BOOKING\.COM", None, "Travel"),
    (r"^AMTRAK", "Amtrak", "Travel"),
    (
        r"^HERTZ|^AVIS|^ENTERPRISE RENT|^NATIONAL CAR|RENT[- ]A[- ]CAR|^U-?HAUL|"
        r"^BUDGET RENT|^SIXT|^THRIFTY|^DOLLAR RENT",
        None,
        "Travel",
    ),
    (r"\bHOTEL\b|\bAIRLINES?\b|\bAIRWAYS\b", None, "Travel"),
    (r"\bPARKING\b|^PAYBYPHONE|^SPOTHERO|^DIAMOND PARKING", None, "Transport"),
    (r"^LIME|^BIRD ", None, "Transport"),
    (r"^LES SCHWAB|^DISCOUNT TIRE|^JIFFY LUBE|^FIRESTONE|^PEP BOYS", None, "Auto"),
    (r"^GEICO|^PROGRESSIVE|^STATE FARM|^ALLSTATE|^USAA INSURANCE", None, "Auto"),
    (r"^WA DOL|^DEPT OF LICENSING", "WA Department of Licensing", "Auto"),
    (r"^BMW FINANCIAL|^TOYOTA FINANCIAL|^HONDA FINANCIAL|^ALLY AUTO", None, "Auto"),
    (r"^CVS", "CVS", "Health"),
    (r"^WALGREENS", "Walgreens", "Health"),
    (r"^RITE AID", "Rite Aid", "Health"),
    (r"^KAISER", None, "Health"),
    (r"\bPHARMACY\b|\bDENTAL\b|\bDENTIST\b|\bCLINIC\b|\bMEDICAL\b|\bOPTOMETR", None, "Health"),
    (
        r"^24 HOUR FITNESS|^LA FITNESS|^PLANET FITNESS|^ORANGETHEORY|^EQUINOX|^CROSSFIT",
        None,
        "Health",
    ),
    (r"^AMC |^REGAL|^CINEMARK", None, "Entertainment"),
    (r"^STEAM ?GAMES|^STEAMGAMES|^PLAYSTATION|^NINTENDO|^XBOX", None, "Entertainment"),
    (r"^TICKETMASTER|^STUBHUB|^AXS ", None, "Entertainment"),
    (r"^UDEMY|^COURSERA", None, "Education"),
    (r"^PETCO|^PETSMART|^CHEWY", None, "Pets"),
    (r"\bVETERINAR|\bANIMAL HOSPITAL\b", None, "Pets"),
    (r"^GOFUNDME|^DONORBOX|^RED CROSS|^ACLU|^UNICEF", None, "Gifts and Charity"),
    (r"^(GREAT CLIPS|SUPERCUTS|SPORT CLIPS)|\bSALON\b|\bBARBER", None, "Personal Care"),
    (r"^SEPHORA|^ULTA", None, "Personal Care"),
    (r"^USPS|^UPS |^FEDEX", None, "Shopping"),
    (r"^IRS |^US TREASURY", None, "Taxes and Government"),
    (r"^LEMONADE|^LIBERTY MUTUAL|^FARMERS INS|^SAFECO", None, "Insurance"),
    (r"\bHOA\b|\bRENT\b(?! ?A ?CAR)|\bMORTGAGE\b", None, "Housing"),
    (r"^NELNET|^MOHELA|^NAVIENT|^SALLIE MAE|^GREAT LAKES", None, "Education"),
    (r"^ZOO\b|\bAQUARIUM\b|\bMUSEUM\b", None, "Entertainment"),
    (r"^KINDERCARE|^BRIGHT HORIZONS", None, "Kids"),
]

ISSUER_CATEGORY_MAP: dict[str, str] = {
    # Amex
    "merchandise & supplies-groceries": "Groceries",
    "restaurant-restaurant": "Dining",
    "restaurant-bar & café": "Dining",
    "restaurant-bar & cafe": "Dining",
    "transportation-fuel": "Fuel",
    "transportation-taxis & coach": "Transport",
    "transportation-parking charges": "Transport",
    "travel-airline": "Travel",
    "travel-lodging": "Travel",
    "entertainment-general attractions": "Entertainment",
    "entertainment-theatre & sports": "Entertainment",
    "merchandise & supplies-internet purchase": "Shopping",
    "merchandise & supplies-general retail": "Shopping",
    "merchandise & supplies-department stores": "Shopping",
    "merchandise & supplies-pharmacies": "Health",
    "communications-cable & internet": "Utilities",
    "communications-cellular telephone": "Utilities",
    "business services-other services": "Subscriptions",
    "fees & adjustments-fees & adjustments": "Fees and Interest",
    # Chase
    "groceries": "Groceries",
    "food & drink": "Dining",
    "gas": "Fuel",
    "travel": "Travel",
    "shopping": "Shopping",
    "health & wellness": "Health",
    "bills & utilities": "Utilities",
    "entertainment": "Entertainment",
    "automotive": "Auto",
    "personal": "Personal Care",
    "home": "Shopping",
    "education": "Education",
    "gifts & donations": "Gifts and Charity",
    "fees & adjustments": "Fees and Interest",
    # Apple Card
    "grocery": "Groceries",
    "restaurants": "Dining",
    "transportation": "Transport",
    "health": "Health",
    # Capital One
    "dining": "Dining",
    "merchandise": "Shopping",
    "gas/automotive": "Fuel",
    "health care": "Health",
    "internet": "Utilities",
    "phone/cable": "Utilities",
    "insurance": "Insurance",
    "other travel": "Travel",
    "airfare": "Travel",
    "lodging": "Travel",
    "car rental": "Travel",
    "fee/interest charge": "Fees and Interest",
    # Discover
    "supermarkets": "Groceries",
    "gasoline": "Fuel",
    "travel/ entertainment": "Travel",
    "medical services": "Health",
    "home improvement": "Shopping",
    "government services": "Taxes and Government",
    "fees": "Fees and Interest",
    "interest": "Fees and Interest",
}

TRANSFER_PATTERNS = [
    r"PAYMENT ?-? ?THANK YOU",
    r"PAYMENT RECEIVED",
    r"TRANSFER TO",
    r"TRANSFER FROM",
    r"ONLINE TRANSFER",
    r"\bXFER\b",
    r"ZELLE (TO|FROM|PAYMENT)",
    r"\bVENMO\b",
    r"\bPAYPAL TRANSFER\b",
    r"CASH APP",
    r"CHASE CREDIT CRD",
    r"AMERICAN EXPRESS ACH",
    r"AMEX EPAYMENT",
    r"CAPITAL ONE .*(PMT|PYMT|PAYMENT|AUTOPAY)",
    r"CITI CARD ONLINE",
    r"CITI AUTOPAY",
    r"DISCOVER .*(PAYMENT|E-PAYMENT)",
    r"\bDIRECTPAY\b",
    r"APPLECARD GSBANK",
    r"BANK OF AMERICA .*PAYMENT",
    r"FID BKG SVC",
    r"FIDELITY .*(TRANSFER|EFT)",
    r"ETRADE ACH",
    r"E\*TRADE",
    r"VANGUARD BUY",
    r"SCHWAB .*(TRANSFER|MONEYLINK)",
    r"ROBINHOOD",
    r"WEALTHFRONT",
    r"BETTERMENT",
    r"CREDIT CARD PAYMENT",
    r"CRD PMT",
    r"\bPMT\b.*\bCARD\b",
]
# Weak signals: a real bill can also carry these words. is_transfer only honors a weak match
# when no built-in merchant with a spend category matched the description first.
PAYMENT_PATTERNS = [
    r"\bAUTOPAY\b",
    r"\bAUTO ?PAY\b.*\bPAYMENT\b",
    r"ONLINE PAYMENT",
    r"MOBILE (PAYMENT|PYMT)",
    r"ELECTRONIC PAYMENT",
    r"\bACH PMT\b",
    r"\bACH PAYMENT\b",
    r"\bEPAY\b",
]
INCOME_PATTERNS = [
    r"\bPAYROLL\b",
    r"DIRECT DEP",
    r"\bDIR DEP\b",
    r"\bSALARY\b",
    r"\bDIRDEP\b",
    r"\bPAYCHECK\b",
]
FEE_PATTERNS = [
    r"INTEREST CHARGE",
    r"\bINTEREST\b.*\bCHARGED\b",
    r"LATE FEE",
    r"LATE PAYMENT FEE",
    r"ANNUAL (MEMBERSHIP )?FEE",
    r"FOREIGN TRANSACTION FEE",
    r"MONTHLY SERVICE FEE",
    r"OVERDRAFT FEE",
    r"ATM FEE",
    r"RETURNED PAYMENT FEE",
    r"CASH ADVANCE FEE",
    r"BALANCE TRANSFER FEE",
]

_PREFIX = re.compile(
    r"^(SQ \*|SQ\*|TST\* ?|TST \*|PAYPAL \*|PP\*|SP \*|DD \*|APLPAY |APPLE PAY |GOOGLE \*|"
    r"IC\* |CKE\*|PY \*|WPY\*|BT\*)",
    re.IGNORECASE,
)
_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}
# Two-letter state codes that collide with common words or abbreviations (Company, In, Or,
# De, Los Angeles, Oklahoma-as-OK, ...) and so are never read as a trailing state.
_AMBIGUOUS_STATES = {"CO", "IN", "OR", "DE", "LA", "OK", "ME", "MA", "HI", "OH", "ID", "PA"}
_CITY_LEADS = {
    "NEW",
    "SAN",
    "LOS",
    "LAS",
    "SALT",
    "FORT",
    "ST",
    "ST.",
    "MOUNT",
    "MT",
    "LAKE",
    "PORT",
    "NORTH",
    "SOUTH",
    "EAST",
    "WEST",
}
_BRAND_CASE = {
    "IKEA": "IKEA",
    "QFC": "QFC",
    "PCC": "PCC",
    "AT&T": "AT&T",
    "T-MOBILE": "T-Mobile",
    "TMOBILE": "T-Mobile",
    "ICLOUD": "iCloud",
    "USPS": "USPS",
    "UPS": "UPS",
    "REI": "REI",
    "CVS": "CVS",
    "H&M": "H&M",
    "BP": "BP",
    "DMV": "DMV",
    "IRS": "IRS",
    "HOA": "HOA",
    "NW": "Nw",
    "LLC": "LLC",
    "INC": "Inc",
}
_PHONE = re.compile(r"^\+?1?[-.]?\d{3}[-.]\d{3}[-.]\d{4}$|^\d{3}[-.]\d{4}$|^\d{10,11}$")
_URL = re.compile(r"^(WWW\.|HTTPS?://)", re.IGNORECASE)
_CODE = re.compile(r"^(?=.*\d)[A-Z0-9]{6,}$")


def _tokens_of(text: str) -> list[str]:
    return " ".join(text.upper().split()).split(" ") if text and text.strip() else []


def _strip_prefixes(text: str) -> str:
    out = text
    for _ in range(2):
        new = _PREFIX.sub("", out).strip()
        if new == out:
            break
        out = new
    return out


def _drop_noise(tokens: list[str]) -> list[str]:
    # The first token is never dropped by the digit/reference-code rule: a description
    # starts with the merchant, and store numbers or reference codes come after it.
    kept: list[str] = []
    for i, tok in enumerate(tokens):
        t = tok.split("*")[0] if "*" in tok and not tok.startswith("*") else tok
        if not t or t == "-" or t == "*" or t.startswith("#"):
            continue
        if t.startswith("*"):
            continue
        if _PHONE.match(t) or _URL.match(t) or "/" in t:
            continue
        if i > 0 and (t.isdigit() or _CODE.match(t)):
            continue
        kept.append(t)
    return kept


def _drop_city_state(tokens: list[str]) -> list[str]:
    if len(tokens) >= 3 and tokens[-1] in _STATES and tokens[-1] not in _AMBIGUOUS_STATES:
        tokens = tokens[:-2]
        if tokens and tokens[-1] in _CITY_LEADS and len(tokens) >= 2:
            tokens = tokens[:-1]
    return tokens


def _title(tokens: list[str]) -> str:
    out = []
    for t in tokens:
        if t in _BRAND_CASE:
            out.append(_BRAND_CASE[t])
        elif "-" in t:
            out.append("-".join(seg.capitalize() for seg in t.split("-")))
        else:
            out.append(t.capitalize())
    return " ".join(out)


def _rule_matches(rule: dict, description: str, merchant: str) -> bool:
    pattern = rule.get("match")
    if not isinstance(pattern, str) or not pattern:
        return False
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return False
    return bool(rx.search(description or "") or rx.search(merchant or ""))


def _builtin(text_upper: str) -> tuple[str | None, str] | None:
    for pattern, merchant, category in BUILTIN_MERCHANTS:
        if re.search(pattern, text_upper):
            return merchant, category
    return None


def normalize_merchant(description: str, merchant_rules: list[dict] | None = None) -> str:
    raw = " ".join((description or "").upper().split())
    if not raw:
        return ""
    stripped = _strip_prefixes(raw)
    hit = _builtin(stripped)
    canonical = hit[0] if hit else None
    pre_noise = _drop_city_state(_tokens_of(stripped))
    cleaned = _drop_noise(pre_noise)
    tokens = cleaned if cleaned else pre_noise
    name = canonical or _title(tokens)
    for rule in merchant_rules or []:
        if isinstance(rule.get("merchant"), str) and _rule_matches(rule, description, name):
            return rule["merchant"]
    return name


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def is_transfer(description: str, merchant: str, transfer_rules: list[dict] | None = None) -> bool:
    up = (description or "").upper()
    if _any(TRANSFER_PATTERNS, up):
        return True
    if any(_rule_matches(r, description, merchant) for r in transfer_rules or []):
        return True
    if _any(PAYMENT_PATTERNS, up):
        stripped = _strip_prefixes(" ".join(up.split()))
        if _builtin(stripped) is None:
            return True
    return False


def is_income(description: str) -> bool:
    return _any(INCOME_PATTERNS, (description or "").upper())


def is_fee(description: str) -> bool:
    return _any(FEE_PATTERNS, (description or "").upper())


def rule_for(description: str, merchant: str, rules: dict | None) -> dict | None:
    for rule in (rules or {}).get("categories", []) or []:
        if rule.get("category") in TAXONOMY and _rule_matches(rule, description, merchant):
            return rule
    return None


def categorize(
    description: str, merchant: str, issuer_category: str | None, rules: dict | None
) -> tuple[str, str]:
    hit = rule_for(description, merchant, rules)
    if hit is not None:
        return hit["category"], "rule"
    if is_fee(description):
        return "Fees and Interest", "keyword"
    if merchant == "Amazon":
        return "Amazon", "keyword"
    label = (issuer_category or "").strip().lower()
    if label and label in ISSUER_CATEGORY_MAP:
        return ISSUER_CATEGORY_MAP[label], "issuer"
    up = " ".join((description or "").upper().split())
    hit = _builtin(_strip_prefixes(up)) or _builtin((merchant or "").upper())
    if hit:
        return hit[1], "keyword"
    return "Uncategorized", "none"


PRESETS: dict[str, dict] = {
    "amex": {
        "kind": "card",
        "sign": "charges_positive",
        "fingerprint": {"date", "description", "amount"},
        "columns": {
            "date": "date",
            "description": "description",
            "amount": "amount",
            "category": "category",
        },
    },
    "chase-card": {
        "kind": "card",
        "sign": "charges_negative",
        "fingerprint": {
            "transaction date",
            "post date",
            "description",
            "category",
            "type",
            "amount",
        },
        "columns": {
            "date": "transaction date",
            "post_date": "post date",
            "description": "description",
            "amount": "amount",
            "category": "category",
            "type": "type",
        },
        "type_map": {
            "sale": "purchase",
            "return": "refund",
            "payment": "payment",
            "fee": "fee",
            "adjustment": "other",
        },
    },
    "chase-checking": {
        "kind": "checking",
        "sign": "account_view",
        "fingerprint": {"details", "posting date", "description", "amount", "type", "balance"},
        "columns": {"date": "posting date", "description": "description", "amount": "amount"},
    },
    "citi": {
        "kind": "card",
        "sign": "debit_credit",
        "fingerprint": {"status", "date", "description", "debit", "credit"},
        "columns": {
            "date": "date",
            "description": "description",
            "debit": "debit",
            "credit": "credit",
            "status": "status",
        },
    },
    "capital-one": {
        "kind": "card",
        "sign": "debit_credit",
        "fingerprint": {
            "transaction date",
            "posted date",
            "card no",
            "description",
            "category",
            "debit",
            "credit",
        },
        "columns": {
            "date": "transaction date",
            "post_date": "posted date",
            "description": "description",
            "category": "category",
            "debit": "debit",
            "credit": "credit",
        },
    },
    "discover": {
        "kind": "card",
        "sign": "charges_positive",
        "fingerprint": {"trans date", "post date", "description", "amount", "category"},
        "columns": {
            "date": "trans date",
            "post_date": "post date",
            "description": "description",
            "amount": "amount",
            "category": "category",
        },
    },
    "bofa-card": {
        "kind": "card",
        "sign": "charges_negative",
        "fingerprint": {"posted date", "reference number", "payee", "address", "amount"},
        "columns": {"date": "posted date", "description": "payee", "amount": "amount"},
    },
    "apple-card": {
        "kind": "card",
        "sign": "charges_positive",
        "fingerprint": {
            "transaction date",
            "clearing date",
            "description",
            "merchant",
            "category",
            "type",
            "amount usd",
        },
        "columns": {
            "date": "transaction date",
            "post_date": "clearing date",
            "description": "description",
            "merchant": "merchant",
            "category": "category",
            "type": "type",
            "amount": "amount usd",
        },
        "type_map": {
            "purchase": "purchase",
            "payment": "payment",
            "credit": "refund",
            "interest": "interest",
            "installment": "purchase",
        },
    },
}
_KINDS = ("card", "checking", "savings")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%b %d, %Y",
    "%Y%m%d",
)


def norm_header(header: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(header or "").lower()).split())


def detect_preset(headers: list[str]) -> str | None:
    have = {norm_header(h) for h in headers}
    best: tuple[int, str] | None = None
    for name, preset in PRESETS.items():
        fp = preset["fingerprint"]
        if fp <= have and (best is None or len(fp) > best[0]):
            best = (len(fp), name)
    return best[1] if best else None


def parse_date(raw: object) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    text = text.split(" as of ")[0].strip()
    if "T" in text and len(text) >= 10 and text[4] == "-":
        text = text[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_money(raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    text = str(raw).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not text:
        return None
    neg = False
    if text.startswith("(") and text.endswith(")"):
        neg, text = True, text[1:-1]
    if text.endswith("-"):
        neg, text = True, text[:-1]
    if text.startswith("-"):
        neg, text = (not neg), text[1:]
    if text.startswith("+"):
        text = text[1:]
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if neg else value


_OFX_BLOCK = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)
_OFX_FIELD = re.compile(r"<(TRNTYPE|DTPOSTED|TRNAMT|FITID|NAME|MEMO)>([^<\r\n]*)", re.IGNORECASE)


def parse_ofx(text: str) -> dict:
    up = text or ""
    kind = (
        "card"
        if re.search(r"<CCSTMTRS>", up, re.IGNORECASE)
        else ("checking" if re.search(r"<STMTRS>", up, re.IGNORECASE) else None)
    )
    rows = []
    for block in _OFX_BLOCK.findall(up):
        fields = {k.upper(): v.strip() for k, v in _OFX_FIELD.findall(block)}
        date = parse_date(fields.get("DTPOSTED", "")[:8])
        amount = parse_money(fields.get("TRNAMT"))
        if date is None or amount is None:
            continue
        rows.append(
            {
                "date": date,
                "post_date": None,
                "amount": amount,
                "description": (fields.get("NAME") or fields.get("MEMO") or "").strip(),
                "fitid": fields.get("FITID") or None,
                "trntype": (fields.get("TRNTYPE") or "").upper() or None,
            }
        )
    return {"kind": kind, "rows": rows}


def _ignored(description: str, merchant: str, rules: dict) -> bool:
    return any(_rule_matches(r, description, merchant) for r in rules.get("ignore", []) or [])


def _derive_kind(
    category: str, type_hint: str | None, account_kind: str, amount: float, description: str
) -> str:
    if type_hint in ("purchase", "refund", "fee", "interest", "other"):
        return type_hint
    if category == "Fees and Interest":
        return "interest" if "INTEREST" in description.upper() else "fee"
    if account_kind == "card":
        return "purchase" if amount < 0 else ("refund" if amount > 0 else "other")
    return "withdrawal" if amount < 0 else ("deposit" if amount > 0 else "other")


def build_transaction(
    account_id: str,
    account_kind: str,
    *,
    date: str,
    post_date: str | None,
    amount: float,
    description: str,
    issuer_category: str | None,
    type_hint: str | None,
    fitid: str | None,
    rules: dict,
    source_id: str,
    detail: str | None = None,
    items: list | None = None,
    merchant_override: str | None = None,
    category_override: str | None = None,
    source: str = "preset",
) -> dict | None:
    if merchant_override is not None and not isinstance(merchant_override, str):
        raise ValueError("merchant must be a string")
    if isinstance(merchant_override, str) and merchant_override.strip():
        merchant, merchant_source = merchant_override.strip(), "transcribed"
    else:
        merchant, merchant_source = normalize_merchant(description, rules.get("merchants")), None
    if _ignored(description, merchant, rules):
        return None
    own_detail = validate_detail(detail)
    detail_source = "transcribed" if own_detail else None
    transfer = type_hint == "payment" or is_transfer(description, merchant, rules.get("transfers"))
    rule = None if transfer else rule_for(description, merchant, rules)
    if category_override is not None:
        if category_override not in TAXONOMY:
            raise ValueError("category must be one of the taxonomy names")
        if category_override == "Income" and account_kind == "card":
            raise ValueError("Income applies to checking and savings accounts only")
        category, source_tag = category_override, "transcribed"
        transfer = category_override == "Transfer"
        if transfer:
            kind = "payment" if account_kind == "card" else "transfer"
        elif category_override == "Income":
            kind = "deposit"
        else:
            kind = _derive_kind(category, type_hint, account_kind, amount, description)
    elif transfer:
        category, source_tag = "Transfer", "keyword"
        kind = "payment" if account_kind == "card" else "transfer"
    elif rule is not None:
        # A user category rule wins over both the Income shortcut and categorize()'s own
        # fee/Amazon/issuer/keyword chain, so a rule on a bank credit (e.g. re-tagging a
        # payroll deposit) is not silently shadowed by the Income branch below.
        category, source_tag = rule["category"], "rule"
        if category == "Transfer":
            # A hand-edited rules file can name Transfer as a category; honor it as a real
            # transfer (excluded from spend/income) rather than a category with no effect.
            transfer = True
            kind = "payment" if account_kind == "card" else "transfer"
        elif account_kind in ("checking", "savings") and amount > 0:
            kind = "deposit"
        else:
            kind = _derive_kind(category, type_hint, account_kind, amount, description)
    elif account_kind in ("checking", "savings") and amount > 0:
        category, source_tag, kind = "Income", "keyword", "deposit"
    else:
        category, source_tag = categorize(description, merchant, issuer_category, rules)
        kind = _derive_kind(category, type_hint, account_kind, amount, description)
    if own_detail is None and rule is not None and rule.get("detail"):
        own_detail = validate_detail(rule.get("detail"))
        detail_source = "rule" if own_detail else None
    tx = {
        "account_id": account_id,
        "date": date,
        "post_date": post_date,
        "amount": round(float(amount), 2),
        "description": description,
        "merchant": merchant,
        "merchant_source": merchant_source,
        "category": category,
        "category_source": source_tag,
        "issuer_category": issuer_category or None,
        "type": kind,
        "transfer": transfer,
        "fitid": fitid,
        "source_id": source_id,
        "source": source,
        "detail": own_detail,
        "detail_source": detail_source,
    }
    if items:
        tx["items"] = validate_items(items, tx["amount"])
    return tx


def _cell(row: dict, wanted: str | None) -> str:
    if not wanted:
        return ""
    for k, v in row.items():
        if norm_header(k) == wanted:
            return str(v or "").strip()
    return ""


def _mapping_preset(mapping: dict) -> dict:
    cols = {
        role: norm_header(mapping[role])
        for role in (
            "date",
            "post_date",
            "description",
            "amount",
            "debit",
            "credit",
            "category",
            "type",
        )
        if mapping.get(role)
    }
    if (
        "date" not in cols
        or "description" not in cols
        or not ({"amount"} <= set(cols) or {"debit", "credit"} <= set(cols))
    ):
        raise ValueError("mapping needs date, description and amount (or debit and credit)")
    sign = mapping.get("sign") or ("debit_credit" if "debit" in cols else "charges_negative")
    if sign not in ("charges_negative", "charges_positive", "account_view", "debit_credit"):
        raise ValueError(
            "mapping sign must be charges_negative, charges_positive, account_view or debit_credit"
        )
    if sign != "debit_credit" and "amount" not in cols:
        raise ValueError("mapping sign must be debit_credit when no amount column is mapped")
    return {"kind": "card", "sign": sign, "fingerprint": set(cols.values()), "columns": cols}


def _csv_transactions(
    rows: list[dict],
    preset: dict,
    account_id: str,
    account_kind: str,
    rules: dict,
    source_name: str,
    preset_name: str,
) -> tuple[list[dict], list[dict]]:
    cols = preset["columns"]
    out: list[dict] = []
    skipped: list[dict] = []
    label = "mapping" if preset_name == "mapping" else f"preset:{preset_name}"
    for i, row in enumerate(rows, start=1):
        if not any(str(v or "").strip() for v in row.values()):
            skipped.append({"row": i, "reason": "blank row"})
            continue
        if cols.get("status") and _cell(row, cols["status"]).lower() == "pending":
            skipped.append({"row": i, "reason": "pending"})
            continue
        date = parse_date(_cell(row, cols["date"]))
        if date is None:
            skipped.append({"row": i, "reason": "bad date"})
            continue
        if preset["sign"] == "debit_credit":
            debit, credit = (
                parse_money(_cell(row, cols.get("debit"))),
                parse_money(_cell(row, cols.get("credit"))),
            )
            amount = (
                -abs(debit)
                if debit not in (None, 0.0)
                else (abs(credit) if credit is not None else None)
            )
        else:
            amount = parse_money(_cell(row, cols["amount"]))
            if amount is not None and preset["sign"] == "charges_positive":
                amount = -amount
        if amount is None:
            skipped.append({"row": i, "reason": "no amount"})
            continue
        description = _cell(row, cols["description"]) or _cell(row, cols.get("merchant"))
        type_hint = None
        if cols.get("type") and preset.get("type_map"):
            type_hint = preset["type_map"].get(_cell(row, cols["type"]).lower())
        tx = build_transaction(
            account_id,
            account_kind,
            date=date,
            post_date=parse_date(_cell(row, cols.get("post_date"))),
            amount=amount,
            description=description,
            issuer_category=_cell(row, cols.get("category")) or None,
            type_hint=type_hint,
            fitid=None,
            rules=rules,
            source_id=f"{source_name}:{i}",
            source=label,
        )
        if tx is None:
            skipped.append({"row": i, "reason": "ignored by rule"})
            continue
        out.append(tx)
    return out, skipped


def _looks_like_transfer_text(description: str) -> bool:
    """is_transfer's strong+weak keyword lists, with no built-in-merchant suppression.

    Used only to rank cross-account candidates in ``match_transfers`` — it must not feed
    ``is_transfer``/``build_transaction`` or it would change what counts as a transfer for
    a single row on its own.
    """
    up = (description or "").upper()
    return _any(TRANSFER_PATTERNS, up) or _any(PAYMENT_PATTERNS, up)


def match_transfers(transactions: list[dict], accounts: dict[str, dict]) -> int:
    def kind(t: dict) -> str | None:
        account = accounts.get(t.get("account_id"))
        return account.get("kind") if account else None

    bank_rows = [
        t
        for t in transactions
        if kind(t) in ("checking", "savings")
        and float(t["amount"]) < 0
        and not t.get("transfer_pair")
    ]
    pairs = 0
    for t in transactions:
        if kind(t) != "card" or float(t["amount"]) <= 0 or t.get("transfer_pair"):
            continue
        if not (t.get("type") == "payment" or t.get("transfer")):
            continue
        td = date.fromisoformat(t["date"])
        target = round(float(t["amount"]), 2)
        candidates = []
        for i, b in enumerate(bank_rows):
            if b.get("transfer_pair") or round(-float(b["amount"]), 2) != target:
                continue
            delta = abs((date.fromisoformat(b["date"]) - td).days)
            if delta > 5:
                continue
            keyword_rank = 0 if _looks_like_transfer_text(b.get("description") or "") else 1
            candidates.append((delta, keyword_rank, i, b))
        if not candidates:
            continue
        candidates.sort(key=lambda c: (c[0], c[1], c[2]))
        b = candidates[0][3]
        pair = f"p-{t.get('id') or t['source_id']}"
        for row, kind_name in ((t, "payment"), (b, "transfer")):
            row.update(
                {
                    "transfer": True,
                    "category": "Transfer",
                    "category_source": "keyword",
                    "type": kind_name,
                    "transfer_pair": pair,
                }
            )
        pairs += 1
    return pairs


def apply_rules(transactions: list[dict], rules: dict, accounts: dict[str, dict]) -> dict:
    kept: list[dict] = []
    originals: list[dict] = []
    changed = removed = 0
    for t in transactions:
        account_kind = (accounts.get(t.get("account_id")) or {}).get("kind", "card")
        orig_type = t.get("type")
        if orig_type == "payment" and t.get("transfer"):
            type_hint = "payment"
        elif orig_type in ("purchase", "refund", "fee", "interest", "other"):
            # Keep the sub-type sticky across re-normalization: build_transaction would
            # otherwise re-derive it from a keyword heuristic (e.g. "fee" vs "interest")
            # that can disagree with the more specific value a preset's type column gave it
            # on import, reporting a spurious change on every reapply.
            type_hint = orig_type
        else:
            type_hint = None
        transcribed_category = (
            t.get("category") if t.get("category_source") == "transcribed" else None
        )
        transcribed_detail = t.get("detail") if t.get("detail_source") == "transcribed" else None
        transcribed_merchant = (
            t.get("merchant") if t.get("merchant_source") == "transcribed" else None
        )
        rebuilt = build_transaction(
            t["account_id"],
            account_kind,
            date=t["date"],
            post_date=t.get("post_date"),
            amount=float(t["amount"]),
            description=t.get("description") or "",
            issuer_category=t.get("issuer_category"),
            type_hint=type_hint,
            fitid=t.get("fitid"),
            rules=rules,
            source_id=t.get("source_id") or "",
            detail=transcribed_detail,
            items=None,
            merchant_override=transcribed_merchant,
            category_override=transcribed_category,
            source=t.get("source") or "preset",
        )
        if rebuilt is None:
            removed += 1
            continue
        new = {
            **t,
            **{
                k: rebuilt[k]
                for k in (
                    "merchant",
                    "merchant_source",
                    "category",
                    "category_source",
                    "type",
                    "transfer",
                    "detail",
                    "detail_source",
                )
            },
        }
        kept.append(new)
        originals.append(t)

    # A transfer_pair only makes sense while both sides survive. Count how many kept rows
    # still carry each pair id before deciding whether to keep forcing the Transfer contract.
    pair_counts: dict[str, int] = {}
    for t in kept:
        pid = t.get("transfer_pair")
        if pid:
            pair_counts[pid] = pair_counts.get(pid, 0) + 1

    for new, orig in zip(kept, originals):
        pid = new.get("transfer_pair")
        if pid and pair_counts.get(pid, 0) >= 2:
            new.update(
                {
                    "transfer": True,
                    "category": "Transfer",
                    "category_source": "keyword",
                    "type": orig.get("type") or "transfer",
                }
            )
        elif pid:
            # Orphaned: the partner was removed (e.g. by a new ignore rule). Drop the stale
            # pair marker and keep the naturally rebuilt fields — the same path an unpaired
            # row takes. A later match_transfers call can re-pair it if a partner still exists.
            del new["transfer_pair"]
        if any(
            new[k] != orig.get(k)
            for k in (
                "merchant",
                "merchant_source",
                "category",
                "category_source",
                "type",
                "transfer",
                "detail",
                "detail_source",
            )
        ):
            changed += 1
    by_category: dict[str, int] = {}
    for t in kept:
        by_category[t["category"]] = by_category.get(t["category"], 0) + 1
    return {
        "changed": changed,
        "removed": removed,
        "by_category": by_category,
        "transactions": kept,
    }


def run_spendnormalize(params: dict) -> dict:
    """Normalize rows; raises ValueError/TypeError on bad input."""
    if not isinstance(params, dict):
        raise ValueError("input must be a JSON object")
    source = params.get("source")
    account_id = params.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("account_id is required")
    rules = params.get("rules") or {}
    if not isinstance(rules, dict):
        raise ValueError("rules must be an object")
    source_name = str(params.get("source_name") or source or "import")
    account_kind = params.get("account_kind")
    if source == "csv":
        rows = params.get("rows")
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            raise ValueError("rows must be a non-empty list of objects")
        if params.get("mapping"):
            preset_name, preset = "mapping", _mapping_preset(params["mapping"])
        elif params.get("preset"):
            preset_name = params["preset"]
            if preset_name not in PRESETS:
                raise ValueError(f"unknown preset {preset_name!r}; one of {', '.join(PRESETS)}")
            preset = PRESETS[preset_name]
        else:
            detected = detect_preset(list(rows[0].keys()))
            if detected is None:
                raise ValueError("no preset matches the columns; pass preset or mapping")
            preset_name, preset = detected, PRESETS[detected]
        account_kind = account_kind or preset["kind"]
        if account_kind not in _KINDS:
            raise ValueError("account_kind must be card, checking or savings")
        txs, skipped = _csv_transactions(
            rows, preset, account_id, account_kind, rules, source_name, preset_name
        )
    elif source == "ofx":
        parsed = parse_ofx(str(params.get("ofx_text") or ""))
        if not parsed["rows"]:
            raise ValueError("no transactions found in the OFX text")
        account_kind = account_kind or parsed["kind"] or "card"
        if account_kind not in _KINDS:
            raise ValueError("account_kind must be card, checking or savings")
        preset_name = "ofx"
        txs, skipped = [], []
        for i, r in enumerate(parsed["rows"], start=1):
            tx = build_transaction(
                account_id,
                account_kind,
                date=r["date"],
                post_date=None,
                amount=r["amount"],
                description=r["description"],
                issuer_category=None,
                type_hint=None,
                fitid=r["fitid"],
                rules=rules,
                source_id=f"{source_name}:{i}",
                source="ofx",
            )
            if tx is None:
                skipped.append({"row": i, "reason": "ignored by rule"})
            else:
                txs.append(tx)
    elif source == "rows":
        rows = params.get("rows")
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            raise ValueError("rows must be a non-empty list of objects")
        source_kind = params.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind.strip():
            raise ValueError(
                "source_kind is required for rows (for example receipt or amazon-chat)"
            )
        account_kind = account_kind or "card"
        if account_kind not in _KINDS:
            raise ValueError("account_kind must be card, checking or savings")
        preset_name = "rows"
        txs, skipped = [], []
        label = f"transcribed:{source_kind.strip()}"
        for i, r in enumerate(rows, start=1):
            day = parse_date(r.get("date"))
            if day is None:
                skipped.append({"row": i, "reason": "bad date"})
                continue
            amount = parse_money(r.get("amount"))
            if amount is None:
                skipped.append({"row": i, "reason": "no amount"})
                continue
            description = str(r.get("description") or "").strip()
            if not description:
                skipped.append({"row": i, "reason": "no description"})
                continue
            try:
                tx = build_transaction(
                    account_id,
                    account_kind,
                    date=day,
                    post_date=parse_date(r.get("post_date")),
                    amount=amount,
                    description=description,
                    issuer_category=None,
                    type_hint=None,
                    fitid=None,
                    rules=rules,
                    source_id=f"{source_name}:{i}",
                    detail=r.get("detail"),
                    items=r.get("items") or None,
                    merchant_override=r.get("merchant"),
                    category_override=r.get("category"),
                    source=label,
                )
            except ValueError as exc:
                skipped.append({"row": i, "reason": str(exc)})
                continue
            if tx is None:
                skipped.append({"row": i, "reason": "ignored by rule"})
                continue
            txs.append(tx)
    else:
        raise ValueError("source must be csv, ofx or rows")
    txs = [t for _, t in sorted(enumerate(txs), key=lambda p: (p[1]["date"], p[0]))]
    categories: dict[str, int] = {}
    for t in txs:
        categories[t["category"]] = categories.get(t["category"], 0) + 1
    return {
        "preset": preset_name,
        "account_kind": account_kind,
        "transactions": txs,
        "count": len(txs),
        "skipped": skipped,
        "date_range": {"start": txs[0]["date"], "end": txs[-1]["date"]} if txs else None,
        "categories": categories,
        "uncategorized": sum(1 for t in txs if t["category_source"] == "none"),
        "transfers_marked": sum(1 for t in txs if t["transfer"]),
    }


def main() -> None:
    """Read JSON params from stdin, write the result (or error) to stdout."""
    raw = sys.stdin.read()
    try:
        result = run_spendnormalize(json.loads(raw))
    except (ValueError, TypeError, KeyError, ZeroDivisionError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
