from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import (
    JSONResponse,
    RedirectResponse,
    HTMLResponse,
    PlainTextResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import aiohttp
import asyncio
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
import os
from functools import lru_cache
from math import ceil
from pathlib import Path
from urllib.parse import quote as urlquote
from xml.sax.saxutils import escape as xml_escape
from typing import Any, Optional, Dict, List

# Resolve assets relative to this file so the app works from any working directory.
BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"

QUOTES_ENDPOINT = "/v1/quote"

# Absolute URLs in canonical tags, Open Graph, sitemap.xml and llms.txt must point
# at the real public origin. Set QUOTIA_BASE_URL in production (e.g. behind a proxy
# or custom domain); otherwise we fall back to the origin the request arrived on,
# which is correct for local dev and default Hugging Face Space URLs.
BASE_URL_ENV_VAR = "QUOTIA_BASE_URL"
BASE_URL_PLACEHOLDER = "__BASE_URL__"

# Enhanced logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# Upper bound on how many pages we pull from each source for one request. Deeper
# pages cost another round trip per source, so this caps the scraping fan-out.
MAX_SOURCE_PAGES = 5

# Rough number of quotes one page of one source yields. Only used to decide how
# many source pages to request; the real count is whatever comes back.
QUOTES_PER_SOURCE_PAGE = 10

DESCRIPTION = """
Quotia aggregates quotes scraped on demand from public quote sites.

`GET /v1/quote` is the API. The site root `/` serves the landing page.

## Sources

* **toscrape** — [quotes.toscrape.com](http://quotes.toscrape.com)
* **goodreads** — [goodreads.com/quotes](https://www.goodreads.com/quotes)

## Filtering and pagination

Pass `category` to restrict results to a tag (`love`, `inspirational`, `humor`, …).
Use `page` and `page_size` to walk the merged result set; the response carries
`total`, `total_pages`, `has_next` and `has_previous` alongside the quotes.

Because quotes are scraped live, `total` counts what was retrieved for this
request (up to {max_pages} pages per source), not the full upstream catalogue.

Results are cached in memory for 5 minutes per `category`/`page`/`page_size`
combination, so repeated identical calls do not re-scrape the upstream sites.

## Interactive documentation

* [Swagger UI](/docs) — try requests directly from the browser
* [ReDoc](/redoc) — reference-style reading view
* [OpenAPI schema](/openapi.json) — raw machine-readable spec
""".format(max_pages=MAX_SOURCE_PAGES)

TAGS_METADATA = [
    {
        "name": "quotes",
        "description": "Scrape and return quotes, optionally filtered by category.",
    },
]

app = FastAPI(
    title="Quotia",
    summary="A quote aggregation API that scrapes quotes from multiple public sources.",
    description=DESCRIPTION,
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": 1,
        "displayRequestDuration": True,
        "docExpansion": "list",
        "filter": True,
        "tryItOutEnabled": True,
    },
)


class Quote(BaseModel):
    """A single scraped quote."""

    text: str = Field(..., description="The quote text, without surrounding quotation marks.")
    author: str = Field(..., description="Name of the person the quote is attributed to.")
    source: str = Field(..., description="Site the quote was scraped from (`toscrape` or `goodreads`).")
    tags: List[str] = Field(
        default_factory=list,
        description="Categories the source filed this quote under. Empty if the source lists none.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "The world as we have created it is a process of our thinking.",
                    "author": "Albert Einstein",
                    "source": "toscrape",
                    "tags": ["change", "deep-thoughts", "thinking", "world"],
                }
            ]
        }
    }


class QuotesResponse(BaseModel):
    """One page of quotes, plus the pagination cursor for walking the rest."""

    quotes: List[Quote] = Field(..., description="The requested page of quotes.")
    category: Optional[str] = Field(
        None, description="The normalized category this request was filtered by, or `null` for no filter."
    )
    page: int = Field(..., description="1-based index of the page returned.", ge=1)
    page_size: int = Field(..., description="Maximum number of quotes per page.", ge=1)
    total: int = Field(
        ...,
        description=(
            "Number of unique quotes retrieved for this request. Quotes are scraped live, "
            "so this reflects what the sources returned rather than their full catalogue."
        ),
        ge=0,
    )
    total_pages: int = Field(..., description="Number of pages `total` divides into at this `page_size`.", ge=0)
    has_next: bool = Field(..., description="Whether a page after this one exists.")
    has_previous: bool = Field(..., description="Whether a page before this one exists.")


