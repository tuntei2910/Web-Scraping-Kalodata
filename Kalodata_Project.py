"""
Cleaned Playwright scraper for Kalodata.
- No hard-coded sensitive info (no emails/passwords/shop list in code).
- Reads shop names from ./shops.txt (one shop name per line).
- Writes outputs to ./output/
"""

import asyncio
import os
import pandas as pd
from datetime import datetime
from playwright.async_api import async_playwright
from p_logging import get_logger

# ---------- CONFIG ----------
SHOPS_FILE = "shops.txt"        # create this file with one shop name per line
MAX_PAGES = 50
URL = "https://kalodata.com"
FILTER_TAB_LABEL = "Filter"     # change if site label differs

# ---------- LOGGER SETUP ----------
date_str = datetime.now().strftime("%Y%m%d")
log_dir = os.path.join("output", f"shop_creators_{date_str}")
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, "shop_creators.log")

# start fresh log each run
if os.path.exists(log_path):
    os.remove(log_path)

logger = get_logger("shop_creators", log_path)

# ---------- UTILS ----------
async def safe_click(page, selector, retries=4, delay=1.5):
    """Click element with retries to handle flaky selectors."""
    for attempt in range(retries):
        try:
            await page.click(selector)
            return True
        except Exception as e:
            logger.warning(f"Retry click {attempt+1}/{retries} for '{selector}': {e}")
            await asyncio.sleep(delay)
    return False

def parse_product(value):
    """Convert values with 'k'/'m' suffix to numeric, return None if can't parse."""
    try:
        if isinstance(value, str) and value.endswith("k"):
            return float(value.replace("k", "")) * 1000
        elif isinstance(value, str) and value.endswith("m"):
            return float(value.replace("m", "")) * 1_000_000
        return float(value)
    except Exception:
        return None

async def apply_shop_filters(page):
    """Try to switch to the filter tab (non-sensitive)."""
    try:
        # locate a tab with FILTER_TAB_LABEL text. If not found, skip quietly.
        filter_tab = page.locator("div.ant-tabs-tab", has_text=FILTER_TAB_LABEL)
        await filter_tab.scroll_into_view_if_needed()
        await filter_tab.click()
        await asyncio.sleep(1)
    except Exception as e:
        logger.debug(f"Filter tab not found or not clickable: {e}")

# ---------- SCRAPER ----------
async def scrape_shop(context, page, shop_name):
    """
    Navigate to Shop tab, search for a shop, open detail page, go to Creator tab,
    and paginate through the creators table to collect rows.
    Returns pandas.DataFrame or None.
    """
    logger.info(f"Starting scrape for shop: {shop_name}")
    await safe_click(page, "#page_header_left >> text=Shop")
    await page.wait_for_timeout(1000)
    await apply_shop_filters(page)

    try:
        await page.fill("input[placeholder='Search shop name']", shop_name)
        await page.press("input[placeholder='Search shop name']", "Enter")
        await asyncio.sleep(2)
        logger.info(f"Searched for shop: {shop_name}")
    except Exception as e:
        logger.warning(f"Could not input shop name: {e}")

    try:
        await page.wait_for_selector(".ant-table-row.ant-table-row-level-0", timeout=10000)
    except Exception:
        logger.error("No shop list rows detected after search.")
        return None

    rows = await page.query_selector_all(".ant-table-row.ant-table-row-level-0")
    found = False
    results = []

    for row in rows:
        name_el = await row.query_selector("div.line-clamp-1:not(.text-base-999)")
        name = (await name_el.inner_text()).strip() if name_el else ""
        if shop_name.lower() == name.strip().lower():
            found = True
            logger.info(f"Found matching shop entry: {name}")

            # open detail page in new tab
            try:
                async with context.expect_page() as new_page_info:
                    await row.click()
                shop_page = await new_page_info.value
                await shop_page.wait_for_load_state()
                logger.info("Opened shop detail page.")
            except Exception as e:
                logger.error(f"Failed to open shop detail page: {e}")
                return None

            # navigate to Creator tab inside shop page
            try:
                sidebar_items = await shop_page.query_selector_all("div.flex.flex-col a")
                for item in sidebar_items:
                    txt = await item.inner_text()
                    if "Creator" in txt:
                        await item.click()
                        logger.info("Switched to Creator tab.")
                        break
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Failed to switch to Creator tab: {e}")
                return None

            # paginate through Creator table
            page_num = 1
            while page_num <= MAX_PAGES:
                if shop_page.is_closed():
                    logger.warning(f"Shop page closed while scraping at page {page_num}")
                    break
                try:
                    await shop_page.wait_for_selector("table", timeout=10000)
                    rows_table = await shop_page.query_selector_all("tbody > tr")
                    logger.info(f"Page {page_num} contains {len(rows_table)} rows.")

                    for row_table in rows_table:
                        try:
                            cols = await row_table.query_selector_all("td")
                            if len(cols) >= 6:
                                name_col = (await cols[0].inner_text()).strip()
                                creator_col = (await cols[1].inner_text()).strip().split("\n")[0]
                                account_type_col = (await cols[2].inner_text()).strip()
                                revenue_col = (await cols[3].inner_text()).strip()
                                product_col = (await cols[4].inner_text()).strip()
                                live_col = (await cols[5].inner_text()).strip()

                                results.append({
                                    "Name": name_col,
                                    "Creator": creator_col,
                                    "Account Type": account_type_col,
                                    "Revenue": revenue_col,
                                    "Product": product_col,
                                    "Live": live_col,
                                    "Shop Name": shop_name
                                })
                        except Exception as e:
                            logger.warning(f"Error parsing table row: {e}")

                    # click next if exists
                    next_btn = await shop_page.query_selector("li.ant-pagination-next:not(.ant-pagination-disabled)")
                    if next_btn:
                        await next_btn.click()
                        page_num += 1
                        await shop_page.wait_for_timeout(800)
                    else:
                        break
                except Exception as e:
                    logger.warning(f"Error on page {page_num}: {e}")
                    break
            break  # stop scanning other rows in search results

    if not found:
        logger.error(f"Shop not found in search results: {shop_name}")
        return None

    if results:
        df = pd.DataFrame(results)
        # Normalize revenue field: remove $ and parse suffixes
        df["Revenue"] = df["Revenue"].str.replace("$", "", regex=False)
        df["Revenue"] = df["Revenue"].apply(parse_product)
        # Optional filter example: keep only Affiliates or Seller operated and revenue >= 100
        df = df[(df["Account Type"].isin(["Affiliate", "Seller operated"])) & (df["Revenue"].fillna(0) >= 100)]
        return df
    return None

