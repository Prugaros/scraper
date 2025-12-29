import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from typing import List, Dict, Any
from common.config import OHORA_WEBHOOK_URL
from scrapers.base import BaseScraper

class OhoraScraper(BaseScraper):
    def __init__(self):
        super().__init__(table_name='ohora_results', webhook_url=OHORA_WEBHOOK_URL)

    def parse_search(self, products_json) -> List[Dict[str, Any]]:
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

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Ohora US's products.json for product preview data"""
        
        def make_request(page):
            return f"https://ohora.com/products.json?limit=250&page={page}"

        results = []
        page = 1

        async with await self.get_client() as session:
            while True:
                try:
                    response = await session.get(make_request(page))
                    products_json = response.json()
                    
                    if not products_json.get('products'):
                        break
                    
                    page_results = self.parse_search(products_json)
                    results.extend(page_results)
                    page += 1
                    print(f"[{self.table_name}] Scraped page {page-1}")
                except Exception as e:
                    print(f"[{self.table_name}] Error scraping page {page}: {e}")
                    break
                    
        return results

async def scrape_search():
    scraper = OhoraScraper()
    return await scraper.run()

if __name__ == "__main__":
    asyncio.run(scrape_search())

