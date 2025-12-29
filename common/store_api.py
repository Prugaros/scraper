import asyncio
import httpx
import requests
import math
import os
import random
import time
import tempfile
import shutil
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from .config import BACKEND_URL, ADMIN_USERNAME, ADMIN_PASSWORD


def normalize_product_url(url: str) -> str:
    """
    Normalize product URL to just the product handle for comparison.
    Examples:
      https://ohora.co.jp/products/set-134-j -> set-134-j
      https://ohora.co.jp/collections/all-products/products/ohol-02 -> ohol-02
    """
    # Extract the product handle (last part of the URL path)
    path = urlparse(url).path
    # Remove query parameters and fragments, get last segment
    handle = path.rstrip('/').split('/')[-1]
    return handle


async def get_admin_token() -> Optional[str]:
    """Authenticate with username/password and get JWT token."""
    api_url = f"{BACKEND_URL}/api/auth/login"
    credentials = {
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=credentials)
            response.raise_for_status()
            data = response.json()
            if "accessToken" in data:
                print(f"[Store API] Successfully authenticated and obtained token")
                return data['accessToken']
            else:
                print("[Store API] Error: accessToken not found in response.")
                return None
    except Exception as e:
        print(f"[Store API] Authentication error: {e}")
        return None


def get_jpy_to_usd_rate() -> Optional[float]:
    """Fetches the JPY to USD exchange rate from the European Central Bank."""
    try:
        response = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml")
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        ns = {'ecb': 'http://www.ecb.int/vocabulary/2002-08-01/eurofxref'}
        
        usd_rate_elem = root.find(".//ecb:Cube[@currency='USD']", ns)
        jpy_rate_elem = root.find(".//ecb:Cube[@currency='JPY']", ns)
        
        if usd_rate_elem is not None and jpy_rate_elem is not None:
            usd_rate = float(usd_rate_elem.get('rate'))
            jpy_rate = float(jpy_rate_elem.get('rate'))
            # Convert from EUR-based rates to a direct JPY to USD rate
            jpy_to_usd = usd_rate / jpy_rate
            print(f"[Store API] Successfully fetched JPY to USD exchange rate: {jpy_to_usd}")
            return jpy_to_usd
        else:
            print("[Store API] Could not find USD or JPY rates in ECB data.")
            return None
    except Exception as e:
        print(f"[Store API] Failed to fetch or parse exchange rate data: {e}")
        return None


def calculate_usd_price(jpy_msrp: float, jpy_to_usd_rate: Optional[float]) -> int:
    """Calculates the USD price based on JPY MSRP and a conversion rate."""
    
    # Fixed price points
    if jpy_msrp == 2300:
        return 19
    if jpy_msrp == 2200:
        return 19
    if jpy_msrp == 2068:
        return 18
    if jpy_msrp == 1826:
        return 16

    if jpy_to_usd_rate is None:
        print("[Store API] Warning: Cannot calculate dynamic price, exchange rate not available.")
        return 0

    # Convert, round up, and add $3
    usd_price = jpy_msrp * jpy_to_usd_rate
    rounded_up_price = math.ceil(usd_price)
    final_price = rounded_up_price + 3
    
    return int(final_price)


async def get_brand_id(brand_name: str, token: str) -> Optional[int]:
    """Fetch brand ID from store API by name."""
    try:
        headers = {"x-access-token": token}
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/api/brands", headers=headers)
            response.raise_for_status()
            brands = response.json()
            for brand in brands:
                if brand['name'] == brand_name:
                    print(f"[Store API] Found brand '{brand_name}' with ID: {brand['id']}")
                    return brand['id']
            print(f"[Store API] Brand '{brand_name}' not found in database.")
            return None
    except Exception as e:
        print(f"[Store API] Failed to fetch brand ID: {e}")
        return None


