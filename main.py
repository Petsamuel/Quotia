from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
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
from math import ceil
from pathlib import Path
from urllib.parse import quote as urlquote
from typing import Any, Optional, Dict, List

# Resolve assets relative to this file so the app works from any working directory.
BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
STATIC_DIR = BASE_DIR / "static"

QUOTES_ENDPOINT = "/v1/quote"

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

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the landing page. The quotes API lives at /v1/quote."""
    if not INDEX_FILE.is_file():
        logger.error(f"index.html not found at {INDEX_FILE}")
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX_FILE, media_type="text/html")

@app.get("/doc", include_in_schema=False)
@app.get("/doc/", include_in_schema=False)
async def doc_redirect() -> RedirectResponse:
    """Alias /doc and /doc/ onto the ReDoc reference view."""
    return RedirectResponse(url="/redoc", status_code=308)

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