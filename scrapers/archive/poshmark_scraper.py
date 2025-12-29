import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import httpx
import time
from typing import TypedDict, List, Literal
from urllib.parse import urlencode
from parsel import Selector
from common.config import POSHMARK_WEBHOOK_URL
from common.database import (
    get_db_connection,
    get_all_listing_urls,
    increment_failed_parse,
    remove_failed_listings,
    reset_failed_parse,
)
from common.notifications import send_discord_message
'''
session = httpx.AsyncClient(
    # for our HTTP headers we want to use a real browser's default headers to prevent being blocked
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 Edg/113.0.1774.35",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    },
    # Enable HTTP2 version of the protocol to prevent being blocked
    http2=True,
    # enable automatic follow of redirects
    follow_redirects=True,
    timeout=10.0
)
'''
# this is scrape result we'll receive
class ProductPreviewResult(TypedDict):
    """type hint for search scrape results for product preview data"""

    url: str  # url to full product page
    title: str
    price: str


def parse_search(response: httpx.Response) -> List[ProductPreviewResult]:
    """parse poshmark's search page for listing preview details"""
    previews = []
    # each listing has it's own HTML box where all of the data is contained
    sel = Selector(response.text)
    listing_boxes = sel.css('div[data-et-name="listing"]')
    for box in listing_boxes:
        # quick helpers to extract first element and all elements
        css = lambda css: box.css(css).get("").strip()
        css_all = lambda css: box.css(css).getall()
        photo_select = box.css('a.tile__covershot img::attr(data-src)')
        photo_content = photo_select.get()
        if not photo_content:
            photo_select = box.css('a.tile__covershot img::attr(src)')
            photo_content = photo_select.get()
        photo_content = photo_content.replace("/s_", "/")
        previews.append(
            {
                "url": "https://poshmark.com" + css("a.tile__covershot::attr(href)"),
                "title": css("a.tile__title::text"),
                "price": css("span.p--t--1::text"),
                "photo": photo_content,
            }
        )
    return previews


SORTING_MAP = {
    "best_match": 12,
    "ending_soonest": 1,
    "Just_In": "added_desc",
}


async def scrape_search(
    query,
    max_pages=None,
    items_per_page=48,
    sort: Literal["best_match", "ending_soonest", "Just_In"] = "Just_In",
) -> List[ProductPreviewResult]:
    """Scrape Poshmark's search for product preview data for given"""

    def make_request(page):
        return "https://poshmark.com/search?" + urlencode(
            {
                "query": query,
                "sort_by": SORTING_MAP[sort],
                "max_id": page
            }
        )

    results = []
    page = 1

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 Edg/113.0.1774.35",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
        http2=True
    ) as session:
        while True:
            response = await session.get(make_request(page))
            QueryCheck = make_request(page)
            print(QueryCheck)
            #print(response.text)  # print the raw HTML content
            sel = Selector(response.text)
            results.extend(parse_search(response))
            next_button = sel.css('button.btn--pagination:contains("Next"):not([disabled])')
            if not next_button:
                break
            page += 1
            if max_pages is not None and page > max_pages:
                break

    # create a connection to the database
    conn = get_db_connection()

    # gather all the URLs from the new results
    new_urls = {result['url'] for result in results}

    # get all the existing URLs from the database
    existing_urls = set(get_all_listing_urls("poshmark_results"))

    # find the URLs that are not in the database yet
    urls_to_insert = new_urls - existing_urls

    # insert the new listings into the database
    with conn:
        for result in results:
            reset_failed_parse(conn, "poshmark_results", result['url'])
            if result['url'] in urls_to_insert:
                try:
                    conn.execute('''
                    INSERT INTO poshmark_results (
                        url,
                        title,
                        price,
                        photo
                    ) VALUES (?, ?, ?, ?)
                    ''', (
                        result['url'],
                        result['title'],
                        result['price'],
                        result['photo']
                    ))
                    # Print new listing
                    print(f"New Listing: {result['url']}")

                    # Send a message to the Discord channel
                    embed = {
                        "title": result['title'],
                        "url": result['url'],
                        "color": 0x00ff00,
                        "fields": [{
                            "name": "Price",
                            "value": result['price'],
                            "inline": True
                        }],
                        "thumbnail": {
                            "url": result['photo']
                        }
                    }
                    await send_discord_message(POSHMARK_WEBHOOK_URL, embed)
                except Exception as e:
                    print(f"Failed to insert listing into database: {e}")
                    print(f"URL: {result['url']}")
                    print(f"Result: {result}")

    # close the database connection
    conn.close()

    return results


if __name__ == "__main__":
    # create a list of search phrases
    search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora", "ohora nail", "ohora gel", "ohora nail gel", "ohora nail gel semi", "ohora nail gel semi cured", "ohora nail gel semi cured gel", "ohora nail gel semi cured"]
    all_results = []
    seen_urls = set()  # set to keep track of unique URLs
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for phrase in search_phrases:
        results = loop.run_until_complete(scrape_search(phrase))
        for result in results:
            if result["url"] not in seen_urls:
                all_results.append(result)
                seen_urls.add(result["url"])
    print(f"Unique Result Count: {len(all_results)}")

    # remove old listings from the database
    db_urls = set(get_all_listing_urls("poshmark_results"))  # get set of all URLs in the database
    new_urls = set(result["url"] for result in all_results)  # get set of URLs in the new search results
    old_urls = db_urls - new_urls  # get set of URLs that are in the database but not in the new search results
    for url in old_urls:
        increment_failed_parse("poshmark_results", url)

    # call remove_failed_listings at the end of the scrape_search function to remove the failed listings
    remove_failed_listings("poshmark_results")