async def get_existing_products_status(token: str) -> Dict[str, Dict[str, Any]]:
    """Fetch all products and their statuses from store."""
    api_url = f"{BACKEND_URL}/api/scrape/products-status"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url)
            response.raise_for_status()
            products = response.json()
            existing_products = {p['product_url']: p for p in products}
            print(f"[Store API] Found {len(existing_products)} existing products in the store.")
            return existing_products
    except Exception as e:
        print(f"[Store API] Failed to get existing products: {e}")
        return {}


async def update_product_statuses(products_to_update: List[Dict[str, Any]], token: str) -> bool:
    """Batch update product statuses."""
    try:
        headers = {
            "Content-Type": "application/json",
            "x-access-token": token
        }
        api_url = f"{BACKEND_URL}/api/scrape/update-statuses"
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json={"productsToUpdate": products_to_update}, headers=headers)
            response.raise_for_status()
            print(f"[Store API] Successfully updated {len(products_to_update)} product statuses.")
            return True
    except Exception as e:
        print(f"[Store API] Failed to update product statuses: {e}")
        return False


async def upload_images(image_urls: List[str], session: httpx.AsyncClient, token: str) -> List[str]:
    """Download and upload images to store."""
    uploaded_urls = []
    temp_dir = tempfile.mkdtemp()
    
    try:
        downloaded_image_paths = []
        for img_url in image_urls:
            # Check for '.gif' in the URL path, ignoring query parameters
            if '.gif' in img_url.split('?')[0]:
                print(f"[Store API] Skipping .gif file: {img_url}")
                continue
            if not img_url.startswith('http'):
                img_url = 'https:' + img_url
            try:
                # Use the async session to download the image
                response = await session.get(img_url)
                response.raise_for_status()
                
                # Generate a short, unique filename
                url_without_query = img_url.split('?')[0]
                _, file_extension = os.path.splitext(url_without_query)
                if not file_extension:
                    file_extension = '.jpg'
                new_filename = f"{int(time.time() * 1000)}-{random.randint(1000, 9999)}{file_extension}"
                temp_path = os.path.join(temp_dir, new_filename)
                
                with open(temp_path, 'wb') as f:
                    f.write(response.content)
                downloaded_image_paths.append(temp_path)
            except Exception as e:
                print(f"[Store API] Failed to download image {img_url}: {e}")

        if downloaded_image_paths:
            files_to_upload = []
            opened_files = []
            try:
                for path in downloaded_image_paths:
                    filename = os.path.basename(path)
                    f = open(path, 'rb')
                    opened_files.append(f)
                    files_to_upload.append(('images', (filename, f, 'image/jpeg')))

                def do_upload():
                    upload_url = f"{BACKEND_URL}/api/upload/image"
                    headers = {"x-access-token": token}
                    return requests.post(upload_url, files=files_to_upload, headers=headers)

                # Run the synchronous requests call in a separate thread
                response = await asyncio.to_thread(do_upload)
                response.raise_for_status()
                uploaded_urls = response.json().get('imageUrls', [])
                print(f"[Store API] Successfully uploaded {len(uploaded_urls)} images.")
            except Exception as e:
                print(f"[Store API] Failed to upload images: {e}")
            finally:
                # Ensure all opened files are closed
                for f in opened_files:
                    f.close()
    finally:
        # Manually clean up the temporary directory
        shutil.rmtree(temp_dir)
    
    return uploaded_urls


async def upsert_product(product_data: Dict[str, Any], token: str) -> bool:
    """Create or update a product in the store."""
    try:
        headers = {
            "Content-Type": "application/json",
            "x-access-token": token
        }
        api_url = f"{BACKEND_URL}/api/scrape/upsert"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, json=product_data, headers=headers)
            response.raise_for_status()
            print(f"[Store API] Successfully upserted product: {product_data.get('name')}")
            return True
    except Exception as e:
        print(f"[Store API] Failed to upsert product {product_data.get('product_url')}: {e}")
        return False
