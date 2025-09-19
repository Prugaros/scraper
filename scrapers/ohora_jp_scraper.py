# last update: 2023-11-12
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import httpx
import time
import re
import math
import sqlite3
from typing import TypedDict, List, Literal
from urllib.parse import urlencode
from urllib.parse import urljoin
from parsel import Selector
from common.config import OHORA_JP_WEBHOOK_URL
from common.database import get_db_connection
from common.notifications import send_discord_message

# this is scrape result we'll receive
class ProductPreviewResult(TypedDict):
    """type hint for search scrape results for product preview data"""

    url: str  # url to full product page
    title: str
    price: str
    status: str  # availability status
    photo: str  # image url


def parse_search(response: httpx.Response) -> List[ProductPreviewResult]:
    """parse ebay's search page for listing preview details"""
    previews = []
    # each listing has it's own HTML box where all of the data is contained
    sel = Selector(response.text)
    #print(f"Response: {response.text}")
    listing_boxes = sel.css(".boost-pfs-filter-products div.boost-pfs-filter-product-item")
    for box in listing_boxes:
        # quick helpers to extract first element and all elements
        css = lambda css: box.css(css).get("").strip()
        css_all = lambda css: box.css(css).getall()

        url = f"https://ohora.co.jp{css('a.boost-pfs-filter-product-item-title::attr(href)')}"
        url = url.rsplit('#', 1)[0]

        # Extract the image URL
        img_url = box.css('img.boost-pfs-filter-product-item-main-image.lazyload.Image--lazyLoad::attr(data-src)').get()
        if img_url:
            img_url = 'https:' + img_url.strip()

        # Check if the item is sold out
        if box.css('.sold-out'):
            status = 'sold out'
        else:
            status = 'in stock'

        previews.append(
            {
                "url": url,
                "title": box.css("a.boost-pfs-filter-product-item-title::text").get("").strip(),
                "price": box.css(".boost-pfs-filter-product-item-price span::text").get("").strip(),
                "status": status,
                "photo": img_url
            }
        )
    return previews

'''
SORTING_MAP = {
    "best_match": 12,
    "ending_soonest": 1,
    "newly_listed": "created-descending",
}
'''

async def scrape_search(
    max_pages=9999,
    sort: Literal["best_match", "ending_soonest", "newly_listed"] = "newly_listed",
) -> List[ProductPreviewResult]:
    """Scrape Ebay's search for product preview data for given"""

    def make_request(page):
        return f"https://ohora.co.jp/collections/all-products?page={page}"

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
            # Extract total number of items from the HTML
            match = re.search(r'"items":(\d+)', response.text)
            if match:
                total_items = int(match.group(1))
                total_pages = math.ceil(total_items / 24)
                #print(f'Total items: {total_items}')
            else:
                print('Could not find total items in HTML')

            query_check = make_request(page)
            print(f"Query Check: {query_check}")
            sel = Selector(response.text)
            page_results = parse_search(response)
            results.extend(page_results)
            page += 1
            print(f"Page: {page}")
            # check if we've reached the maximum number of pages to scrape
            if page > min(max_pages, total_pages):
                break

    
    # create a connection to the database
    conn = get_db_connection()

    # insert the scraped data into the table
    with conn:
        for result in results:
            try:
                # check if the listing already exists in the database
                existing_listing = conn.execute('SELECT * FROM OhoraJP_results WHERE url = ?', (result['url'],)).fetchone()
                if existing_listing is None:
                    # Insert a new entry
                    conn.execute('''
                    INSERT INTO OhoraJP_results (
                        url,
                        title,
                        status,
                        price,
                        photo
                    ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        result['url'],
                        result['title'],
                        result['status'],
                        result['price'],
                        result['photo']
                    ))
                    # Send a message to the Discord channel
                    embed = {
                        "title": f"New Listing: {result['title']}",
                        "url": result['url'],
                        "color": 0x00ff00,
                        "fields": [{
                            "name": "Price",
                            "value": result['price'],
                            "inline": True
                        },
                        {
                            "name": "Status",
                            "value": result['status'],
                            "inline": True
                        }],
                        "thumbnail": {
                            "url": result['photo']
                        }
                    }
                    await send_discord_message(OHORA_JP_WEBHOOK_URL, embed)
                else:
                    # Update the existing entry if the price or the status has changed
                    changes = []
                    if existing_listing['price'] != result['price']:
                        changes.append(f"Price changed from {existing_listing['price']} to {result['price']}")
                    if existing_listing['status'] != result['status']:
                        changes.append(f"Status changed from {existing_listing['status']} to {result['status']}")
                    if changes:
                        conn.execute('''
                        UPDATE OhoraJP_results
                        SET title = ?,
                            status = ?,
                            price = ?,
                            photo = ?
                        WHERE url = ?
                        ''', (
                            result['title'],
                            result['status'],
                            result['price'],
                            result['photo'],
                            result['url']
                        ))
                        # Send a message to the Discord channel
                        embed = {
                            "title": f"Listing Updated: {result['title']}",
                            "url": result['url'],
                            "color": 0x00ff00,
                            "fields": [{
                                "name": "Changes",
                                "value": ', '.join(changes),
                                "inline": False
                            }, {
                                "name": "Price",
                                "value": result['price'],
                                "inline": True
                            }],
                            "thumbnail": {
                                "url": result['photo']
                            }
                        }
                        await send_discord_message(OHORA_JP_WEBHOOK_URL, embed)

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
