# oceanops-wigos-erddap

Some example notebooks working with the new [OceanOPS passports](https://www.ocean-ops.org/passports/#/intro)

These were compiled with a lot of trial and error, and are somewhat specialised by their nature to VOTO's data system (a fleet of SeaExplorer gliders with data shared in the OG1 format via ERDDAP) but will hopefully be helpful to anyone else sharing their passport data with OceanOPS via option B "expose".

Currently the demos are organised into 3 notebooks

- **01-passport-get-info** A generic notebook that uses a supplied WMO ID to query the OceanOPS API for all passport information for that WMO ID. This should work out the box for any WMO ID
- **02-passport-request-update** A more specialised notebook building on the first which pulls data from your ERDDAP and compares it to the OceanOPS passport data from notebook 1. If there are any differences, it will update passport data via the OceanOPS API and request passport ids where needed
- **03-passport-tables-for-erddap** An even more specialised notebook that will build the tables needed for Option B ingest so that OceanOPS can harvest mission and sensor metadata from your ERDDAP, without you needing to make active calls to their API. 