# ---------- SAVE DATA ----------
def save_data(stacked_rows, output_path):
    """Concatenate collected DataFrames and write to an Excel file."""
    try:
        if stacked_rows:
            combined_df = pd.concat(stacked_rows, ignore_index=True)
            with pd.ExcelWriter(output_path, engine="openpyxl", mode="w") as writer:
                combined_df.to_excel(writer, sheet_name="All Shops Data", index=False)
            logger.info(f"Saved combined data to {output_path}")
        else:
            # create an empty sheet to signal no results
            pd.DataFrame().to_excel(output_path, sheet_name="All Shops Data", index=False)
            logger.info(f"No rows collected. Created empty file at {output_path}")
    except Exception as e:
        logger.error(f"Failed to save final data: {e}")

# ---------- MAIN ----------
async def main():
    logger.info("Launching Playwright scraper...")

    # Read shop list from external file (no secrets in code)
    if not os.path.exists(SHOPS_FILE):
        logger.error(f"Missing {SHOPS_FILE}. Please create it with one shop name per line.")
        return

    with open(SHOPS_FILE, "r", encoding="utf-8") as f:
        shop_list = [line.strip() for line in f if line.strip()]

    if not shop_list:
        logger.error(f"{SHOPS_FILE} is empty. Add shops to scrape (one per line).")
        return

    stacked_rows = []
    output_folder = log_dir  # re-use log_dir under ./output
    os.makedirs(output_folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_folder, f"all_shops_data_{timestamp}.xlsx")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(no_viewport=True)
        page = await context.new_page()

        try:
            logger.info(f"Opening {URL} ...")
            await page.goto(URL, timeout=60000)

            # Give user time to log in manually if the site requires interactive auth
            logger.info("If login is required, please complete it within 30 seconds...")
            await asyncio.sleep(30)

            page_content = await page.content()
            if "Login" in page_content or "Sign In" in page_content:
                logger.error("Detected login page. Please login manually and re-run the script.")
                return

            # Optional: attempt to change region (best-effort, no sensitive labels)
            try:
                await safe_click(page, "div.h-\\[22px\\].hover\\:bg-\\[rgb\\(238\\,246\\,253\\)]")
                await asyncio.sleep(1)
            except Exception:
                logger.debug("Region switch element not available or clickable.")

            for shop in shop_list:
                try:
                    df_shop = await scrape_shop(context, page, shop)
                    if df_shop is not None and not df_shop.empty:
                        stacked_rows.append(df_shop)
                        # save incrementally to reduce data loss on interruption
                        save_data(stacked_rows, output_path)
                        logger.info(f"Scraped and appended data for: {shop}")
                    else:
                        logger.info(f"No matching creators or filtered-out rows for: {shop}")
                except Exception as e:
                    logger.error(f"Error scraping {shop}: {e}")

                # polite delay between shops
                await asyncio.sleep(2)
        finally:
            await browser.close()
            logger.info("Browser closed.")

if __name__ == "__main__":
    asyncio.run(main())
