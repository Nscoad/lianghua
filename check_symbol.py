"""
查询交易对信息
"""
from core.trader import client

resp = client.rest_api.exchange_information()
for s in resp.data().symbols:
    if "BANK" in s.symbol.upper():
        print(f"交易对: {s.symbol}  状态: {s.status}")
        print(f"  baseAsset: {s.base_asset}  quoteAsset: {s.quote_asset}")
        for f in s.filters:
            if hasattr(f, 'min_qty'):
                print(f"  LOT_SIZE: minQty={f.min_qty} maxQty={f.max_qty} stepSize={f.step_size}")
            elif hasattr(f, 'min_notional'):
                print(f"  MIN_NOTIONAL: {f.min_notional}")
            elif hasattr(f, 'tick_size'):
                print(f"  PRICE_FILTER: tickSize={f.tick_size}")
        print()
