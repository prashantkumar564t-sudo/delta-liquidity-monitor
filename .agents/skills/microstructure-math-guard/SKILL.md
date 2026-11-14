---
name: microstructure-math-guard
description: Enforces Decimal precision, tick-size alignment ($0.50 for BTCUSD), and mathematical invariants across order book metrics and execution simulations.
---

# Microstructure Math Guard

This skill defines mandatory mathematical invariants, precision rules, and tick alignment for the Delta Exchange BTC-USD order book engine.

## 1. Decimal Precision Rules
- Every numerical value from raw API payloads (`price`, `size`, `contract_value`, `taker_fee`) must be converted to `decimal.Decimal` before any calculations.
- Strings must be passed directly into `Decimal(str(val))`—never cast to `float` first to avoid IEEE-754 precision poisoning.
- Division operations must be explicit about rounding modes where contract truncation occurs (e.g. `ROUND_FLOOR` for contract lots).

## 2. Market Microstructure Invariants
When evaluating any Level-2 order book snapshot:
1. **Uncrossed Book Guarantee:**
   $$\text{best\_ask} > \text{best\_bid}$$
   If $\text{best\_ask} \le \text{best\_bid}$, raise `ValueError("Crossed or zero-spread order book detected")`.
2. **Spread Tick-Size Alignment:**
   $$\text{spread} = \text{best\_ask} - \text{best\_bid}$$
   $$\text{spread} \ge 0.50 \quad (\text{Minimum tick size for BTCUSD on Delta Exchange})$$
3. **Normalized Order Book Imbalance:**
   $$\text{Imbalance} = \frac{\text{BidContracts} - \text{AskContracts}}{\text{BidContracts} + \text{AskContracts}}$$
   $$\text{Imbalance} \in [-1.0, 1.0]$$
   - If $\text{TotalDepth} = 0$, Imbalance is defined as $0.0$.
4. **Execution Conservation Law:**
   For any market execution with budget $B$:
   $$\text{Executed Notional (USD)} + \text{Unfilled USD} = B$$
   $$\text{Average Price} = \frac{\text{Executed Notional}}{\text{Executed Contracts} \times \text{Contract Value}}$$
