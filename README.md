# Kalodata Project Scraper

This project is a **Playwright-based asynchronous scraper** for extracting shop and creator data from [Kalodata](https://kalodata.com).  
It has been cleaned of any sensitive or hard-coded information (no emails, passwords, or shop lists inside the script).  
The scraper reads shop names from an external file and outputs results into Excel files under the `./output/` directory.

---

## Features
- Uses **Playwright (async)** for stable browser automation.
- Reads shop names from `shops.txt` (one per line).
- Navigates to shop details, switches to the **Creator** tab, and extracts:
  - Shop Name
  - Creator Name
  - Account Type
  - Revenue (parsed into numeric values, supports `k`/`m` suffixes)
  - Product
  - Live sessions
- Supports pagination (up to 50 pages by default).
- Logs all scraping activities into timestamped log files under `./output/`.
- Saves combined results into an **Excel file**.

---

## Project Structure
├── Kalodata_Project.py # main scraper script

├── shops.txt # input file with one shop name per line (create manually)

├── output/ # logs and exported Excel files will be stored here

└── requirements.txt # dependencies for running the script

---

## Requirements
- Python **3.9+**
- Dependencies listed in `requirements.txt`:
  - `playwright`
  - `pandas`
  - `openpyxl`
  - `p_logging` (custom/local logging helper)

Install dependencies:
pip install -r requirements.txt

**Make sure Playwright browsers are installed**
playwright install
