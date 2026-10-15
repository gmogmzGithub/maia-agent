---
status: accepted
---

# Search synchronized external inventory

Discovery and ranking use a synchronized local copy of authorized EasyBroker
inventory rather than making live source queries for every customer search.
This supports combined ranking while separating conversational response from
connector availability. Recheck an external listing before offering bookable
options; the local projection does not establish current external availability.
During source outages, show verified own inventory and explain that external
options could not be checked. Keep external records internally but exclude
unverified external listings from new recommendations during an outage; explain
pending availability for previously shown external listings. The provisional
refresh target is every 30 minutes, subject to provider limits and inventory
size. Outage detection and recovery thresholds remain implementation work.
