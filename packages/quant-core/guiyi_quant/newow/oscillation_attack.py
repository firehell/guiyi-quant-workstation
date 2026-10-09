"""Newow v3.3.79 display-only ZLGJ and independent SMA(9,3,3) J.

Auxiliary hints never become BUILD/CLEAR or quantity decisions.
"""
from decimal import Decimal, localcontext

FORMULA_VERSION = 'newow_oscillation_zlgj_sma_j_v1'


def calculate_oscillation_attack(bars):
    if len(bars) < 10:
        return ()
    with localcontext() as ctx:
        ctx.prec = 28
        eps, alpha = Decimal('1e-9'), Decimal(2) / 7
        num1 = num2 = den1 = den2 = Decimal(0)
        z, ma, j, peaks, output = [], [], [], [], []
        k = d = None
        last_buy = last_sell = -10**9
        for i, bar in enumerate(bars):
            mtm = bar.close - bars[i-1].close if i else Decimal(0)
            num1 += (mtm - num1) * alpha
            num2 += (num1 - num2) * alpha
            den1 += (abs(mtm) - den1) * alpha
            den2 += (den1 - den2) * alpha
            z.append(100 * num2 / den2 if abs(den2) > eps else Decimal(0))
            ma.append(sum(z[max(0,i-1):], Decimal(0)) / min(i+1,2))
            buy_raw = sell_raw = False
            if i >= 6:
                buy_raw = (abs(min(z[i-1:]) - min(z[i-6:])) < eps and z[i] < 0 and z[i-1] < 0
                    and z[i-1] <= ma[i-1] and z[i] > ma[i])
                sell_raw = (abs(max(z[i-1:]) - max(z[i-6:])) < eps and z[i] > 50 and z[i-1] > 50
                    and ma[i-1] <= z[i-1] and ma[i] > z[i])
            buy, sell = buy_raw and i-last_buy > 5, sell_raw and i-last_sell > 1
            if buy:
                last_buy = i
            if sell:
                last_sell = i
            span = bars[max(0,i-8):i+1]
            low, high = min(b.low for b in span), max(b.high for b in span)
            rsv = (bar.close-low)/(high-low)*100 if abs(high-low)>eps else Decimal(50)
            k = rsv if k is None else (rsv+2*k)/3
            d = k if d is None else (k+2*d)/3
            j.append(3*k-2*d)
            peaks.append(abs(max(j[max(0,i-1):])-max(j[max(0,i-7):]))<eps and j[i]>80)
            warning = i>=2 and j[i-2]-Decimal('.01')<j[i-1] and j[i-1]-Decimal('.01')>j[i] and peaks[i-1] and not sell_raw
            output.append(dict(zlgj=z[i], j=j[i], buy=buy, sell=sell, j_warning=warning))
        return tuple(output)
