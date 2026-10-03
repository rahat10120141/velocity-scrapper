import pandas as pd
import numpy as np
from binance_client import BinanceClient
from indicators import compute_all_indicators

def supertrend(df, period=10, mult=2.2):
    hl2 = (df['high'] + df['low']) / 2
    c_prev = df['close'].shift(1)
    tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - c_prev), abs(df['low'] - c_prev)))
    atr = tr.rolling(period).mean()
    up = hl2 - (mult * atr)
    dn = hl2 + (mult * atr)
    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    current_dir = 1
    for i in range(period, len(df)):
        c = df['close'].iloc[i]
        c_p = df['close'].iloc[i-1]
        curr_up = up.iloc[i]
        curr_dn = dn.iloc[i]
        prev_up = up.iloc[i-1] if i > period else curr_up
        prev_dn = dn.iloc[i-1] if i > period else curr_dn
        if c_p > prev_up: curr_up = max(curr_up, prev_up)
        if c_p < prev_dn: curr_dn = min(curr_dn, prev_dn)
        if current_dir == 1:
            if c < curr_up:
                current_dir = -1
                st.iloc[i] = curr_dn
            else: st.iloc[i] = curr_up
        else:
            if c > curr_dn:
                current_dir = 1
                st.iloc[i] = curr_up
            else: st.iloc[i] = curr_dn
        direction.iloc[i] = current_dir
    return st, direction

client = BinanceClient(mode='FUTURES')
df = client.fetch_klines('SOLUSDT', interval='1m', limit=3000)
df_ind = compute_all_indicators(df, {'ema_fast': 20, 'ema_slow': 50, 'bb_period': 20, 'bb_std': 2.0, 'rsi_period': 14, 'stoch_period': 14, 'stoch_k': 3, 'stoch_d': 3, 'volume_ma_period': 20})
st, direction = supertrend(df, period=10, mult=2.2)
df_ind['st_dir'] = direction

trades = []
in_t = False
notional = 125.0
fee = 0.0004 * 2 # 0.08%

for i in range(50, len(df_ind)):
    r = df_ind.iloc[i]
    prev = df_ind.iloc[i-1]
    c, h, l, o = r['close'], r['high'], r['low'], r['open']
    
    if in_t:
        dur += 1
        # Breakeven & Trailing logic
        if side == 'BUY':
            if h > peak: peak = h
            # If hit +0.35%, move sl to BE + 0.1%
            if (peak - ep)/ep >= 0.0035 and sl < ep * 1.001:
                sl = ep * 1.001
            # Check TP
            if h >= tp:
                trades.append(('BUY', ep, tp, (tp - ep)/ep * notional - notional*fee, dur, 'TP'))
                in_t = False
            elif l <= sl:
                trades.append(('BUY', ep, sl, (sl - ep)/ep * notional - notional*fee, dur, 'SL'))
                in_t = False
            elif dur >= 25:
                trades.append(('BUY', ep, c, (c - ep)/ep * notional - notional*fee, dur, 'TIME'))
                in_t = False
        elif side == 'SELL':
            if l < peak: peak = l
            if (ep - peak)/ep >= 0.0035 and sl > ep * 0.999:
                sl = ep * 0.999
            if l <= tp:
                trades.append(('SELL', ep, tp, (ep - tp)/ep * notional - notional*fee, dur, 'TP'))
                in_t = False
            elif h >= sl:
                trades.append(('SELL', ep, sl, (ep - sl)/ep * notional - notional*fee, dur, 'SL'))
                in_t = False
            elif dur >= 25:
                trades.append(('SELL', ep, c, (ep - c)/ep * notional - notional*fee, dur, 'TIME'))
                in_t = False
        continue

    # Entry logic:
    stoch_bull = (r['stoch_k'] > r['stoch_d']) and (prev['stoch_k'] <= prev['stoch_d']) and (r['stoch_k'] <= 25)
    stoch_bear = (r['stoch_k'] < r['stoch_d']) and (prev['stoch_k'] >= prev['stoch_d']) and (r['stoch_k'] >= 75)
    
    if r['st_dir'] == 1 and stoch_bull and c > o and r['vol_ratio'] >= 0.9:
        in_t = True
        side = 'BUY'
        ep = c
        tp = ep * 1.0075
        sl = ep * 0.9955
        peak = ep
        dur = 0
    elif r['st_dir'] == -1 and stoch_bear and c < o and r['vol_ratio'] >= 0.9:
        in_t = True
        side = 'SELL'
        ep = c
        tp = ep * 0.9925
        sl = ep * 1.0045
        peak = ep
        dur = 0

tdf = pd.DataFrame(trades, columns=['side', 'ep', 'xp', 'pnl', 'dur', 'reason'])
wins = tdf[tdf['pnl'] > 0]
losses = tdf[tdf['pnl'] <= 0]
print(f'Total Trades: {len(tdf)}')
if len(tdf) > 0:
    print(f'Win Rate: {len(wins)/len(tdf)*100:.1f}% ({len(wins)}W / {len(losses)}L)')
    print(f'Total Net Profit: ${tdf["pnl"].sum():+.2f}')
    print(f'Profit Factor: {wins["pnl"].sum() / abs(losses["pnl"].sum() + 1e-9):.2f}')
    print(f'Average Trade Duration: {tdf["dur"].mean():.1f} min')
    print(tdf['reason'].value_counts())
