import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import math
import httpx
import re
from typing import TypedDict, List, Literal
from urllib.parse import urlencode
from parsel import Selector
import time
from common.config import EBAY_WEBHOOK_URL
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
    follow_redirects=True
)
'''
# this is scrape result we'll receive
class ProductPreviewResult(TypedDict):
    """type hint for search scrape results for product preview data"""

    url: str  # url to full product page
    title: str
    price: str
    shipping: str
    list_date: str
    subtitles: List[str]
    condition: str
    photo: str  # image url

def parse_search(response: httpx.Response) -> List[ProductPreviewResult]:
    """parse ebay's search page for listing preview details"""
    previews = []
    # each listing has it's own HTML box where all of the data is contained
    sel = Selector(response.text)
    listing_boxes = sel.css(".srp-results li.s-item")
    for box in listing_boxes:
        if not box.css('a[data-interactions]').getall():
            continue
        # quick helpers to extract first element and all elements
        css = lambda css: box.css(css).get("").strip()
        css_all = lambda css: box.css(css).getall()
        price_text = css(".s-item__price::text")
        if css(".s-item__price .ITALIC"):
            # price is in a non-USD currency and has already been converted
            price_text = css(".s-item__price .ITALIC::text")
        if css(".s-item__price .DEFAULT"):
            price_text = css_all(".s-item__price::text")
            for i in range(0, len(price_text), 2):
                price_text = f"{price_text[i]} to {price_text[i+1]}"
        if css(".s-item__price .DEFAULT.ITALIC"):
            # price is in a non-USD currency and has already been converted
            price_text = css_all(".s-item__price .ITALIC::text")
            # check if price_text contains both italic and default classes
            price_ranges = []
            for i in range(0, len(price_text)-1, 2):
                price_range = f"{price_text[i]} to {price_text[i+2]}"
                price_ranges.append(price_range)
            price_text = ", ".join(price_ranges)
        shipping_text = css(".s-item__shipping::text")
        shipping_text = shipping_text.replace(" shipping", "")
        if not shipping_text:
            shipping_text = css(".s-item__freeXDays::text")
        if css(".s-item__shipping .ITALIC"):
            # shipping cost is in a non-USD currency and has already been converted
            shipping_text = css(".s-item__shipping .ITALIC::text")
            shipping_text = shipping_text.replace(" shipping", "")
        if css(".s-item__freeXDays .BOLD"):
            shipping_text = box.css(".s-item__freeXDays .BOLD::text").get()
        previews.append(
            {
                "url": css("a.s-item__link::attr(href)").split("?")[0],
                "title": css(".s-item__title>span::text"),
                "price": price_text,
                "shipping": shipping_text,
                "list_date": css(".s-item__listingDate span::text"),
                "subtitles": css_all(".s-item__subtitle::text"),
                "condition": css(".s-item__subtitle .SECONDARY_INFO::text"),
                "photo": css(".s-item__image-wrapper img::attr(src)"),
            }
        )
    return previews


SORTING_MAP = {
    "best_match": 12,
    "ending_soonest": 1,
    "newly_listed": 10,
}


async def scrape_search(
    query,
    max_pages=1,
    category=0,
    items_per_page=120,
    sort: Literal["best_match", "ending_soonest", "newly_listed"] = "newly_listed",
) -> List[ProductPreviewResult]:
    """Scrape Ebay's search for product preview data for given"""

    def make_request(page):
        return "https://www.ebay.com/sch/i.html?" + urlencode(
            {
                "_nkw": query,
                "_sacat": category,
                "_ipg": items_per_page,
                "_sop": SORTING_MAP[sort],
                "_pgn": page,
            }
        )
    
    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
        http2=True
    ) as session:

        first_page = await session.get(make_request(page=1))
        with open("ebay_debug.html", "w", encoding="utf-8") as f:
            f.write(first_page.text)
        print("Saved ebay_debug.html for inspection.")
        sel = Selector(first_page.text)
        header_results = sel.css("h1.srp-controls__count-heading").xpath("string()").get()
        print(f"Actual Result Count: {header_results}")
        QueryCheck = make_request(page=1)
        print(QueryCheck)
        results = parse_search(first_page)
        if not header_results:
            return results
        # find total amount of results for concurrent pagination
        match = re.search(r'(\d+,?\d*)', header_results)
        if not match:
            return results
        header_results = match.group(1).replace(',', '')
        total_pages = math.ceil(int(header_results) / items_per_page)
        if total_pages > max_pages:
            max_pages = total_pages
        if max_pages == 1:
            return results
        other_pages = [session.get(make_request(page=i)) for i in range(2, total_pages + 1)]
        additional_query_check = [make_request(page=i) for i in range(2, total_pages + 1)]
        print(additional_query_check)
        for response in asyncio.as_completed(other_pages):
            response = await response
            try:
                results.extend(parse_search(response))
            except Exception as e:
                print(f"failed to scrape search page {response.url}")

    # create a connection to the database
    conn = get_db_connection()

    # gather all the URLs from the new results
    new_urls = {result['url'] for result in results}

    # get all the existing URLs from the database
    existing_urls = set(get_all_listing_urls("ebay_results"))

    # find the URLs that are not in the database yet
    urls_to_insert = new_urls - existing_urls

    # insert the new listings into the database
    with conn:
        for result in results:
            reset_failed_parse(conn, "ebay_results", result['url'])
            if result['url'] in urls_to_insert:
                try:
                    conn.execute('''
                    INSERT INTO ebay_results (
                        url,
                        title,
                        price,
                        shipping,
                        list_date,
                        subtitles,
                        condition,
                        photo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        result['url'],
                        result['title'],
                        result['price'],
                        result['shipping'],
                        result['list_date'],
                        ', '.join(result['subtitles']),
                        result['condition'],
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
                        }, {
                            "name": "Shipping",
                            "value": result['shipping'],
                            "inline": True
                        }],
                        "thumbnail": {
                            "url": result['photo']
                        }
                    }
                    await send_discord_message(EBAY_WEBHOOK_URL, embed)
                except Exception as e:
                    print(f"Failed to insert listing into database: {e}")
                    print(f"URL: {result['url']}")
                    print(f"Result: {result}")

    # close the database connection
    conn.close()

    return results


# Example run:
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
    db_urls = set(get_all_listing_urls("ebay_results"))  # get set of all URLs in the database
    new_urls = set(result["url"] for result in all_results)  # get set of URLs in the new search results
    old_urls = db_urls - new_urls  # get set of URLs that are in the database but not in the new search results
    for url in old_urls:
        increment_failed_parse("ebay_results", url)

    # call remove_failed_listings at the end of the scrape_search function to remove the failed listings
    remove_failed_listings("ebay_results")
