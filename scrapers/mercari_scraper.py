import asyncio
import httpx
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import StaleElementReferenceException
import sqlite3

webhook_url = "https://discord.com/api/webhooks/1166549011717701682/dE9uTHnyJfitdCCkhnPphP_jfoTMgLjn_qI913SfC97sLbOc_y7JfCoVwV7AE7lMYJzZ"

async def main():

    

    # set the search phrases to use
    search_phrases = ["ohora gel nail", "semi cured gel nail", "semi cured gel", "ohora"]

    seen_urls = set()

    search_results = []
    for search_phrase in search_phrases:

        options = Options()
        options.add_argument('--headless')
        options.add_argument("--log-level=3")
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')

        # create a new instance of the web driver
        service = Service('C:/Users/Taylor/Desktop/SCG Community/Scrape/chromedriver-win64/chromedriver.exe')
        driver = webdriver.Chrome(service=service, options=options)

        # set the window size to 1920x1080 pixels
        driver.set_window_size(1920, 1080)

        # navigate to the website
        driver.get(f'https://www.mercari.com/search/?itemStatuses=1&keyword={search_phrase}&sortBy=2')
        no_new_results_count = 0
        last_search_results_length = 0
        single_search_results = []  # temporary list for this search phrase
        search_seen_urls = set()  # URLs seen in this search
        while True:
            time.sleep(.1)
            # scroll down the page by 500 pixels
            driver.execute_script("window.scrollBy(0, 500)")
            print("scrolling down...")

            # wait for the new search results to load
            time.sleep(.1)

            # locate the new search results elements and extract the data
            results = driver.find_elements(By.CSS_SELECTOR, 'div[data-itemstatus="on_sale"]')
            for result in results:
                try:
                    url = result.find_element(By.CSS_SELECTOR, 'a[itemprop="url"]').get_attribute('href').split('?')[0]
                    if url in search_seen_urls:
                        continue
                    search_seen_urls.add(url)
                    title = result.find_element(By.CSS_SELECTOR, 'div[data-testid="ItemName"]').text
                    price = result.find_element(By.CSS_SELECTOR, 'p[data-testid="ItemPrice"]').text
                    image = result.find_element(By.CSS_SELECTOR, 'img[data-nimg="fill"]').get_attribute('src')
                    single_search_results.append({'url': url, 'title': title, 'price': price, 'image': image})
                except StaleElementReferenceException:
                    continue

            # check if there are no more new search results
            print(f"Found {len(single_search_results)} listings this search")
            
            if len(single_search_results) == last_search_results_length:
                no_new_results_count += 1
                if no_new_results_count == 5:
                    break
            else:
                no_new_results_count = 0
                last_search_results_length = len(single_search_results)

        # append the results of this search to the main list only if they're not already in seen_urls
        for result in single_search_results:
            if result['url'] not in seen_urls:
                search_results.append(result)
                seen_urls.add(result['url'])

        # close the browser window and clean up resources
        driver.quit()

    # print the total number of search results found
    print(f"Total scrape search results found: {len(search_results)}")

    

    # create a new SQLite database and table to store the search results
    conn = sqlite3.connect('websocket-server/scrape_results.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS mercari_results
                 (url text PRIMARY KEY, title text, price text, image text)''')

    # iterate over the search results and insert them into the database
    for result in search_results:
        url = result['url']
        title = result['title']
        price = result['price']
        image = result['image']
        try:
            c.execute("INSERT INTO mercari_results VALUES (?, ?, ?, ?)", (url, title, price, image))
            print(f"Inserted new result to db: {title}")
        except sqlite3.IntegrityError:
            continue
        
        # send message to Discord
        await send_message_to_discord(
            webhook_url,
            title,
            url,
            price,
            image
        )
        
    # remove old listings from the database
    db_urls = set(row[0] for row in c.execute("SELECT url FROM mercari_results"))  # get set of all URLs in the database
    new_urls = set(result["url"] for result in search_results)  # get set of URLs in the new search results
    old_urls = db_urls - new_urls  # get set of URLs that are in the database but not in the new search results
    for url in old_urls:
        c.execute("DELETE FROM mercari_results WHERE url=?", (url,))
        print(f"Deleted listing with URL: {url}")

    # commit the changes and close the database connection
    conn.commit()
    conn.close()

async def send_message_to_discord(webhook_url, title, url, price, photo):
    # Generate the affiliate link
    target_link = url
    affiliate_query = "?mkevt=1&mkcid=1&mkrid=711-53200-19255-0&campid=5339016586&toolid=10001&customid=message"
    affiliate_link = target_link + affiliate_query

    # Create the message data
    data = {
        "embeds": [{
            "title": title,
            "url": url,
            "color": 0x00ff00,
            "fields": [{
                "name": "Price",
                "value": price,
                "inline": True
            }],
            "thumbnail": {
                "url": photo
            }
        }]
    }
    headers = {
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient() as client:
        try:
            # add logging statement to record the time each request is sent
            print(f"Sending request to Discord at {time.time()}")
            response = await client.post(webhook_url, json=data, headers=headers)
            response.raise_for_status()
            await asyncio.sleep(1.5)
        except httpx.HTTPStatusError as e:
            print(f"Failed to send message to Discord: {e}")

# call the main function
asyncio.run(main())