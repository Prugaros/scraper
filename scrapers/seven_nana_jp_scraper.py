import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from typing import List, Dict, Any, Optional
from common.config import SEVEN_NANA_WEBHOOK_URL
from scrapers.base import BaseScraper
from parsel import Selector
from common.store_api import get_jpy_to_usd_rate, calculate_usd_price, upload_images
from common.translation import clean_product_name


class SevenNanaScraper(BaseScraper):
    """Scraper for 7nana Japan products using JSON endpoint"""
    
    def __init__(self):
        super().__init__(
            table_name="seven_nana_results",
            webhook_url=SEVEN_NANA_WEBHOOK_URL,
            upload_new_products=True,
            sync_product_statuses=False,  # Statuses synced via batch update
            brand_name='7nana'
        )
    
    async def scrape(self) -> List[Dict[str, Any]]:
        """Scrape 7nana's products.json for product data"""
        results = []
        
        async with await self.get_client() as session:
            # 7nana has all products in a single JSON endpoint
            url = "https://7na.jp/products.json?limit=250"
            
            try:
                response = await session.get(url)
                response.raise_for_status()
                products_json = response.json()
                
                if not products_json.get('products'):
                    print(f"[{self.table_name}] No products found")
                    return results
                
                results = self.parse_search(products_json)
                print(f"[{self.table_name}] Scraped {len(results)} products")
                
            except Exception as e:
                print(f"[{self.table_name}] Error fetching products: {e}")
        
        return results
    
    def parse_search(self, products_json: dict) -> List[Dict[str, Any]]:
        """Parse the JSON response from 7nana"""
        results = []
        
        for product in products_json.get('products', []):
            try:
                # Check if ANY variant is available
                variants = product.get('variants', [])
                if not variants:
                    continue
                
                is_available = any(v.get('available', False) for v in variants)
                main_variant = variants[0]
                
                # Get the first image
                images = product.get('images', [])
                photo = images[0]['src'] if images else ''
                
                # Ensure photo URL is absolute
                if photo and not photo.startswith('http'):
                    photo = 'https:' + photo
                
                result = {
                    'url': f"https://7na.jp/products/{product.get('handle')}",
                    'title': product.get('title', ''),
                    'price': f"¥{main_variant.get('price', '0')}",
                    'status': 'in stock' if is_available else 'sold out',
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
            return None
        
        # Get exchange rate
        jpy_to_usd_rate = get_jpy_to_usd_rate()
        
        try:
            response = await session.get(url)
            sel = Selector(response.text)

            # Extract data from JSON-LD
            json_ld_scripts = sel.css('script[type="application/ld+json"]::text').getall()
            
            product_data = {}
            
            for script in json_ld_scripts:
                try:
                    import json
                    data = json.loads(script)
                    # Handle if it's a list of schemas
                    if isinstance(data, list):
                        for item in data:
                             if item.get('@type') == 'Product':
                                 data = item
                                 break
                    
                    if data.get('@type') == 'Product':
                        product_data['name'] = data.get('name')
                        product_data['description'] = data.get('description')
                        product_data['sku'] = data.get('sku')
                        if 'offers' in data and data['offers']:
                            # Handle list of offers or single offer
                            offer = data['offers'][0] if isinstance(data['offers'], list) else data['offers']
                            product_data['MSRP'] = float(offer.get('price', 0))
                            availability = offer.get('availability', '')
                            product_data['is_active'] = "InStock" in availability
                        break # Found Product schema, stop looking
                except json.JSONDecodeError:
                    continue

            # Fallback scraping
            if not product_data.get('name'):
                product_data['name'] = sel.css('h1.product-single__title::text').get("").strip()
            
            # Translate Japanese name
            if product_data.get('name'):
                product_data['name'] = clean_product_name(product_data['name'])
                
            if not product_data.get('MSRP'):
                price_text = sel.css('.product__price::text').re_first(r'[\d,]+')
                product_data['MSRP'] = float(price_text.replace(',', '')) if price_text else 0.0

            # Scrape image URLs
            # 7nana specific selectors (usually standard Shopify)
            image_urls = sel.css('.product__media img::attr(src)').getall()
            if not image_urls:
                 image_urls = sel.css('.product-single__photo img::attr(src)').getall()
            if not image_urls: # Generic fallback
                 image_urls = sel.css('img[src*="/products/"]::attr(src)').getall()

            # Clean up URLs
            image_urls = [f"https:{url}" if url.startswith('//') else url for url in image_urls]
            image_urls = [url for url in image_urls if url.startswith('http')]

            # Upload images
            from common.store_api import get_admin_token
            token = await get_admin_token()
            if token:
                product_data['images'] = await upload_images(image_urls[:10], session, token)
            else:
                product_data['images'] = []
            
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
    scraper = SevenNanaScraper()
    return await scraper.run()

