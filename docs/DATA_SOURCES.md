# Data sources and compliance

## Summary

The pipeline uses:

1. **Open Food Facts** - open database, CC-BY-SA licensed, API documented.
   Used as a fallback for missing allergens / dietary tags / nutrition.
2. **Woolworths.com.au and Coles.com.au public pages** - publicly accessible
   web pages; data is collected from the same endpoints the websites use.
   This is NOT an official API and NOT an open-data licence.

For a coursework project (FIT5120 inclusive-design brief), be honest in the
proposal: "Open Food Facts open database + public product pages from the two
retailers (unofficial collection, fetched_at recorded, reference only)".
Do not describe retailer pages as "open data".

## What "public" means here

- Woolworths search/category endpoints answer anonymous HTTP requests; the
  website itself is publicly browsable without login.
- Coles product pages are server-rendered and the detail JSON is embedded in
  the HTML; the site is publicly browsable without login.
- Neither retailer publishes a developer API or data licence for third-party
  use. robots.txt disallows `/search/` (Coles) and `/shop/search` (Woolworths);
  both use anti-bot protection (Incapsula / Akamai).

## Product disclaimer

Retailer allergen and dietary filters are explicitly marked "a guide only" by
Woolworths; consumers must check the physical label. The app must surface a
disclaimer such as:

> Information is sourced from retailer public pages and Open Food Facts,
> collected at a specific date; always check the product label before
> consuming.

## Reference projects

- tjhowse/aus_grocery_price_database - GPL-3.0. Architecture and API
  techniques informed this project; no code copied (this project is MIT).
- tjhowse/python-woolworths - no licence; endpoint inventory only.
- abhinav-pandey29/coles-scraper - no licence; cookie-interception pattern.
- nguyentansinh123/Scraping-Coles-Woolworths-IGA - no licence; browser
  fallback pattern.
