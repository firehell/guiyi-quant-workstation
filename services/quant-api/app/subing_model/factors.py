"""Incremental adapters over the shared SuBing indicator functions."""
from dataclasses import asdict
from decimal import Decimal as D
from guiyi_quant.indicators import subing_trend, subing_macd, subing_volume, subing_price, subing_range, subing_conditions
from guiyi_quant.subing_recent_structure import State, Bar, step as structure_step

class Factors:
    def __init__(self,contract):
        self.contract=contract
        self.trends={f:subing_trend.initial_state(contract,f) for f in ('1d','30m','60m')}
        self.macd=subing_macd.initial_state(contract,'30m')
        self.volume=subing_volume.initial_state(contract,'30m')
        self.price=subing_price.PullbackState(contract)
        self.rebound=subing_price.PullbackState(contract,side='SHORT')
        self.range=subing_range.initial_state(contract,'30m',profile='bounded_confirmed')
        self.structure=State(contract)
        self.previous=None;self.daily=[];self.hourly=None;self.frame=None;self.structure_point=None

    def step(self,frequency,b):
        c=self.contract;at=b.bar_end
        self.trends[frequency],point=subing_trend.step(self.trends[frequency],contract=c,frequency=frequency,
            bar_end=at,high=float(b.high),low=float(b.low),close=float(b.close))
        if frequency=='1d':
            self.daily.append(dict(time=at.isoformat(),direction=point.direction));self.daily=self.daily[-2:];return
        if frequency=='60m':self.hourly=dict(at=at.isoformat(),direction=point.direction);return
        atr=D(str(point.atr14)) if point.atr14 is not None else None
        ema=D(str(point.ema21)) if point.ema21 is not None else None
        self.macd,cross=subing_macd.step(self.macd,contract=c,frequency='30m',bar_end=at,close=float(b.close))
        self.volume,vol=subing_volume.observe(self.volume,contract=c,frequency='30m',bar_end=at,volume=b.volume)
        price=subing_price.price_point(b.close,ema)
        self.price,pull=subing_price.observe(self.price,contract=c,bar_end=at,high=b.high,low=b.low,close=b.close,ema21=ema,atr14=atr,trend_direction=point.direction)
        self.rebound,rebound=subing_price.observe(self.rebound,contract=c,bar_end=at,high=b.high,low=b.low,close=b.close,ema21=ema,atr14=atr,trend_direction=point.direction,side='SHORT')
        self.range,r=subing_range.step(self.range,contract=c,frequency='30m',bar_end=at,high=b.high,low=b.low,close=b.close,atr=atr,trend_direction=point.direction)
        exits=subing_conditions.exit_facts(close=b.close,previous_low=self.previous.low if self.previous else None,ema21=ema,high_death=cross.high_death)
        self.frame=dict(high=str(b.high),low=str(b.low),near_zero_death=cross.near_zero_death,low_golden=cross.low_golden,
            above_previous_high=b.close>self.previous.high if self.previous else None,qualified_rebound=rebound['qualified_hold'],
            rebound_low=str(rebound['armed_high']) if rebound['qualified_hold'] else None,
            rebound_invalidated=price.below_ema is not True or point.direction in ('UP','UNKNOWN'),ema21=str(ema) if ema is not None else None,
            near_zero_golden=cross.near_zero_golden,minute_angle=str(point.angle) if point.angle is not None else None,
            above_ema=price.above_ema,volume_tier=vol.tier,volume_effective=vol.effective,below_previous_low=exits['below_previous_low'],
            high_death=cross.high_death,below_ema=price.below_ema,qualified_pullback=pull['qualified_hold'],
            pullback_high=str(pull['armed_high']) if pull['qualified_hold'] else None,
            pullback_invalidated=price.above_ema is not True or point.direction in ('DOWN','UNKNOWN'),regime=r.regime)
        self.structure,self.structure_point=structure_step(self.structure,Bar(at,b.high,b.low,b.close),contract=c)
        self.previous=b
        return dict(asdict(point),atr14=atr)

    def observation(self,b,day_end_window):
        daily=next((d for d in reversed(self.daily) if d['time']<b.bar_end.isoformat()),None)
        return dict(event_id=f'observe:{self.contract}:{b.bar_end.isoformat()}',kind='observe',at=b.bar_end.isoformat(),
            contract=self.contract,trading_day=b.trading_day.isoformat(),close=str(b.close),daily_direction=daily['direction'] if daily else 'UNKNOWN',
            daily_at=daily['time'] if daily else None,day_end_window=day_end_window,
            m30=self.frame if self.previous and self.previous.bar_end==b.bar_end else None)
