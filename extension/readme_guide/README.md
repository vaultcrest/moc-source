# MOC Source Extension — User Guide (outline)

Fill in each section below (replace the `[Sean: ...]` prompts with real text) and drop screenshots into this same folder, named to match the `![screenshot]` placeholders. When it's ready, I'll turn this into the guide website.

---

## 1. Introduction

- MOC Source is a free browser extension for builders. See Pick a Brick prices alongside BrickLink store prices — on the same page — and let the extension help sort out carts and find the cheapest way to buy a BrickLink Wanted list.
- Who it's for - Anyone who is trying to buy wanted lists at the cheapest price.
- Free and open source, built by AFOLs for AFOLs 


## 2. Installation

- Chrome Web Store link (once live) [MOC Source](https://chromewebstore.google.com/detail/moc-source/hoglacgnlglnbpeffbdndnhaokiojigh)
- Supported browsers (Chrome/Brave, Manifest V3, any Chromium based browser)

## 3. Getting Started

- Clicking the toolbar icon → Opens up a page with your saved carts and Wanted lists.
- First-time setup: Click the Gear icon to set basic Settings — setting your PAB region (18 locales) and store location filter
- More details on settings in the Settings section.

![screenshot: toolbar icon + popup](getting-started.png)
![screenshot: Settings](settings-basic.png)

## 4. Price Badges on BrickLink

Cover each page type where badges appear, with a screenshot each:

- **Wanted list page** — Price shown in your wanted list.
  ![screenshot: wanted list badge](badge-wanted-list.png)
- **Store listing** — Prices in Store Listings
  ![screenshot: store listing badge](badge-store-listing.png)
  *(cropped to the price column — full page shows the store name in the header, browsing that store's inventory directly)*
- **Store cart** — badge in price cell
  ![screenshot: store cart badge](badge-store-cart.png)
  *(cropped to the price column — full page shows the store name in the header, viewed while building a cart from a wanted list)*
- **Buy All page** — badge shown inline in the Buy All popup so you can compare PAB price before checking out
  ![screenshot: buy all badge](badge-buy-page.png)
- **Catalog item page** — Price on part listing that is color aware
  ![screenshot: catalog badge](part-page.png)

- Badges: green **PAB** (fast) Bestseller, amber **STD** (30+ day) Standard part, grey **PAB: N/A** not on PAB
- Clicking the PAB price will bring up the part in the Pick a Brick page.

## 5. Saving Lists & Carts to MOC Source

- At the top of Pick a Brick carts, Wanted lists, and Store pages are buttons to save to MOC Source to be used as reference.

- "Save to MOC Source" button location on wanted list pages and store cart pages
- **Save Wanted List** — Save your Wanted list. 
  ![screenshot: catalog badge](badge-wanted-list.png)
  Wanted lists can be reimported to a new list or add parts to an existing list. 
- **Save Pick a Brick Cart** — Save your PAB Cart.
  ![screenshot: catalog badge](pab-cart.png)
  Carts can be used to add parts back to Pick a Brick, or saved to a Wanted list. 
- **Save Store cart** — Save your BrickLink Store Cart.
  ![screenshot: store cart badge](badge-store-cart.png)
  Store carts can be updated if changed in MOC Source.

## 6. The Extension SPA — Lists View

- Three sections: Wanted Lists / BrickLink Carts / Pick a Brick Carts
- Clicking a name opens the detail view
- If you have no lists saved, they appear on the main page. From here you can create PAB Carts or Wanted lists to use for projects, or interact with your lists.

![screenshot: lists view](lists-view.png)

## 7. Detail Views

### Wanted List detail
- Tabs (All / Bestseller / Standard / Not on PAB)
- Toolbar actions: Remove Selected, → BrickLink / → PAB, Copy to / Move to, sort
- Inline Want/Have editing, Need column, Max $, PAB Price, Channel

![screenshot: wanted list detail](detail-wanted-list.png)

### BrickLink Cart detail
- Tabs, toolbar, ☑ BL cheaper / ☑ PAB ≤ store auto-select
- Flagging rows for "To Remove"

![screenshot: BL cart detail](detail-bl-cart.png)

### Pick a Brick Cart detail
- Tabs (All / Bestseller / Standard / BrickLink / To Remove)

![screenshot: Pick a Brick cart detail](detail-pab-cart.png)
- You can move these to other carts, Export to BrickLink or Pick a Brick.

## 8. Projects 

This is the flagship feature — give it the most space.

- What a "Project" is and why you'd use one (planning a MOC build across multiple sources)
  Projects are where Wanted lists, BrickLink carts, and Pick a Brick prices work together. 
- **Setup**: linking wanted lists, BL store carts, a Pick a Brick cart, a scratch list
  Set which carts, wanted lists, and other lists you want to use for a particular project. This can be used to create multiple Pick a Brick carts to separate Bestseller from Standard, and set multiple carts if you go over 200 elements in Bestseller or Standard, or over 999 in quantity. The auto allocate will figure out, with the given BrickLink carts and Pick a Brick prices, what is the cheapest mix to fulfill a project. It will also tell you what's missing and allow you to add that to its own list.
- **Pool**: the aggregated parts view, tabs, over-allocation highlighting
  These are all unallocated parts in a Project. You can expand it to show the parts already allocated.
- **Allocating parts**: moving pool → Pick a Brick/BL/scratch, checkbox multi-select
  Parts can be moved between sections by selecting them and using the buttons to choose where you want them to move, if you want to be opinionated.
- **⚡ Auto Allocate**: one-click cheapest-source allocation, domestic-PAB-only option
  We recommend using this to auto allocate parts. If you find a store is not giving you much of a discount compared to pick a brick, you can remove it from the Project configuration and it will return the parts to the Pool, Run Reallocate again to try and get a better mix.
- **Scratch space**: what it's for (zero-allocation parts only)
  These are all the unallocated parts, useful for saving those parts to a list to find stores that have them, or saving them for later.
- **Saving**: Pick a Brick cart diff+replace, scratch space save, pool save, BL cart writeback ("Save Cart ↓" / "Update cart from MOC Source")
  Each cart can be saved to its respective list. This will remove parts allocated elsewhere.
- **Grand total bar**: per-cart subtotals, estimated shipping, vs-PAB savings
  The grand total takes cart and shipping cost/estimated shipping cost and gives a total cost of buying the parts, and how much money was saved by using the BrickLink stores.


![screenshot: project setup](project-setup.png)
![screenshot: project pool + allocation](project-pool.png)
![screenshot: auto allocate](project-auto-allocate.png)
![screenshot: grand total / savings bar](project-savings.png)

## 9. Fill Wanted Qtys (BrickLink store shop page)

- What it does, condition preference (New/Used), when it skips a row
- This fills the quantity in a store for everything on the page in the desired amounts on a wanted list, that can then be added to your cart.
- In the Extension settings, you can tell it to use Used or New parts when possible for using the fill Wanted Quantities.
- Make sure to read item descriptions on things that may have notes about damage.
- This is useful for when you want to overload a cart with options to compare prices across stores you have chosen.
- You can add everything on your wanted list to a cart by cycling through the Fill and Add, to add as many items from the wanted list into the store cart.
- This can then be pruned and used in the Project page to determine which stores have the best price across the stores added to a particular project.

![screenshot: fill wanted qtys](fill-wanted-qtys.png)

## 10. Settings

- PAB region (18 locales), store location filter, buy page filter toggles
- Settings allows you to set your PAB price region to determine availability and prices.
  It allows you to set certain options on the BrickLink Buy page, such as ignoring lots over your max price, and setting your store location to buy from. Note that on some large wanted lists, the store location may load too early — we are working on a fix for that.
  It allows you to set the default length of items to show on Wanted lists. We have defaulted this to 10,000 to eliminate pages in 99% of cases.
  Store Shop Fill Button settings — tell it to use Used or New parts when possible for using the Fill Wanted Quantities.
  Project settings — tell the Project to ignore fees for shipping and costs if under the limit. Use this if you are trying to estimate on carts you will be adding parts in order to meet the thresholds, or adding to other orders in the cost estimate.

![screenshot: settings](settings-basic.png)

## 11. Tips / FAQ

- Try out overloading the carts, it can take a while to remove but gives the best results.
- Be aware that Part assemblies are not taken into account, so if someone has a Bicycle with wheels, and you ask for those parts, it won't pick that up.


## 12. Support

- Patreon / PayPal links
  https://www.patreon.com/cw/MocSource
  https://www.paypal.com/ncp/payment/SAACTUBPTPBSS
- MOC Source is free and open source, licensed under the [GNU AGPL-3.0](https://github.com/vaultcrest/moc-source/blob/devel/LICENSE). You're free to use, modify, and share it — derivative works must stay open source under the same license.

---

**Notes for me (not for the site):**
- [Sean: anything you want emphasized visually — e.g. before/after savings numbers, a "why this beats manual sourcing" pitch]
  Refer to the index page for the benefits — there are images and text there that we go over things.
- [Sean: tone — casual AFOL-community voice, or more polished/product-y?]
  Mix between casual AFOL community voice and polished/product-y. We want to lean casual, but just lean that way. 
