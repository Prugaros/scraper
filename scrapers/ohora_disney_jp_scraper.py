import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from typing import List, Dict, Any, Optional
from parsel import Selector
from googletrans import Translator
from common.config import OHORA_DISNEY_JP_WEBHOOK_URL
from common.database import initialize_tables
from scrapers.base import BaseScraper
from common.store_api import get_jpy_to_usd_rate, calculate_usd_price, upload_images
from common.translation import clean_product_name


class DisneyScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            table_name='disney_results', 
            webhook_url=OHORA_DISNEY_JP_WEBHOOK_URL,
            upload_new_products=True,
            sync_product_statuses=False,  # Statuses synced via batch update
            brand_name='Ohora' # Assuming Disney Ohora collabs go under Ohora or need specific brand
        )
        self.translator = Translator()

    async def parse_search(self, response, session) -> List[Dict[str, Any]]:
        """parse disney's search page for listing preview details"""
        previews = []
        sel = Selector(response.text)
        listing_boxes = sel.css(".product-grid__tile")

        for box in listing_boxes:
            pid = box.attrib["data-pid"]
            url = f"https://shopdisney.disney.co.jp/goods/{pid}.html"
            
            # Construct the image URL
            img_url = f"https://cdns7.shopdisney.disney.co.jp/is/image/ShopDisneyJPPI/{pid}"
            
            # Get the title (Japanese)
            title = box.css("a.product__tile_link::text").get("").strip()
            
            # Fetch stock info
            api_url = f"https://store.disney.co.jp/on/demandware.store/Sites-shopDisneyJapan-Site/ja_JP/Product-Variation?pid={pid}"
            
            status = "in stock"
            stock = 0
            try:
                # Need to be careful with rate limits on this internal API
                api_response = await session.get(api_url)
                product_data = api_response.json().get("product", {})
                availability = product_data.get("availability", {})
                stock = availability.get("ATS", 0)
                
                if stock > 0:
                    status = "in stock"
                else:
                    status = "sold out"
            except Exception:
                # if we fail to parse, assume in stock/0 or keep default
                pass

            previews.append(
                {
                    "url": url,
                    "title": title, # Japanese title, will be translated on insert
                    "price": box.css(".value::text").get("").strip(),
                    "status": status,
                    "photo": img_url,
                    "stock": stock,
                }
            )
        return previews

    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Disney JP's search results"""
        url = "https://store.disney.co.jp/on/demandware.store/Sites-shopDisneyJapan-Site/ja_JP/Search-UpdateGrid?cgid=ohora&sz=100"
        
        async with await self.get_client() as session:
            try:
                # Add headers to mimic browser to avoid blocks
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': 'https://shopdisney.disney.co.jp/'
                })
                response = await session.get(url)
                results = await self.parse_search(response, session)
                return results
            except Exception as e:
                print(f"[{self.table_name}] Error scraping: {e}")
                return []

    async def handle_new_listing(self, conn, result: Dict[str, Any]):
        """Override to translate title before inserting"""
        try:
            # Translate title to English
            print(f"[{self.table_name}] Translating title: {result['title']}")
            translated = await asyncio.to_thread(self.translator.translate, result['title'], dest='en')
            if translated and translated.text:
                result['title'] = translated.text
        except Exception as e:
            print(f"[{self.table_name}] Translation failed for {result['url']}: {e}")
        
        # Proceed with standard insert and notification
        await super().handle_new_listing(conn, result)

    async def scrape_product_details(self, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Scrape detailed information from a single product page for store upload."""
        session = kwargs.get('session')
        brand_id = kwargs.get('brand_id')
        
        if not session or not brand_id:
            return None
        
        # Get exchange rate
        jpy_to_usd_rate = get_jpy_to_usd_rate()
        
        try:
            response = await session.get(url)
            sel = Selector(response.text)

            product_data = {}
            
            # --- Disney JP Scraping Logic ---
            
            # 1. Title
            title = sel.css('h1.product-name::text').get()
            if not title:
                title = sel.css('.product-detail h1::text').get()
            product_data['name'] = title.strip() if title else "Unknown Product"

            # Translate Title
            product_data['name'] = clean_product_name(product_data['name'])

            # 2. Description
            # Disney descriptions are often in .product-description or .description
            desc = sel.css('.product-description').get() # Get HTML
            if not desc:
                 desc = sel.css('.description').get()
            product_data['description'] = desc if desc else ""

            # 3. Price (MSRP)
            # Usually in .price-sales or .price-standard
            price_text = sel.css('.price-sales::text').get()
            if not price_text:
                price_text = sel.css('.price-standard::text').get()
            
            # Clean price string (remove '¥', ',', etc.)
            msrp = 0.0
            if price_text:
                 import re
                 digits = re.sub(r'[^\d]', '', price_text)
                 if digits:
                     msrp = float(digits)
            product_data['MSRP'] = msrp

            # 4. Images
            # Primary image
            image_urls = []
            
            # Try to grab from JSON data often found in data attributes or specific scripts
            # Fallback to selectors
            imgs = sel.css('.product-image-container img::attr(src)').getall()
            if not imgs:
                imgs = sel.css('.primary-image::attr(src)').getall()
            
            # Disney mostly uses hi-res images via specific CDNS domains
            # Try to upgrade resolution if possible, or just take what we get
            image_urls = [url for url in imgs if url.startswith('http')]
            # Deduplicate
            image_urls = list(dict.fromkeys(image_urls))

            # Upload images
            from common.store_api import get_admin_token
            token = await get_admin_token()
            if token:
                product_data['images'] = await upload_images(image_urls[:10], session, token)
            else:
                product_data['images'] = []
            
            # 5. Status
            # We assume active if we can scrape it, or check availability text
            # Accessing availability often requires API calls (like in search), 
            # but for upsert "Active" is usually fine to default to True (1)
            # We let the batch updater handle exact boolean status later
            product_data['is_active'] = 1 

            # Calculate USD price
            product_data['price'] = calculate_usd_price(msrp, jpy_to_usd_rate)
            product_data['product_url'] = url
            product_data['brandId'] = brand_id

            print(f"[{self.table_name}] Scraped details for {product_data.get('name')}")
            return product_data
            
        except Exception as e:
            print(f"[{self.table_name}] Error scraping product details for {url}: {e}")
            return None


async def scrape_search():
    # Ensure tables exist (legacy requirement)
    initialize_tables()
    scraper = DisneyScraper()
    return await scraper.run()


if __name__ == "__main__":
    asyncio.run(scrape_search())