class ErrorResponse(BaseModel):
    """Error payload returned by failing endpoints."""

    detail: str = Field(..., description="Human-readable description of what went wrong.")

    model_config = {"json_schema_extra": {"examples": [{"detail": "Internal server error"}]}}

# Initialize cache immediately
FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    logger.warning(f"Static directory not found at {STATIC_DIR}; /static will 404")

def resolve_base_url(request: Request) -> str:
    """Public origin for absolute URLs, without a trailing slash."""
    configured = os.getenv(BASE_URL_ENV_VAR, "").strip()
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")

@lru_cache(maxsize=8)
def render_index(base_url: str) -> str:
    """Read index.html and bake the public origin into its canonical/OG/JSON-LD tags."""
    return INDEX_FILE.read_text(encoding="utf-8").replace(BASE_URL_PLACEHOLDER, base_url)

@app.get("/", include_in_schema=False)
async def index(request: Request) -> HTMLResponse:
    """Serve the landing page. The quotes API lives at /v1/quote."""
    if not INDEX_FILE.is_file():
        logger.error(f"index.html not found at {INDEX_FILE}")
        raise HTTPException(status_code=404, detail="index.html not found")
    return HTMLResponse(render_index(resolve_base_url(request)))

@app.get("/doc", include_in_schema=False)
@app.get("/doc/", include_in_schema=False)
async def doc_redirect() -> RedirectResponse:
    """Alias /doc and /doc/ onto the ReDoc reference view."""
    return RedirectResponse(url="/redoc", status_code=308)

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request) -> PlainTextResponse:
    """Let crawlers index the site and docs, but keep them out of the scraping endpoint."""
    base_url = resolve_base_url(request)
    body = f"""User-agent: *
Allow: /
Disallow: {QUOTES_ENDPOINT}

Sitemap: {base_url}/sitemap.xml
"""
    return PlainTextResponse(body)

