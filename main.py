import asyncio
# from scrapers.ebay_scraper import scrape_search as scrape_ebay
# from scrapers.poshmark_scraper import scrape_search as scrape_poshmark
from scrapers.ohora_disney_jp_scraper import scrape_search as scrape_ohora_disney_jp
from scrapers.ohora_jp_scraper import scrape_search as scrape_ohora_jp
from scrapers.ohora_scraper import scrape_search as scrape_ohora
from scrapers.seven_nana_jp_scraper import scrape_search as scrape_seven_nana
from scrapers.dashingdiva_jp_scraper import scrape_search as scrape_dashingdiva
from scrapers.cosme_jp_scraper import scrape_search as scrape_cosme
from scrapers.esshimo_jp_scraper import scrape_search as scrape_esshimo
from common.batch_store_update import batch_update_store

async def main():
    # eBay search phrases
    # ebay_search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora", "ohora nail", "ohora gel", "ohora nail gel", "ohora nail gel semi", "ohora nail gel semi cured", "ohora nail gel semi cured gel", "ohora nail gel semi cured"]
    # for phrase in ebay_search_phrases:
    #     await scrape_ebay(phrase)

    # Poshmark search phrases
    # poshmark_search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora", "ohora nail", "ohora gel", "ohora nail gel", "ohora nail gel semi", "ohora nail gel semi cured", "ohora nail gel semi cured gel", "ohora nail gel semi cured"]
    # for phrase in poshmark_search_phrases:
    #     await scrape_poshmark(phrase)

    # Dictionary to collect all scraped products for batch store update
    all_scraped_products = {}

    # Ohora Disney JP
    results = await scrape_ohora_disney_jp()
    all_scraped_products['ohora_disney_jp'] = results or []

    # Ohora JP
    results = await scrape_ohora_jp()
    all_scraped_products['ohora_jp'] = results or []

    # Ohora US
    # EXCLUDED from batch store update (Discord notifications only)
    await scrape_ohora()
    # all_scraped_products['ohora_us'] = results or []
    
    # 7nana JP
    results = await scrape_seven_nana()
    all_scraped_products['seven_nana_jp'] = results or []
    
    # Dashing Diva JP
    results = await scrape_dashingdiva()
    all_scraped_products['dashingdiva_jp'] = results or []
    
    # Cosme JP
    results = await scrape_cosme()
    all_scraped_products['cosme_jp'] = results or []
    
    # Esshimo JP
    results = await scrape_esshimo()
    all_scraped_products['esshimo_jp'] = results or []

    # Perform batch store update with all collected data
    await batch_update_store(all_scraped_products)

if __name__ == "__main__":
    asyncio.run(main())

