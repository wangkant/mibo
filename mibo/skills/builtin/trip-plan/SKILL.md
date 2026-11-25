---
name: trip-plan
description: Plan a trip or a day out as a day-by-day itinerary with times, costs and sources. Use when they ask to plan a trip or route ("帮我做个三天的东京行程", "周末去杭州怎么安排", "plan a trip to…"). Choosing between two hotels or destinations is compare-options; a reminder at a set time is schedule_create alone.
license: Apache-2.0
metadata:
  mibo-title-zh: 行程规划
  mibo-description-zh: 依据官方页面核实开放时间、票价与交通，编排逐日行程并估算费用；不代为预订或付款，可另存为表格或文档。
  mibo-title-en: Trip planning
  mibo-description-en: Checks opening hours, prices and transport on official pages and builds a day-by-day itinerary with estimated costs; nothing is booked or paid, and the plan can be saved as a sheet or document.
---

# Planning a trip

1. Settle where, the dates or number of days, where they start from, who goes, the budget and what they like.
   Use what you remember of them and ask only what the plan turns on.
2. web_search and read_page for those dates: opening days and hours, ticket prices, how to get between places and
   how long it takes, events, the weather for the season, and entry or visa rules when crossing a border. Read the
   official page for each, and note where each fact came from.
3. Give a day-by-day plan: morning, afternoon, evening, with the travel time between stops. No more than three or
   four main stops a day, and one indoor option per day for bad weather.
4. Add a short cost estimate (transport, tickets, meals, a stay range) with its sources and the date seen, and
   what is worth booking ahead.
5. Never book, buy tickets, reserve or pay, and never ask for payment or ID details. Booking is theirs; pages
   with booking forms are only read.
6. Offer the plan as a workbook (one row per stop, with excel-workbook) or a document (word-document), and a
   reminder before departure (schedule_create), only as questions.

Opening hours and prices change: say that the figures are as seen on the dates given and to check the official
page before leaving.