@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request) -> Response:
    """List the human-readable pages worth indexing."""
    base_url = resolve_base_url(request)
    pages = [("/", "1.0"), ("/docs", "0.8"), ("/redoc", "0.8")]
    entries = "\n".join(
        f"  <url>\n"
        f"    <loc>{xml_escape(base_url + path)}</loc>\n"
        f"    <changefreq>weekly</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f"  </url>"
        for path, priority in pages
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")

@app.get("/llms.txt", include_in_schema=False)
async def llms_txt(request: Request) -> PlainTextResponse:
    """Concise index for LLM agents, per the llmstxt.org convention."""
    base_url = resolve_base_url(request)
    body = f"""# Quotia

> A free, developer-focused REST API that scrapes quotes from multiple public
> sources in parallel, deduplicates them, and returns clean paginated JSON.

Quotia exposes one endpoint and requires no authentication or API key. Quotes are
scraped live from public sites and cached in memory for 5 minutes. Because results
are scraped per request, `total` reflects what was retrieved for that request
rather than a fixed catalogue size.

## API

- [GET {QUOTES_ENDPOINT}]({base_url}{QUOTES_ENDPOINT}): Returns a page of quotes. Query
  parameters: `category` (tag such as love, inspirational, humor), `page`
  (1-based, default 1), `page_size` (1-{MAX_PAGE_SIZE}, default {DEFAULT_PAGE_SIZE}). Responds with
  `quotes`, `category`, `page`, `page_size`, `total`, `total_pages`, `has_next`,
  `has_previous`. Each quote has `text`, `author`, `source`, `tags`.

## Docs

- [OpenAPI schema]({base_url}/openapi.json): Machine-readable specification of the API.
- [ReDoc reference]({base_url}/redoc): Reference-style documentation.
- [Swagger UI]({base_url}/docs): Interactive documentation you can send requests from.
- [Full details]({base_url}/llms-full.txt): Parameters, response schema and examples in one file.

## Sources

- [quotes.toscrape.com](http://quotes.toscrape.com): Reported as `source: "toscrape"`.
- [goodreads.com/quotes](https://www.goodreads.com/quotes): Reported as `source: "goodreads"`.
"""
    return PlainTextResponse(body)

@app.get("/llms-full.txt", include_in_schema=False)
async def llms_full_txt(request: Request) -> PlainTextResponse:
    """Everything an agent needs to call the API correctly, without fetching the schema."""
    base_url = resolve_base_url(request)
    example = """```json
{
  "quotes": [
    {
      "text": "The world as we have created it is a process of our thinking.",
      "author": "Albert Einstein",
      "source": "toscrape",
      "tags": ["change", "deep-thoughts", "thinking", "world"]
    }
  ],
  "category": "inspirational",
  "page": 1,
  "page_size": 10,
  "total": 40,
  "total_pages": 4,
  "has_next": true,
  "has_previous": false
}
```"""
    body = f"""# Quotia — full reference

> A free, developer-focused REST API that scrapes quotes from multiple public
> sources in parallel, deduplicates them, and returns clean paginated JSON.

Base URL: {base_url}
No authentication is required.

## GET {QUOTES_ENDPOINT}

Scrapes every configured source concurrently, merges the results, removes
duplicates, and returns one page. A source that fails or returns a non-200 status
is skipped rather than failing the request.

### Query parameters

- `category` (string, optional): Tag to filter by, e.g. `love`, `inspirational`,
  `humor`. Case-insensitive and trimmed. Omit for the front page of each source.
- `page` (integer, optional, default 1, minimum 1): 1-based page number. A page
  beyond the available results returns an empty `quotes` list, not an error.
- `page_size` (integer, optional, default {DEFAULT_PAGE_SIZE}, range 1-{MAX_PAGE_SIZE}): Quotes per page.

### Response fields

- `quotes` (array): The requested page. Each item has `text` (string),
  `author` (string), `source` (`"toscrape"` or `"goodreads"`), and `tags`
  (array of strings, may be empty when the source lists none).
- `category` (string or null): The normalized category that was applied.
- `page`, `page_size` (integer): Echo of the pagination request.
- `total` (integer): Unique quotes retrieved for this request. Scraping is live and
  bounded to {MAX_SOURCE_PAGES} pages per source, so this is not a fixed catalogue size and can
  differ between requests with different `page_size` values.
- `total_pages` (integer): `total` divided by `page_size`, rounded up.
- `has_next`, `has_previous` (boolean): Whether adjacent pages exist.

### Example

Request: `GET {base_url}{QUOTES_ENDPOINT}?category=inspirational&page=1&page_size=10`

{example}

### Errors

- `422 Unprocessable Entity`: A parameter failed validation, e.g. `page=0` or
  `page_size` above {MAX_PAGE_SIZE}. The body has FastAPI's standard `detail` array.
- `500 Internal Server Error`: Scraping failed unexpectedly. The body is
  `{{"detail": "Internal server error"}}`.

## Behaviour notes

- Responses are cached in memory for 5 minutes per `category`/`page`/`page_size`.
- Page 1 of every source is fetched before page 2 of any source, so lower `page`
  values hold the most prominent quotes.
- Quotes appearing on both sources are returned once, keeping the first occurrence.
- Quotes are scraped from third-party sites; check their terms before redistributing.

## Other endpoints

- `GET /` — landing page.
- `GET /docs` — Swagger UI.
- `GET /redoc` — ReDoc reference. `/doc` and `/doc/` redirect here.
- `GET /openapi.json` — OpenAPI schema.
"""
    return PlainTextResponse(body)

async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch the HTML content of a URL asynchronously."""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Error fetching {url}: Status {response.status}")
                return ""
            return await response.text()
    except Exception as e:
        logger.error(f"Error fetching {url}: {str(e)}")
        return ""

async def scrape_quotes_toscrape(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Scrape quotes from quotes.toscrape.com."""
    quotes = []
    try:
        for quote in soup.find_all("div", class_="quote"):
            text = quote.find("span", class_="text")
            author = quote.find("small", class_="author")
            if text and author:
                quotes.append({
                    "text": text.text.strip(' "'),
                    "author": author.text.strip(),
                    "source": "toscrape",
                    "tags": [tag.text.strip() for tag in quote.find_all("a", class_="tag") if tag.text.strip()]
                })
    except Exception as e:
        logger.error(f"Error parsing toscrape quotes: {str(e)}")
    return quotes

def _goodreads_tags(quote_text_div) -> List[str]:
    """Pull the tag list that sits in the quote's footer, alongside the quote text."""
    container = quote_text_div.find_parent("div", class_="quote")
    if not container:
        return []
    footer = container.find("div", class_="quoteFooter")
    if not footer:
        return []
    # Tag links point at /quotes/tag/<name>; other footer links (likes, book) do not.
    return [
        link.text.strip()
        for link in footer.find_all("a")
        if "/quotes/tag/" in (link.get("href") or "") and link.text.strip()
    ]

async def scrape_quotes_goodreads(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Scrape quotes from goodreads.com."""
    quotes = []
    try:
        for quote in soup.find_all("div", class_="quoteText"):
            text_parts = quote.get_text(strip=True).split("―")
            author = quote.find("span", class_="authorOrTitle")
            if text_parts and author:
                quotes.append({
                    "text": text_parts[0].strip(' "'),
                    "author": author.text.strip(),
                    "source": "goodreads",
                    "tags": _goodreads_tags(quote)
                })
    except Exception as e:
        logger.error(f"Error parsing goodreads quotes: {str(e)}")
    return quotes

def build_source_urls(category: Optional[str], source_pages: int) -> List[str]:
    """
    Build the list of source URLs to scrape, ordered page by page.

    Page 1 of every source comes before page 2 of any source, so truncating the
    merged results still yields the most prominent quotes first.
    """
    tag = urlquote(category, safe="") if category else None
    urls = []
    for n in range(1, source_pages + 1):
        if tag:
            urls.append(f"http://quotes.toscrape.com/tag/{tag}/page/{n}/")
            urls.append(f"https://www.goodreads.com/quotes/tag/{tag}?page={n}")
        else:
            urls.append(f"http://quotes.toscrape.com/page/{n}/")
            urls.append(f"https://www.goodreads.com/quotes?page={n}")
    return urls

def deduplicate(quotes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop repeats, keeping first occurrence. Sources overlap and paginate inconsistently."""
    seen = set()
    unique = []
    for quote in quotes:
        key = (quote["text"].casefold(), quote["author"].casefold())
        if key not in seen:
            seen.add(key)
            unique.append(quote)
    return unique

async def scrape_url(session: aiohttp.ClientSession, url: str) -> List[Dict[str, Any]]:
    """Scrape quotes from a single URL."""
    try:
        html = await fetch(session, url)
        if not html:
            return []
        
        soup = BeautifulSoup(html, "html.parser")
        
        if "toscrape" in url:
            return await scrape_quotes_toscrape(soup)
        elif "goodreads" in url:
            return await scrape_quotes_goodreads(soup)
        return []
    except Exception as e:
        logger.error(f"Error scraping {url}: {str(e)}")
        return []

@app.get(
    QUOTES_ENDPOINT,
    response_class=JSONResponse,
    response_model=QuotesResponse,
    tags=["quotes"],
    summary="Fetch quotes",
    responses={
        500: {
            "model": ErrorResponse,
            "description": "Scraping failed unexpectedly for every source.",
        }
    },
)
@cache(expire=300)
async def get_quotes(
    category: Optional[str] = Query(
        None,
        description=(
            "Category (tag) to filter quotes by, e.g. `love`, `inspirational`, `humor`. "
            "Omit it to get the front page of each source."
        ),
        examples=["inspirational"],
    ),
    page: int = Query(
        1,
        ge=1,
        description="1-based page number to return.",
    ),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"How many quotes to return per page (1-{MAX_PAGE_SIZE}).",
    ),
) -> Dict[str, Any]:
    """
    Fetch quotes from every configured source, merge them, and return one page.

    Each source is scraped concurrently; a source that fails or returns a
    non-200 status is logged and skipped rather than failing the whole request.
    Duplicates across sources are removed before paging, and page 1 of every
    source is fetched before page 2 of any, so lower `page` values hold the
    most prominent quotes.

    Deep pages require more scraping, so at most 5 pages are pulled per source.
    A `page` beyond what the sources returned yields an empty `quotes` list
    rather than an error.

    Responses are cached for 5 minutes per `category`/`page`/`page_size`.
    """
    category = (category or "").strip().lower() or None
    logger.info(f"Processing request for category={category} page={page} page_size={page_size}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    # Only scrape as deep as the requested window needs, up to the cap.
    needed = page * page_size
    source_pages = min(MAX_SOURCE_PAGES, ceil(needed / QUOTES_PER_SOURCE_PAGE))
    urls = build_source_urls(category, source_pages)

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [scrape_url(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            all_quotes = []
            for result in results:
                if isinstance(result, list):
                    all_quotes.extend(result)
                else:
                    logger.error(f"Error in gathering results: {str(result)}")

            unique_quotes = deduplicate(all_quotes)
            total = len(unique_quotes)
            total_pages = ceil(total / page_size)
            start = (page - 1) * page_size
            window = unique_quotes[start:start + page_size]

            logger.info(f"Retrieved {total} unique quotes, returning {len(window)} for page {page}")
            return {
                "quotes": window,
                "category": category,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1,
            }
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)