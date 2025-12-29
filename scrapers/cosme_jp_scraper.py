"""Cosme Japan scraper - fetches product data from shop-cosmedebeaute.com"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from common.config import COSME_WEBHOOK_URL
from common.store_api import get_jpy_to_usd_rate, calculate_usd_price, upload_images
from common.translation import clean_product_name
from scrapers.base import BaseScraper
from parsel import Selector


class CosmeScraper(BaseScraper):
    """Scraper for Cosme Japan products using JSON endpoint"""
    
    def __init__(self):
        super().__init__(
            table_name="cosme_results",
            webhook_url=COSME_WEBHOOK_URL,
            upload_new_products=True,  # Enable new product uploads
            sync_product_statuses=False,  # Statuses synced via batch update
            brand_name='Gel Me1'  # Brand name in the store
        )
    
    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape Cosme's products.json for product data"""
        results = []
        
        async with await self.get_client() as session:
            page = 1
            
            while True:
                url = f"https://shop-cosmedebeaute.com/products.json?limit=250&page={page}"
                
                try:
                    response = await session.get(url)
                    response.raise_for_status()
                    products_json = response.json()
                    
                    products = products_json.get('products', [])
                    if not products:
                        break
                    
                    # Filter for products with handle or SKU starting with 'gmp'
                    gmp_products = []
                    for p in products:
                        handle = p.get('handle', '').lower()
                        # Check handle
                        if handle.startswith('gmp'):
                            gmp_products.append(p)
                            continue
                        
                        # Check SKU in variants
                        variants = p.get('variants', [])
                        if variants:
                            sku = variants[0].get('sku', '').lower()
                            if sku.startswith('gmp'):
                                gmp_products.append(p)
                    
                    page_results = self.parse_search(gmp_products)
                    results.extend(page_results)
                    page += 1
                    print(f"[{self.table_name}] Scraped page {page-1} ({len(gmp_products)} GMP products)")
                    
                except Exception as e:
                    print(f"[{self.table_name}] Error scraping page {page}: {e}")
                    break
        
        print(f"[{self.table_name}] Total scraped: {len(results)} products")
        return results
    
    def parse_search(self, products: List[dict]) -> List[Dict[str, Any]]:
        """Parse the JSON response from Cosme"""
        results = []
        
        for product in products:
            try:
                # Get the first variant for availability and price
                variants = product.get('variants', [])
                if not variants:
                    continue
                
                main_variant = variants[0]
                
                # Get the first image
                images = product.get('images', [])
                photo = images[0]['src'] if images else ''
                
                # Ensure photo URL is absolute
                if photo and not photo.startswith('http'):
                    photo = 'https:' + photo
                
                result = {
                    'url': f"https://shop-cosmedebeaute.com/products/{product.get('handle')}",
                    'title': product.get('title', ''),
                    'price': f"¥{main_variant.get('price', '0')}",
                    'status': 'in stock' if main_variant.get('available', False) else 'sold out',
                    'photo': photo
                }
                
                results.append(result)
                
            except Exception as e:
                print(f"[{self.table_name}] Error parsing product: {e}")
                continue
        
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
                "Referer": "https://shop-cosmedebeaute.com/collections/nailsticker"
            }
            response = await session.get(url, headers=headers)
            sel = Selector(response.text)

            # Scrape product data
            product_data = {}
            
            # Name
            product_data['name'] = sel.css('h1.product-single__title::text').get("").strip()
            
            # Translate Japanese name to English
            if product_data['name']:
                product_data['name'] = clean_product_name(product_data['name'])
            
            # Fallback to JSON-LD if direct scraping fails
            if not product_data['name']:
                json_ld_script = sel.css('script[type="application/ld+json"]::text').get()
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

            # Price
            if 'MSRP' not in product_data or not product_data['MSRP']:
                price_text = sel.css('span.product__price span[aria-hidden="true"]::text').re_first(r'[\d,]+')
                product_data['MSRP'] = float(price_text.replace(',', '')) if price_text else 0.0
            
            # Description
            if 'description' not in product_data or not product_data['description']:
                desc_parts = sel.css('div.rte[itemprop="description"] ::text').getall()
                product_data['description'] = ' '.join([text.strip() for text in desc_parts if text.strip()])
            
            # SKU
            if 'sku' not in product_data or not product_data['sku']:
                product_data['sku'] = sel.css('span[data-sku-id]::text').get("").strip()
            
            # Availability
            if 'is_active' not in product_data:
                product_data['is_active'] = sel.css('button[data-add-to-cart-text="Sold out"]').get() is None

            # Scrape image URLs
            image_urls = sel.css('div.product__main-photos img::attr(src)').getall()
            if not image_urls:
                # Fallback for different image gallery structures
                image_urls = sel.css('a.product__thumb::attr(href)').getall()
            
            # Get token and upload images
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
    """Entry point for backward compatibility"""
    scraper = CosmeScraper()
    return await scraper.run()


if __name__ == "__main__":
    asyncio.run(scrape_search())

