import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from typing import List, Dict, Any, Optional
from common.config import OHORA_JP_WEBHOOK_URL
from common.store_api import get_jpy_to_usd_rate, calculate_usd_price, upload_images
from common.translation import clean_product_name
from scrapers.base import BaseScraper
from parsel import Selector

class OhoraJPScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            table_name='OhoraJP_results',
            webhook_url=OHORA_JP_WEBHOOK_URL,
            upload_new_products=True,  # Enable new product uploads
            sync_product_statuses=False,  # Statuses synced via batch update
            brand_name='Ohora'
        )

    def parse_search(self, products_json) -> List[Dict[str, Any]]:
        """parse the products.json response for product preview details"""
        previews = []
        for product in products_json['products']:
            # Check if ANY variant is available
            is_available = any(v['available'] for v in product['variants'])
            status = 'in stock' if is_available else 'sold out'
            
            # Use first variant for price/other details
            variant = product['variants'][0]
            previews.append(
                {
                    "url": f"https://ohora.co.jp/products/{product['handle']}",
                    "title": product['title'],
                    "price": f"¥{variant['price']}",
                    "status": status,
                    "photo": product['images'][0]['src'] if product['images'] else None
                }
            )
        return previews

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Ohora JP's products.json for product preview data"""
        
        def make_request(page):
            return f"https://ohora.co.jp/products.json?limit=250&page={page}"

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

    async def scrape_product_details(self, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Scrape detailed information from a single product page for store upload."""
        session = kwargs.get('session')
        brand_id = kwargs.get('brand_id')
        
        if not session or not brand_id:
            print(f"[{self.table_name}] Missing session or brand_id for {url}")
            return None
        
        # Get exchange rate
        jpy_to_usd_rate = get_jpy_to_usd_rate()
        if not jpy_to_usd_rate:
            print(f"[{self.table_name}] Failed to get exchange rate for {url}")
            return None
        
        try:
            headers = {
                "Referer": "https://ohora.co.jp/collections/all-products"
            }
            response = await session.get(url, headers=headers)
            sel = Selector(response.text)

            # Extract data from JSON-LD script for reliability
            json_ld_script = sel.css('script[type="application/ld+json"]::text').get()
            product_data = {}
            
            if json_ld_script:
                import json
                try:
                    data = json.loads(json_ld_script)
                    product_data['name'] = data.get('name')
                    product_data['description'] = data.get('description')
                    product_data['sku'] = data.get('sku')
                    if 'offers' in data and data['offers']:
                        product_data['MSRP'] = float(data['offers'][0].get('price', 0))
                        availability = data['offers'][0].get('availability')
                        product_data['is_active'] = "InStock" in availability if availability else False
                except json.JSONDecodeError:
                    print(f"[{self.table_name}] Error decoding JSON-LD for {url}")

            # Fallback or supplement with direct HTML scraping if needed
            if 'name' not in product_data or not product_data['name']:
                product_data['name'] = sel.css('h1.product-single__title::text').get("").strip()
            
            # Translate Japanese name to English
            if product_data.get('name'):
                product_data['name'] = clean_product_name(product_data['name'])
            if 'MSRP' not in product_data or not product_data['MSRP']:
                price_text = sel.css('.product__price::text').re_first(r'[\d,]+')
                product_data['MSRP'] = float(price_text.replace(',', '')) if price_text else 0.0
            if 'description' not in product_data or not product_data['description']:
                product_data['description'] = sel.css('.product-block .rte p::text').get("").strip()
            if 'sku' not in product_data or not product_data['sku']:
                product_data['sku'] = sel.css('.product-single__sku span[data-sku-id]::text').get("").strip()

            # Scrape image URLs
            image_urls = sel.css('.product__main-photos img::attr(data-photoswipe-src)').getall()
            if not image_urls:
                # Fallback for different image gallery structures
                image_urls = sel.css('.product__thumb a::attr(href)').getall()
            
            # Get token from kwargs (passed by process_results_with_store_updates)
            # We need to import and get token here since we need it for upload_images
            from common.store_api import get_admin_token
            token = await get_admin_token()
            if not token:
                print(f"[{self.table_name}] Failed to get token for image upload")
                product_data['images'] = []
            else:
                # Upload images
                product_data['images'] = await upload_images(image_urls, session, token)
            
            # Calculate USD price
            jpy_msrp = product_data.get('MSRP', 0.0)
            product_data['price'] = calculate_usd_price(jpy_msrp, jpy_to_usd_rate)
            product_data['product_url'] = url
            product_data['brandId'] = brand_id

            print(f"[{self.table_name}] Scraped details for {product_data.get('name')}")
            return product_data
            
        except Exception as e:
            print(f"[{self.table_name}] Error scraping product details for {url}: {e}")
            return None

async def scrape_search():
    scraper = OhoraJPScraper()
    return await scraper.run()

if __name__ == "__main__":
    asyncio.run(scrape_search())

