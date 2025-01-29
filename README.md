# Web Scraping Quote Generator

This project demonstrates how to perform asynchronous web scraping using FastAPI, aiohttp, and BeautifulSoup. The application scrapes quotes from two websites: [Quotes to Scrape](http://quotes.toscrape.com) and [Goodreads Quotes](https://www.goodreads.com/quotes).

## Requirements

- Python 3.8+
- FastAPI
- aiohttp
- BeautifulSoup4
- Requests

## Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/Petsamuel/Quotes.git
   
    ```

2. Create a virtual environment and activate it:

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the dependencies:

    ```bash
    pip install -r requirements.txt
    ```

## Running the Application

1. Start the FastAPI server:

    ```bash
    uvicorn main:app --reload
    ```

2. Open your browser and navigate to `http://127.0.0.1:8000/` to see the scraped quotes.

## Project Files

- [main.py](./main.py): The main FastAPI application file that handles the asynchronous scraping.
- [requirements.txt](./requirements.txt): Contains all the dependencies  
<!-- - `async_scraper.py`: Contains the asynchronous scraping logic. -->
<!-- - `parser.py`: Contains the parsing logic for the scraped HTML content. -->
<!-- - `helpers.py`: Utility functions used in the project. -->
<!-- - `test_scraper.py`: Unit tests for the scraping functions. -->

## Usage

The application scrapes quotes from the specified URLs and returns them as a JSON response. The scraping is done asynchronously to improve performance and handle multiple requests concurrently.

## License

This project is licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.
