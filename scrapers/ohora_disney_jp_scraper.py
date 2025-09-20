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
from googletrans import Translator
from common.config import OHORA_DISNEY_JP_WEBHOOK_URL
from common.database import get_db_connection, initialize_tables
from common.notifications import send_discord_message

# this is scrape result we'll receive
class ProductPreviewResult(TypedDict):
    """type hint for search scrape results for product preview data"""

    url: str  # url to full product page
    title: str
    price: str
    status: str  # availability status
    photo: str  # image url
    stock: int


async def parse_search(response: httpx.Response, session: httpx.AsyncClient) -> List[ProductPreviewResult]:
    """parse disney's search page for listing preview details"""
    previews = []
    # each listing has it's own HTML box where all of the data is contained
    sel = Selector(response.text)
    listing_boxes = sel.css(".product-grid__tile")

    # Create a Translator object
    translator = Translator()

    for box in listing_boxes:
        pid = box.attrib["data-pid"]
        url = f"https://shopdisney.disney.co.jp/goods/{pid}.html"
        
        # Construct the image URL
        img_url = f"https://cdns7.shopdisney.disney.co.jp/is/image/ShopDisneyJPPI/{pid}"
        
        # Get the title and translate it to English
        title = box.css("a.product__tile_link::text").get("").strip()
        
        # Fetch stock info
        api_url = f"https://store.disney.co.jp/on/demandware.store/Sites-shopDisneyJapan-Site/ja_JP/Product-Variation?pid={pid}"
        api_response = await session.get(api_url)
        status = "in stock"
        stock = 0
        try:
            product_data = api_response.json()["product"]
            stock = product_data["availability"]["ATS"]
            if stock > 0:
                status = "in stock"
            else:
                status = "sold out"
        except (KeyError, IndexError):
            # if we fail to parse, assume in stock
            pass

        previews.append(
            {
                "url": url,
                "title": title,
                "price": box.css(".value::text").get("").strip(),
                "status": status,
                "photo": img_url,
                "stock": stock,
            }
        )
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

    url = "https://store.disney.co.jp/on/demandware.store/Sites-shopDisneyJapan-Site/ja_JP/Search-UpdateGrid?cgid=ohora"
    
    async with httpx.AsyncClient(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36 Edg/113.0.1774.35",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
        http2=True
    ) as session:
        response = await session.get(url)
        results = await parse_search(response, session)

    
    # create a connection to the database
    conn = get_db_connection()

    # insert the scraped data into the table
    with conn:
        for result in results:
            try:
                # check if the listing already exists in the database
                existing_listing = conn.execute('SELECT * FROM disney_results WHERE url = ?', (result['url'],)).fetchone()
                if existing_listing is None:
                    # Translate the title here
                    translator = Translator()
                    title = result['title']
                    translated_title = translator.translate(title, dest='en').text
                    result['title'] = translated_title
                    
                    # Insert a new entry
                    conn.execute('''
                    INSERT INTO disney_results (
                        url,
                        title,
                        status,
                        price,
                        photo,
                        stock
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        result['url'],
                        result['title'],
                        result['status'],
                        result['price'],
                        result['photo'],
                        result['stock']
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
                    await send_discord_message(OHORA_DISNEY_JP_WEBHOOK_URL, embed)
                else:
                    # Update the existing entry if the price or the status has changed
                    changes = []
                    if existing_listing['price'] != result['price']:
                        changes.append(f"Price changed from {existing_listing['price']} to {result['price']}")
                    if existing_listing['status'] != result['status']:
                        changes.append(f"Status changed from {existing_listing['status']} to {result['status']}")
                    
                    alert_thresholds = [50, 40, 30, 20, 10, 5]
                    if existing_listing['stock'] and result['stock'] < existing_listing['stock']:
                        for threshold in alert_thresholds:
                            if existing_listing['stock'] > threshold and result['stock'] <= threshold:
                                changes.append(f"STOCK ALERT! Current: {result['stock']}")
                                break

                    if changes:
                        conn.execute('''
                        UPDATE disney_results
                        SET title = ?,
                            status = ?,
                            price = ?,
                            photo = ?,
                            stock = ?
                        WHERE url = ?
                        ''', (
                            result['title'],
                            result['status'],
                            result['price'],
                            result['photo'],
                            result['stock'],
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
                        await send_discord_message(OHORA_DISNEY_JP_WEBHOOK_URL, embed)

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
    initialize_tables()
    results = asyncio.run(scrape_search())
    print(f"Result Count End: {len(results)}")
    #print(results)
