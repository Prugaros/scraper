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
    status: str  # availability status
    photo: str  # image url


def parse_search(products_json) -> List[ProductPreviewResult]:
    """parse the products.json response for product preview details"""
    previews = []
    for product in products_json['products']:
        variant = product['variants'][0]
        status = 'in stock' if variant['available'] else 'sold out'
        previews.append(
            {
                "url": f"https://ohora.com/products/{product['handle']}",
                "title": product['title'],
                "price": f"${variant['price']}",
                "status": status,
                "photo": product['images'][0]['src'] if product['images'] else None
            }
        )
    return previews


SORTING_MAP = {
    "best_match": 12,
    "ending_soonest": 1,
    "newly_listed": "created-descending",
}


async def scrape_search() -> List[ProductPreviewResult]:
    """Scrape Ohora US's products.json for product preview data"""

    def make_request(page):
        return f"https://ohora.com/products.json?limit=250&page={page}"

    results = []
    page = 1

    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        },
        http2=True
    ) as session:
        while True:
            response = await session.get(make_request(page))
            products_json = response.json()
            if not products_json['products']:
                break
            
            page_results = parse_search(products_json)
            results.extend(page_results)
            page += 1
            print(f"Scraped page {page-1}")

    
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
                        status,
                        photo
                    ) VALUES (?, ?, ?, ?, ?)
                    ''', (
                        result['url'],
                        result['title'],
                        result['price'],
                        result['status'],
                        result['photo']
                    ))
                    # Print new listing
                    #print(f"New Listing: {result['url']}")
                    
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
                    await send_discord_message(OHORA_WEBHOOK_URL, embed)
                else:
                    # Update the existing entry if the price or the status has changed
                    changes = []
                    if existing_listing['price'] != result['price']:
                        changes.append(f"Price changed from {existing_listing['price']} to {result['price']}")
                    if existing_listing['status'] != result['status']:
                        changes.append(f"Status changed from {existing_listing['status']} to {result['status']}")
                    if changes:
                        conn.execute('''
                        UPDATE ohora_results
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
