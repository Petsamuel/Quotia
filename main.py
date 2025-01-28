from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
import aiohttp
import asyncio
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from fastapi_cache.decorator import cache
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code to run on startup
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    yield
    # Code to run on shutdown (if needed)

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],   
    allow_headers=["*"],   
)

async def fetch(session, url):
    """Fetch the HTML content of a URL asynchronously."""
    async with session.get(url) as response:
        return await response.text()

async def scrape_quotes_toscrape(soup):
    """Scrape quotes from http://quotes.toscrape.com."""
    quotes = []
    for quote in soup.find_all("div", class_="quote"):
        text = quote.find("span", class_="text").text
        author = quote.find("small", class_="author").text
        quotes.append({"text": text, "author": author})
    return quotes

async def scrape_quotes_goodreads(soup):
    """Scrape quotes from https://www.goodreads.com/quotes."""
    quotes = []
    for quote in soup.find_all("div", class_="quoteText"):
        text = quote.get_text(strip=True).split("―")[0].strip()
        author = quote.find("span", class_="authorOrTitle").text.strip()
        quotes.append({"text": text, "author": author})
    return quotes

async def scrape_url(session, url):
    """Scrape quotes from a single URL."""
    try:
        html = await fetch(session, url)
        soup = BeautifulSoup(html, "html.parser")

        if "toscrape" in url:
            return await scrape_quotes_toscrape(soup)
        elif "goodreads" in url:
            return await scrape_quotes_goodreads(soup)
        else:
            return []
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return []



@app.get("/", response_class=JSONResponse)
@cache(expire=300) # Cache the response for 300 seconds
async def getQuotes(category: str = Query(None, description="Category of quotes to scrape")):
    logger.debug("Root endpoint called")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    base_urls = {
        "toscrape": "http://quotes.toscrape.com",
        "goodreads": "https://www.goodreads.com/quotes"
    }

    urls = []
    if category:
        for key, base_url in base_urls.items():
            urls.append(f"{base_url}/tag/{category}")
    else:
        urls = list(base_urls.values())

    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [scrape_url(session, url) for url in urls]
        results = await asyncio.gather(*tasks)
        all_quotes = [quote for result in results for quote in result]
        return {"quotes": all_quotes}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)