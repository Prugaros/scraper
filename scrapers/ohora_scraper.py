# last update: 2023-10-10
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import httpx
import time
from typing import TypedDict, List, Literal
from urllib.parse import urlencode
from urllib.parse import urljoin
from parsel import Selector
from common.config import OHORA_WEBHOOK_URL
from common.database import get_db_connection
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
    photo: str  # image url


def parse_search(response: httpx.Response) -> List[ProductPreviewResult]:
    """parse Ohora US's search page for listing preview details"""
    previews = []
    # each listing has it's own HTML box where all of the data is contained
    sel = Selector(response.text)
    listing_boxes = sel.css(".grid div.grid__item")
    for box in listing_boxes:
        # quick helpers to extract first element and all elements
        css = lambda css: box.css(css).get("").strip()
        css_all = lambda css: box.css(css).getall()
        photo_url = None
        img_element = box.css('img')
        if img_element:
            photo_url = img_element.attrib.get('src', '').split("?")[0]
            if photo_url.startswith("//"):
                photo_url = "https:" + photo_url

        previews.append(
            {
                "url": f"https://ohora.com{css('a.product__media__holder::attr(href)')}",
                "title": css("a.product-grid-item__title::text"),
                "price": box.css(".product-grid-item__price__new::text").get(default=box.css(".product-grid-item__price::text").get("")).strip(),
                "photo": photo_url
            }
        )
        #print(f"photo: {previews[-1]['photo']}")
    return previews


SORTING_MAP = {
    "best_match": 12,
    "ending_soonest": 1,
    "newly_listed": "created-descending",
}


async def scrape_search(
    max_pages=9999,
    sort: Literal["best_match", "ending_soonest", "newly_listed"] = "newly_listed",
) -> List[ProductPreviewResult]:
    """Scrape Ebay's search for product preview data for given"""

    def make_request(page):
        return "https://ohora.com/collections/all-products?" + urlencode(
            {
                "sort_by": SORTING_MAP[sort],
                "page": page,
            }
        )

    results = []
    page = 1

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 Edg/113.0.1774.35",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
        },
        http2=True
    ) as session:
        while True:
            response = await session.get(make_request(page))
            query_check = make_request(page)
            print(f"Query Check: {query_check}")
            sel = Selector(response.text)
            page_results = parse_search(response)
            results.extend(page_results)
            # check if there are more pages to scrape
            show_more_button = sel.css(".next a")
            if not show_more_button:
                print("No more pages to scrape")
                break
            # extract URL from the "Next page" button and use it to make a new request
            next_page_url = show_more_button.attrib["href"]
            next_page_url = urljoin(str(response.url), next_page_url)
            response = await session.get(next_page_url)
            page += 1
            print(f"Page: {page}")
            # check if we've reached the maximum number of pages to scrape
            if page > max_pages:
                break

    
    # create a connection to the database
    conn = get_db_connection()

    # insert the scraped data into the table
    with conn:
        for result in results:
            try:
                # check if the listing already exists in the database
                existing_listing = conn.execute('SELECT * FROM ohora_results WHERE url = ?', (result['url'],)).fetchone()
                if existing_listing is None:
                    conn.execute('''
                    INSERT INTO ohora_results (
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
                    #print(f"New Listing: {result['url']}")
                    
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
                    await send_discord_message(OHORA_WEBHOOK_URL, embed)
                    
            except Exception as e:
                print(f"Failed to insert listing into database: {e}")
                print(f"URL: {result['url']}")
                print(f"Result: {result}")

    # close the database connection
    conn.close()

    return results


# Example run:
if __name__ == "__main__":
    import asyncio
    results = asyncio.run(scrape_search())
    print(f"Result Count End: {len(results)}")
    #print(results)

'''
if __name__ == "__main__":
    url = "https://ohora.com/collections/all-products?sort_by=created-descending&page=1"
    response = httpx.get(url)
    previews = parse_search(response)
    for preview in previews:
        print(preview)
'''
