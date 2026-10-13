# Understanding EV Charging Costs

## Power, energy, and consumption

A kilowatt (kW) measures power, or the rate of energy transfer. A kilowatt-hour (kWh) measures energy stored or delivered. A 50 kW rate maintained for one hour would transfer 50 kWh in an ideal calculation, but actual charging power changes over time. Vehicle consumption is commonly expressed as kWh per 100 km or kWh per mile. Estimated driving energy is distance multiplied by consumption in matching units.

Efficiency matters when translating battery energy into electricity purchased. Energy measured at the wall can exceed energy added to the battery because power electronics, cables, battery conditioning, and other systems consume energy.

## Home and public charging

Home cost can include the electricity contract, time-of-use rate, grid charges, taxes, and installation or equipment costs. Scheduled charging may use lower-priced hours where the local tariff supports them. Rates and bill structures are regional, so there is no universal default electricity price or currency.

Public charging can use per-kWh, per-minute, session, subscription, roaming, idle, or parking fees. Prices vary by operator, location, power, and time. DC fast charging often costs more because it provides faster service using expensive equipment and grid capacity. Always check the current operator tariff.

## Charging losses and calculations

To estimate a session, first choose the energy to add to the battery. Divide it by charging efficiency to estimate grid energy, then multiply grid energy by the price per kWh. For example, with symbols rather than assumed prices: grid energy equals battery energy divided by efficiency; estimated energy cost equals grid energy multiplied by the local unit price. Add fixed, parking, subscription, or time fees separately.

For a trip, estimate energy from distance and realistic consumption for the route and season. Calculate each stop separately because home, destination, and fast-charging rates may differ. State the assumed efficiency, tariff, and currency so the result is auditable rather than presenting it as a bill.

## Billing and local assumptions

Electricity prices can vary with time, location, demand, taxes, and contract. Charging-station operators may also recover equipment, network, maintenance, property, and payment costs. A time-based fee can penalize a car whose charging curve has tapered, while a per-kWh fee more directly reflects delivered energy. Current local terms are required for a real purchasing decision.

EV Advisor's deterministic charging-cost tool performs arithmetic only. It does not fetch live tariffs or select a currency. The caller supplies energy, price, and efficiency and remains responsible for local fees and assumptions.

## Sources

- Power, energy, and consumption: https://afdc.energy.gov/fuels/electricity-stations
- Home and public charging: https://afdc.energy.gov/fuels/electricity-infrastructure-maintenance-and-operation
- Home and public charging: https://afdc.energy.gov/fuels/electricity-charging-public
- Charging losses and calculations: https://atb.nrel.gov/transportation/2022/Electricity
- Billing and local assumptions: https://afdc.energy.gov/fuels/electricity-infrastructure-maintenance-and-operation

Verification date: 2026-10-13
