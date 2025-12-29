import asyncio
import httpx
import random
from typing import List, Dict, Any, Optional, Callable
from abc import ABC, abstractmethod
from common.database import get_db_connection
from common.notifications import send_discord_message

class BaseScraper(ABC):
    def __init__(self, table_name: str, webhook_url: str, 
                 upload_new_products: bool = False, 
                 sync_product_statuses: bool = False,
                 brand_name: Optional[str] = None, price_converter: Optional[Callable] = None):
        self.table_name = table_name
        self.webhook_url = webhook_url
        self.upload_new_products = upload_new_products
        self.sync_product_statuses = sync_product_statuses
        self.brand_name = brand_name
        self.price_converter = price_converter
        self.base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def get_client(self):
        return httpx.AsyncClient(
            headers=self.base_headers,
            http2=True,
            timeout=30.0
        )

    @abstractmethod
    async def scrape(self) -> List[Dict[str, Any]]:
        """
        Implementation specific scraping logic.
        Must return a list of dictionaries.
        Each dictionary must at least have 'url', 'title', 'price', 'status', 'photo'.
        """
        pass

    async def process_results(self, results: List[Dict[str, Any]]):
        if not results:
            print(f"[{self.table_name}] No results to process.")
            return

        print(f"[{self.table_name}] Processing {len(results)} results...")
        conn = await asyncio.to_thread(get_db_connection)
        
        try:
            # Get current URLs from scrape
            current_urls = {result['url'] for result in results}
            
            # Get all URLs from database
            db_urls = await asyncio.to_thread(
                lambda: {row['url'] for row in conn.execute(
                    f'SELECT url FROM {self.table_name}'
                ).fetchall()}
            )
            
            # Find missing URLs (in DB but not in current scrape)
            missing_urls = db_urls - current_urls
            
            # Process current results
            for result in results:
                await self.process_single_result(conn, result)
            
            # Mark missing products as sold out
            if missing_urls:
                await self.handle_missing_products(conn, missing_urls)
            
            await asyncio.to_thread(conn.commit)
        except Exception as e:
            print(f"[{self.table_name}] Error processing results: {e}")
        finally:
            await asyncio.to_thread(conn.close)

    async def process_single_result(self, conn, result: Dict[str, Any]):
        try:
            # Check existing
            row = await asyncio.to_thread(
                lambda: conn.execute(f'SELECT * FROM {self.table_name} WHERE url = ?', (result['url'],)).fetchone()
            )
            
            if row is None:
                await self.handle_new_listing(conn, result)
            else:
                await self.handle_existing_listing(conn, row, result)
        except Exception as e:
            print(f"[{self.table_name}] Error processing item {result.get('url')}: {e}")

    async def handle_missing_products(self, conn, missing_urls: set):
        """Handle products that are no longer found on the website."""
        print(f"[{self.table_name}] Found {len(missing_urls)} missing products - marking as sold out")
        
        for url in missing_urls:
            try:
                # Get current product data
                row = await asyncio.to_thread(
                    lambda: conn.execute(
                        f'SELECT * FROM {self.table_name} WHERE url = ?', (url,)
                    ).fetchone()
                )
                
                if not row:
                    continue
                
                # Check if already marked as sold out
                current_status = str(row['status']).lower()
                if 'sold out' in current_status or 'inactive' in current_status:
                    continue  # Already marked, skip
                
                # Update to sold out
                await asyncio.to_thread(
                    conn.execute,
                    f"UPDATE {self.table_name} SET status = 'sold out' WHERE url = ?",
                    (url,)
                )
                
                # Send Discord notification
                changes = ["Product no longer available on website - marked as sold out"]
                result = dict(row)
                result['status'] = 'sold out'
                embed = self.create_embed(result, "Product Removed", changes)
                await send_discord_message(self.webhook_url, embed)
                
                print(f"[{self.table_name}] Marked as sold out: {row['title']}")
                
            except Exception as e:
                print(f"[{self.table_name}] Error handling missing product {url}: {e}")

    async def handle_new_listing(self, conn, result: Dict[str, Any]):
        # Construct dynamic insert
        columns = list(result.keys())
        placeholders = ', '.join(['?'] * len(columns))
        col_str = ', '.join(columns)
        values = [result[k] for k in columns]
        
        query = f"INSERT INTO {self.table_name} ({col_str}) VALUES ({placeholders})"
        await asyncio.to_thread(conn.execute, query, values)

        # Send notification
        embed = self.create_embed(result, "New Listing")
        await send_discord_message(self.webhook_url, embed)

    async def handle_existing_listing(self, conn, current_row, new_result: Dict[str, Any]):
        changes = []
        
        # Check standard fields
        if str(current_row['price']) != str(new_result['price']):
            changes.append(f"Price changed from {current_row['price']} to {new_result['price']}")
        
        if str(current_row['status']) != str(new_result['status']):
            changes.append(f"Status changed from {current_row['status']} to {new_result['status']}")

        # Check stock if present
        if 'stock' in new_result and 'stock' in current_row.keys():
            old_stock = current_row['stock']
            new_stock = new_result['stock']
            if old_stock is not None and new_stock < old_stock:
                alert_thresholds = [50, 40, 30, 20, 10, 5]
                for threshold in alert_thresholds:
                    if old_stock > threshold and new_stock <= threshold:
                        changes.append(f"STOCK ALERT! Current: {new_stock}")
                        break

        if changes:
            # Update DB
            # We update all tracked fields to be safe/current
            columns = list(new_result.keys())
            set_clause = ', '.join([f"{col} = ?" for col in columns])
            values = [new_result[col] for col in columns]
            values.append(new_result['url']) # for WHERE clause
            
            query = f"UPDATE {self.table_name} SET {set_clause} WHERE url = ?"
            await asyncio.to_thread(conn.execute, query, values)

            # Send Notification
            embed = self.create_embed(new_result, "Listing Updated", changes)
            await send_discord_message(self.webhook_url, embed)

    def create_embed(self, result: Dict[str, Any], title_prefix: str, changes: List[str] = None):
        description = ""
        if changes:
            description = "**Changes:**\n" + "\n".join(changes)

        fields = [
            {"name": "Price", "value": str(result.get('price', 'N/A')), "inline": True},
            {"name": "Status", "value": str(result.get('status', 'N/A')), "inline": True}
        ]
        
        if 'stock' in result:
             fields.append({"name": "Stock", "value": str(result['stock']), "inline": True})

        return {
            "title": f"{title_prefix}: {result.get('title', 'Unknown')}",
            "url": result.get('url'),
            "color": 0x00ff00,
            "description": description,
            "fields": fields,
            "thumbnail": {"url": result.get('photo', '')}
        }

    async def scrape_product_details(self, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Optional method for scrapers that support store updates.
        Scrape detailed product information for a single product.
        Returns a dictionary with product details for store upload.
        """
        return None

    async def process_results_with_store_updates(self, results: List[Dict[str, Any]]):
        """Process results with store API updates enabled."""
        if not results:
            print(f"[{self.table_name}] No results to process.")
            return

        print(f"[{self.table_name}] Processing {len(results)} results with store updates...")
        
        # Import store API functions
        from common.store_api import (
            get_admin_token, get_brand_id, get_existing_products_status,
            update_product_statuses, upsert_product, normalize_product_url
        )
        
        # Get authentication token
        token = await get_admin_token()
        if not token:
            print(f"[{self.table_name}] Failed to get admin token. Falling back to standard processing.")
            await self.process_results(results)
            return
        
        # Get brand ID if needed
        brand_id = None
        if self.brand_name:
            brand_id = await get_brand_id(self.brand_name, token)
            if not brand_id:
                print(f"[{self.table_name}] Failed to get brand ID. Falling back to standard processing.")
                await self.process_results(results)
                return
        
        # Get existing products from store
        # Get existing products from store
        # Optimization: If only uploading new products, we still need existing products to check existence
        # But we don't need to filter by brand if we are just checking for existence (normalized handle check)
        # However, to avoid false positives on "new" products, we should check against all store products
        
        existing_products = await get_existing_products_status(token)
        
        # Create a mapping of normalized handles
        existing_by_handle = {
            normalize_product_url(url): data 
            for url, data in existing_products.items()
        }
        
        print(f"[{self.table_name}] Mapped {len(existing_by_handle)} existing products by handle.")
        
        # ---------------------------------------------------------
        # 1. STATUS SYNCING (If enabled)
        # ---------------------------------------------------------
        if self.sync_product_statuses:
            products_to_update = []
            for scraped_product in results:
                url = scraped_product['url']
                handle = normalize_product_url(url)
                
                if handle in existing_by_handle:
                    scraped_is_active = 'in stock' in scraped_product.get('status', '').lower()
                    existing_is_active = bool(existing_by_handle[handle].get('is_active', 0)) # Fixed: use bool conversion
                    
                    if scraped_is_active != existing_is_active:
                        products_to_update.append({
                            'product_url': existing_by_handle[handle]['product_url'],
                            'is_active': 1 if scraped_is_active else 0, # Fixed: use integer
                            'name': scraped_product.get('title', '')
                        })
            
            if products_to_update:
                print(f"[{self.table_name}] Found {len(products_to_update)} products with changed status.")
                await update_product_statuses(products_to_update, token)

            # Missing product detection (Store)
            # Only safe if we can identify brand or if we accept risk (disabled for most scrapers now)
            if existing_by_handle: 
                scraped_handles = {normalize_product_url(p['url']) for p in results}
                missing_handles = set(existing_by_handle.keys()) - scraped_handles
                
                # ... skipping implementation for now as we generally disable this ...
                # We defer missing product status updates to batch_store_update.py
                pass

        # ---------------------------------------------------------
        # 2. NEW PRODUCT UPLOAD (If enabled)
        # ---------------------------------------------------------
        if self.upload_new_products:
            new_product_urls = [
                p['url'] for p in results 
                if normalize_product_url(p['url']) not in existing_by_handle
            ]
            print(f"[{self.table_name}] Found {len(new_product_urls)} new products to add to store.")
            
            if new_product_urls and getattr(self, 'scrape_product_details', None):
                async with await self.get_client() as session:
                    for i, url in enumerate(new_product_urls):
                        print(f"[{self.table_name}] Scraping product {i+1}/{len(new_product_urls)}: {url}")
                        try:
                            kwargs = {'session': session}
                            if brand_id: kwargs['brand_id'] = brand_id
                            if self.price_converter: kwargs['price_converter'] = self.price_converter
                            
                            product_details = await self.scrape_product_details(url, **kwargs)
                            if product_details:
                                await upsert_product(product_details, token)
                                await asyncio.sleep(2)
                        except Exception as e:
                            print(f"[{self.table_name}] Failed to upload {url}: {e}")
        
        # Also process with standard database/Discord notifications
        await self.process_results(results)

    async def run(self):
        print(f"Starting scraper for {self.table_name}...")
        results = await self.scrape()
        
        if self.upload_new_products or self.sync_product_statuses:
            await self.process_results_with_store_updates(results)
        else:
            await self.process_results(results)
        
        return results
