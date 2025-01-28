from fastapi import FastAPI, Query, HTTPException
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
from typing import List, Dict, Optional
from aiohttp import ClientTimeout

# Enhanced logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Custom timeout for HTTP requests
TIMEOUT = ClientTimeout(total=30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing FastAPI Cache")
    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
    yield
    logger.info("Shutting down application")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def fetch(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch the HTML content of a URL asynchronously with better error handling."""
    try:
        async with session.get(url, timeout=TIMEOUT) as response:
            if response.status != 200:
                logger.error(f"Error fetching {url}: Status {response.status}")
                raise HTTPException(status_code=response.status, detail=f"Failed to fetch {url}")
            return await response.text()
    except asyncio.TimeoutError:
        logger.error(f"Timeout while fetching {url}")
        raise HTTPException(status_code=504, detail="Request timeout")
    except Exception as e:
        logger.error(f"Error fetching {url}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch {url}: {str(e)}")

async def scrape_quotes_toscrape(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Scrape quotes from quotes.toscrape.com with better error handling."""
    quotes = []
    try:
        for quote in soup.find_all("div", class_="quote"):
            text = quote.find("span", class_="text")
            author = quote.find("small", class_="author")
            if text and author:
                quotes.append({
                    "text": text.text.strip(' "'),
                    "author": author.text.strip(),
                    "source": "toscrape"
                })
    except Exception as e:
        logger.error(f"Error parsing toscrape quotes: {str(e)}")
    return quotes

async def scrape_quotes_goodreads(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Scrape quotes from goodreads.com with better error handling."""
    quotes = []
    try:
        for quote in soup.find_all("div", class_="quoteText"):
            text_parts = quote.get_text(strip=True).split("―")
            author = quote.find("span", class_="authorOrTitle")
            if text_parts and author:
                quotes.append({
                    "text": text_parts[0].strip(' "'),
                    "author": author.text.strip(),
                    "source": "goodreads"
                })
    except Exception as e:
        logger.error(f"Error parsing goodreads quotes: {str(e)}")
    return quotes

async def scrape_url(session: aiohttp.ClientSession, url: str) -> List[Dict[str, str]]:
    """Scrape quotes from a single URL with enhanced error handling."""
    try:
        html = await fetch(session, url)
        soup = BeautifulSoup(html, "html.parser")
        
        if "toscrape" in url:
            return await scrape_quotes_toscrape(soup)
        elif "goodreads" in url:
            return await scrape_quotes_goodreads(soup)
        else:
            logger.warning(f"Unsupported URL format: {url}")
            return []
    except Exception as e:
        logger.error(f"Error scraping {url}: {str(e)}")
        return []

@app.get("/", response_class=JSONResponse)
@cache(expire=300)
async def get_quotes(
    category: Optional[str] = Query(None, description="Category of quotes to scrape")
) -> Dict[str, List[Dict[str, str]]]:
    """
    Fetch quotes from multiple sources with optional category filtering.
    Returns a JSON response with the combined quotes.
    """
    logger.info(f"Processing request for category: {category}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    base_urls = {
        "toscrape": "http://quotes.toscrape.com",
        "goodreads": "https://www.goodreads.com/quotes"
    }

    urls = []
    if category:
        category = category.lower().strip()
        for key, base_url in base_urls.items():
            urls.append(f"{base_url}/tag/{category}")
    else:
        urls = list(base_urls.values())

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
            
            logger.info(f"Retrieved {len(all_quotes)} quotes")
            return {"quotes": all_quotes}
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8080, reload=True)