import time
import datetime
import MetaTrader5 as mt5
import config
import mt5_bridge
import chart_capturer
import order_executor
import agent_committee
import bigquery_logger
import discord_notifier
import opportunity_monitor
from schemas import MarketAnalysisPayload, CandleData

def run_pipeline_cycle(symbol=config.DEFAULT_SYMBOL, dry_run=not config.LIVE_TRADING_ENABLED):
    """
    1回の完全な分析〜合議〜発注〜通知〜クリーンアップサイクルを実行する
    """
    print(f"\n==========================================")
    print(f"🚀 【パイプライン実行開始】 {symbol} (実発注モード: {'ON (LIVE)' if not dry_run else 'OFF (DRY-RUN)'}) - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"==========================================")

    # 1. MT5 初期化 & 接続確認
    if not mt5_bridge.initialize_mt5():
        print("[ERROR] MT5接続に失敗したため、サイクルを中断します。")
        return

    # 2. リアルタイム価格 & スプレッドの取得
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"[ERROR] {symbol} のシンボル情報が見つかりません。")
        mt5.shutdown()
        return

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"[ERROR] {symbol} のTick取得に失敗しました。")
        mt5.shutdown()
        return

    current_price = tick.ask
    if "XAU" in symbol.upper() or "GOLD" in symbol.upper():
        spread_pips = round((tick.ask - tick.bid) / 0.10, 1)
    else:
        pip_size = symbol_info.point * (10 if symbol_info.digits in [3, 5] else 1)
        spread_pips = round((tick.ask - tick.bid) / pip_size, 1)
    print(f"[MARKET STATE] 現在価格: ${current_price:.2f}, スプレッド: {spread_pips} pips")

    # 3. マルチタイムフレームローソク足の取得
    df_h1 = mt5_bridge.get_ohlcv_data(symbol, mt5.TIMEFRAME_H1, count=15)
    df_m15 = mt5_bridge.get_ohlcv_data(symbol, mt5.TIMEFRAME_M15, count=15)

    candles_h1 = [
        CandleData(
            time=str(row['time']),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=int(row['tick_volume'])
        ) for _, row in df_h1.iterrows()
    ] if df_h1 is not None else []

    candles_m15 = [
        CandleData(
            time=str(row['time']),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=int(row['tick_volume'])
        ) for _, row in df_m15.iterrows()
    ] if df_m15 is not None else []

    # 4. エフェメラル・チャート画像の生成 & クリーンアップ
    chart_path = chart_capturer.generate_multi_timeframe_chart(symbol)
    chart_capturer.cleanup_temp_image(chart_path)

    # 5. 分析ペイロードの構築
    payload = MarketAnalysisPayload(
        symbol=symbol,
        current_price=current_price,
        spread_pips=spread_pips,
        candles_h1=candles_h1,
        candles_m15=candles_m15,
        fred_macro_summary="US Real Yields (TIPS) rangebound, DXY consolidates",
        best_fit_ma_info="H1: 89EMA support valid, H4: 55EMA trending",
        retail_sentiment_ratio=0.72
    )

    # 6. Tier 1 クオンツ ＆ Tier 2 AI Multi-Agent 合議体判定
    print("[AI COMMITTEE] 8大エージェント合議体を招集し、相場を分析中...")
    decision = agent_committee.evaluate_market_committee(payload)
    print(f"[DECISION RESULT] アクション: {decision.action}, 方向: {decision.direction}, 確信度: {decision.final_confidence * 100:.1f}%")

    # 7. BigQuery ログ記録
    bigquery_logger.log_agent_decision(decision)

    # 8. トレード機会 ＆ 機会損失の監視
    abstain_streak, alerted = opportunity_monitor.update_opportunity_metrics(decision.action)
    if abstain_streak > 0:
        print(f"[OPPORTUNITY STATS] 連続見送り回数: {abstain_streak} サイクル (監視中)")

    # 9. Discord リッチ通知送信
    discord_notifier.send_discord_decision_alert(decision, current_price)

    # 9. エグゼキューション (実発注判断 & ハードSL付与)
    if decision.action in ["TACTICAL_A_MARKET", "TACTICAL_B_PENDING"] and decision.cfo_risk_approval and decision.direction in ["BUY", "SELL"]:
        print(f"[EXECUTION TRIGGER] {decision.direction} 注文を発注します (ハードSL: {decision.suggested_sl_pips} pips, TP: {decision.suggested_tp_pips} pips)")
        if not dry_run:
            order_executor.execute_market_order_with_hard_sl(
                symbol=symbol,
                action=decision.direction,
                volume=decision.cfo_lot_size,
                sl_pips=decision.suggested_sl_pips,
                tp_pips=decision.suggested_tp_pips
            )
        else:
            print("[DRY-RUN] 実発注はスキップされました (ドライランモード有効)")
    else:
        print(f"[STANDBY] 見送りまたは待機アクションのため発注は見送られました: {decision.action}")

    mt5.shutdown()
    print("==========================================")
    print("🎉 【パイプライン実行完了】")
    print("==========================================\n")

if __name__ == "__main__":
    run_pipeline_cycle(symbol=config.DEFAULT_SYMBOL, dry_run=not config.LIVE_TRADING_ENABLED)
