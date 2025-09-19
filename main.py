import asyncio
# from scrapers.ebay_scraper import scrape_search as scrape_ebay
from scrapers.poshmark_scraper import scrape_search as scrape_poshmark
from scrapers.ohora_disney_jp_scraper import scrape_search as scrape_ohora_disney_jp
from scrapers.ohora_jp_scraper import scrape_search as scrape_ohora_jp
from scrapers.ohora_scraper import scrape_search as scrape_ohora

async def main():
    # eBay search phrases
    # ebay_search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora", "ohora nail", "ohora gel", "ohora nail gel", "ohora nail gel semi", "ohora nail gel semi cured", "ohora nail gel semi cured gel", "ohora nail gel semi cured"]
    # for phrase in ebay_search_phrases:
    #     await scrape_ebay(phrase)

    # Poshmark search phrases
    poshmark_search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora", "ohora nail", "ohora gel", "ohora nail gel", "ohora nail gel semi", "ohora nail gel semi cured", "ohora nail gel semi cured gel", "ohora nail gel semi cured"]
    for phrase in poshmark_search_phrases:
        await scrape_poshmark(phrase)

    # Ohora Disney JP
    await scrape_ohora_disney_jp()

    # Ohora JP
    await scrape_ohora_jp()

    # Ohora
    await scrape_ohora()

if __name__ == "__main__":
    asyncio.run(main())
