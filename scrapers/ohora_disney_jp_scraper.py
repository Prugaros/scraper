import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from typing import List, Dict, Any, Optional
from parsel import Selector
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
            # Translate title to English using common translation utility
            print(f"[{self.table_name}] Translating title: {result['title']}")
            result['title'] = clean_product_name(result['title'])
            print(f"[{self.table_name}] Translated to: {result['title']}")
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
            # Add comprehensive headers to mimic a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://shopdisney.disney.co.jp/',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Cache-Control': 'max-age=0',
            }
            
            response = await session.get(url, headers=headers, timeout=30.0)
            sel = Selector(response.text)

            # DEBUG: Log response details
            print(f"[{self.table_name}] Response status: {response.status_code}")
            print(f"[{self.table_name}] Response HTML length: {len(response.text)} chars")
            print(f"[{self.table_name}] First 500 chars: {response.text[:500]}")

            product_data = {}
            
            # --- Disney JP Scraping Logic ---
            
            # 1. Title
            title = sel.css('h1.product-name::text').get()
            if not title:
                title = sel.css('.product-detail h1::text').get()
            
            # DEBUG: Log title extraction
            print(f"[{self.table_name}] Title extracted: '{title}'")
            print(f"[{self.table_name}] h1.product-name found: {bool(sel.css('h1.product-name'))}")
            print(f"[{self.table_name}] .product-detail h1 found: {bool(sel.css('.product-detail h1'))}")
            
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
            # Disney JP uses <span class="value" content="2200"> inside .prices div
            msrp = 0.0
            price_content = sel.css('.prices .value::attr(content)').get()
            
            # DEBUG: Log price extraction
            print(f"[{self.table_name}] Price content attribute: '{price_content}'")
            print(f"[{self.table_name}] .prices found: {bool(sel.css('.prices'))}")
            print(f"[{self.table_name}] .prices .value found: {bool(sel.css('.prices .value'))}")
            
            if price_content:
                try:
                    msrp = float(price_content)
                except ValueError:
                    # Fallback to text extraction if content attribute fails
                    import re
                    price_text = sel.css('.prices .value::text').get()
                    if price_text:
                        digits = re.sub(r'[^\d]', '', price_text)
                        if digits:
                            msrp = float(digits)
            product_data['MSRP'] = msrp
            print(f"[{self.table_name}] Final MSRP: {msrp}")

            # 4. Images
            # Disney JP stores images in thumbnail carousel with data-image-base attributes
            image_urls = []
            
            # Get base image URLs from thumbnail carousel
            base_urls = sel.css('.thumbnail-carousel__item::attr(data-image-base)').getall()
            
            # DEBUG: Log image extraction
            print(f"[{self.table_name}] Found {len(base_urls)} image base URLs")
            print(f"[{self.table_name}] .thumbnail-carousel__item found: {len(sel.css('.thumbnail-carousel__item'))}")
            if base_urls:
                print(f"[{self.table_name}] First image URL: {base_urls[0]}")
            
            # Convert base URLs to high-res image URLs
            # Disney uses format: base_url?fmt=jpeg&qlt=60&wid=WIDTH&hei=HEIGHT&fit=fit,1
            for base_url in base_urls:
                if base_url:
                    # Request high quality images (1000x1000)
                    full_url = f"{base_url}?fmt=jpeg&qlt=90&wid=1000&hei=1000&fit=fit,1"
                    image_urls.append(full_url)
            
            # Deduplicate while preserving order
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
