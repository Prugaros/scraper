"""Batch store update - runs after all scrapers complete to update store with all brands at once."""
import asyncio
from typing import List, Dict, Any
from common.store_api import (
    get_admin_token, get_existing_products_status, 
    update_product_statuses, normalize_product_url
)


async def batch_update_store(all_scraped_products: Dict[str, List[Dict[str, Any]]]):
    """
    Update store with all scraped products from all brands.
    
    Args:
        all_scraped_products: Dict mapping scraper name to list of scraped products
                             Example: {'ohora_jp': [...], 'cosme': [...]}
    """
    print("\n" + "=" * 60)
    print("BATCH STORE UPDATE - Processing all brands")
    print("=" * 60)
    
    # Get authentication token
    token = await get_admin_token()
    if not token:
        print("[Batch Update] Failed to get admin token. Skipping store updates.")
        return
    
    # Get all existing products from store
    existing_products = await get_existing_products_status(token)
    
    # Create mapping of normalized handles to product data
    existing_by_handle = {
        normalize_product_url(url): data 
        for url, data in existing_products.items()
    }
    
    print(f"[Batch Update] Store has {len(existing_by_handle)} total products")
    
    # Collect all scraped product URLs (normalized handles)
    all_scraped_handles = set()
    products_to_update = []
    
    # Deduplicate scraped products by handle
    # If a product appears multiple times, use the latest info
    unique_scraped_products = {}
    
    # Process each scraper's results
    for scraper_name, products in all_scraped_products.items():
        print(f"[Batch Update] Processing {len(products)} products from {scraper_name}")
        
        for product in products:
            url = product.get('url')
            if not url:
                continue
            
            handle = normalize_product_url(url)
            # Store/Overwrite in dictionary to ensure uniqueness
            unique_scraped_products[handle] = product

    # Collect all scraped handles
    all_scraped_handles = set(unique_scraped_products.keys())

    # Calculate updates
    for handle, product in unique_scraped_products.items():
        # Check if product exists in store and status changed
        if handle in existing_by_handle:
            scraped_is_active = 'in stock' in product.get('status', '').lower()
            existing_is_active = bool(existing_by_handle[handle].get('is_active', False))  # Convert to bool for comparison
            
            if scraped_is_active != existing_is_active:
                products_to_update.append({
                    'product_url': existing_by_handle[handle]['product_url'],
                    'is_active': 1 if scraped_is_active else 0,  # Convert to integer for API
                    'name': product.get('title', handle)
                })
    
    # Update changed product statuses
    if products_to_update:
        print(f"\n[Batch Update] Found {len(products_to_update)} products with changed status")
        for product in products_to_update[:10]:  # Show first 10
            status = "In Stock" if product['is_active'] else "Out of Stock"
            print(f"  - {product.get('name', product['product_url'])}: {status}")
        if len(products_to_update) > 10:
            print(f"  ... and {len(products_to_update) - 10} more")
        
        await update_product_statuses(products_to_update, token)
        print(f"[Batch Update] ✓ Updated {len(products_to_update)} product statuses")
    
    # Find missing products (in store but not scraped by any scraper)
    missing_handles = set(existing_by_handle.keys()) - all_scraped_handles
    
    if missing_handles:
        print(f"\n[Batch Update] Found {len(missing_handles)} products missing from all scrapers")
        missing_products_to_update = []
        
        for handle in missing_handles:
            product_data = existing_by_handle[handle]
            # Only update if currently active
            if product_data.get('is_active', 0):  # Check if active (1 or True)
                missing_products_to_update.append({
                    'product_url': product_data['product_url'],
                    'is_active': 0,  # Integer 0 for inactive
                    'name': f"(Removed) {handle}"
                })
        
        if missing_products_to_update:
            print(f"[Batch Update] Marking {len(missing_products_to_update)} removed products as inactive")
            # Show first 10
            for product in missing_products_to_update[:10]:
                print(f"  - {product['name']}")
            if len(missing_products_to_update) > 10:
                print(f"  ... and {len(missing_products_to_update) - 10} more")
            
            await update_product_statuses(missing_products_to_update, token)
            print(f"[Batch Update] ✓ Marked {len(missing_products_to_update)} products as inactive")
    
    print("\n" + "=" * 60)
    print("BATCH STORE UPDATE - Complete")
    print("=" * 60 + "\n")
