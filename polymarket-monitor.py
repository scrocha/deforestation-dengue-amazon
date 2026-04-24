import ast
import math
import os
import time
from datetime import datetime, timezone

import requests

# ==========================================
# CONFIGURAÇÃO
# ==========================================
CONFIG = {
    "max_time_left_seconds": 45,
    "safe_price_delta_usd": 15.0,
    "max_buy_price": 0.96,
    "min_ask_liquidity_usdc": 5.0,
    "taker_fee_rate": 0.072,
    "gamma_url": "https://gamma-api.polymarket.com",
    "clob_url": "https://clob.polymarket.com",
    "binance_url": "https://api.binance.com",
    "simulation_invest_usd": 1.00,  # Valor base para simulação no dashboard
}

strike_cache: dict[str, float] = {}


# ==========================================
# FUNÇÕES DE API
# ==========================================
def get_btc_price() -> float | None:
    try:
        res = requests.get(
            f"{CONFIG['binance_url']}/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=2,
        )
        return float(res.json()["price"])
    except:
        return None


def get_event_by_slug(slug: str) -> dict | None:
    try:
        res = requests.get(
            f"{CONFIG['gamma_url']}/events", params={"slug": slug}, timeout=3
        )
        data = res.json()
        return data[0] if data else None
    except:
        return None


def get_current_and_next_slugs(n=3) -> list[str]:
    now = int(datetime.now(timezone.utc).timestamp())
    slot = math.ceil(now / 300) * 300
    return [f"btc-updown-5m-{slot + i * 300}" for i in range(-1, n)]


def find_current_market() -> dict | None:
    for slug in get_current_and_next_slugs():
        event = get_event_by_slug(slug)
        if (
            event
            and event.get("active", True)
            and not event.get("closed", False)
        ):
            markets = event.get("markets", [])
            if not markets:
                continue

            market = markets[0]
            start_str = (
                market.get("startDate")
                or market.get("eventStartTime")
                or market.get("startTime")
            )
            end_str = market.get("endDate")
            now = datetime.now(timezone.utc)

            if start_str and end_str:
                try:
                    start = datetime.fromisoformat(
                        start_str.replace("Z", "+00:00")
                    )
                    end = datetime.fromisoformat(
                        end_str.replace("Z", "+00:00")
                    )
                    if start <= now < end:
                        market["slug"] = slug
                        return market
                except:
                    pass
    return None


def extract_tokens(market: dict) -> tuple[str | None, str | None]:
    try:
        outcomes = ast.literal_eval(market.get("outcomes", "[]"))
        tokens = ast.literal_eval(market.get("clobTokenIds", "[]"))
        up_idx = next(
            (i for i, o in enumerate(outcomes) if "up" in o.lower()), 0
        )
        down_idx = next(
            (i for i, o in enumerate(outcomes) if "down" in o.lower()), 1
        )
        return tokens[up_idx], tokens[down_idx]
    except:
        return None, None


def get_live_orderbook(token_id: str) -> tuple[float | None, float | None]:
    """Retorna (Best Ask Price, Ask Liquidity) diretamente do CLOB."""
    if not token_id:
        return None, None
    try:
        res = requests.get(
            f"{CONFIG['clob_url']}/book",
            params={"token_id": token_id},
            timeout=2,
        )
        if res.status_code != 200:
            return None, None
        asks = sorted(
            res.json().get("asks", []), key=lambda x: float(x.get("price", 1))
        )
        if not asks:
            return None, None
        best = asks[0]
        p = float(best["price"])
        return p, p * float(best["size"])
    except:
        return None, None


# ==========================================
# LÓGICA FINANCEIRA E DASHBOARD
# ==========================================
def simulate_trade(ask_price: float, invest: float) -> dict:
    if not ask_price or ask_price <= 0:
        return {
            "shares": 0,
            "gross": 0,
            "profit": 0,
            "fee": 0,
            "net": 0,
            "roi": 0,
        }

    shares = invest / ask_price
    gross_return = shares * 1.00
    gross_profit = gross_return - invest
    fee = gross_profit * CONFIG["taker_fee_rate"] if gross_profit > 0 else 0
    net_profit = gross_profit - fee
    roi = (net_profit / invest) * 100

    return {
        "shares": shares,
        "gross": gross_return,
        "profit": gross_profit,
        "fee": fee,
        "net": net_profit,
        "roi": roi,
    }


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def render_dashboard(
    market, btc, strike, time_left, delta, up_ask, up_liq, down_ask, down_liq
):
    clear_screen()
    side_winning = "UP" if delta >= 0 else "DOWN"
    delta_color = "\033[92m+" if delta >= 0 else "\033[91m-"
    reset = "\033[0m"

    sim_up = simulate_trade(up_ask, CONFIG["simulation_invest_usd"])
    sim_dw = simulate_trade(down_ask, CONFIG["simulation_invest_usd"])

    print("=" * 70)
    print(" 🚀 POLYMARKET BTC 5M - LATE ENTRY ARBITRAGE")
    print(f" Mercado: {market.get('slug', 'N/A')}")
    print(f" Tempo Restante: {time_left:.0f}s")
    print("=" * 70)
    print(" [ TRACKING DE PREÇO ]")
    print(f" BTC Atual    : ${btc:,.2f}")
    print(f" Strike Price : ${strike:,.2f}")
    print(
        f" Delta        : {delta_color}${abs(delta):.2f}{reset}  >>> Vencedor Atual: {side_winning}"
    )
    print("=" * 70)
    print(
        f" [ LIVE CLOB & SIMULAÇÃO (Investimento: ${CONFIG['simulation_invest_usd']:.2f}) ]"
    )
    print(
        f" {'Token':<6} | {'Odd':<6} | {'Liq($)':<8} | {'Bruto($)':<8} | {'Taxa($)':<7} | {'Líq($)':<7} | {'ROI'} "
    )
    print("-" * 70)

    def format_row(name, ask, liq, sim):
        if ask is None:
            return f" {name:<6} | {'-':<6} | {'-':<8} | {'-':<8} | {'-':<7} | {'-':<7} | -"
        return f" {name:<6} | {ask:<6.3f} | {liq:<8.2f} | {sim['gross']:<8.2f} | {sim['fee']:<7.3f} | {sim['net']:<7.2f} | {sim['roi']:+.1f}%"

    print(format_row("UP", up_ask, up_liq, sim_up))
    print(format_row("DOWN", down_ask, down_liq, sim_dw))
    print("=" * 70)

    # Validação do Sinal
    print(" [ STATUS DO BOT ]")

    reasons = []
    if time_left > CONFIG["max_time_left_seconds"]:
        reasons.append(f"Tempo > {CONFIG['max_time_left_seconds']}s")
    if abs(delta) < CONFIG["safe_price_delta_usd"]:
        reasons.append(f"Delta < ${CONFIG['safe_price_delta_usd']:.0f}")

    winning_ask = up_ask if side_winning == "UP" else down_ask
    winning_liq = up_liq if side_winning == "UP" else down_liq
    winning_sim = sim_up if side_winning == "UP" else sim_dw

    if not winning_ask:
        reasons.append("Sem liquidez no CLOB")
    elif winning_ask > CONFIG["max_buy_price"]:
        reasons.append(
            f"Odd ({winning_ask:.3f}) > Máx ({CONFIG['max_buy_price']:.3f})"
        )
    elif (winning_liq or 0) < CONFIG["min_ask_liquidity_usdc"]:
        reasons.append(f"Liquidez baixa (${winning_liq:.0f})")

    if not reasons:
        print(
            f" \033[92m[!!!] SINAL ATIVO - COMPRAR {side_winning} [!!!]\033[0m"
        )
        print(
            f" \033[92mLucro Líquido Esperado: {winning_sim['roi']:+.2f}%\033[0m"
        )
        return True  # Indica que o sinal está ativo
    else:
        print(f" \033[93mAGUARDAR:\033[0m {', '.join(reasons)}")
        return False


# ==========================================
# LOOP PRINCIPAL
# ==========================================
def run_strategy():
    last_slug = None

    while True:
        try:
            market = find_current_market()
            if not market:
                clear_screen()
                print("A aguardar novo ciclo ou sincronização da API...")
                time.sleep(3)
                continue

            slug = market.get("slug", "unknown")
            now = datetime.now(timezone.utc)
            end = datetime.fromisoformat(
                market.get("endDate").replace("Z", "+00:00")
            )
            time_left = (end - now).total_seconds()

            if time_left <= 0:
                time.sleep(3)
                continue

            if slug != last_slug:
                last_slug = slug
                strike = get_btc_price()
                if strike:
                    strike_cache[slug] = strike

            strike = strike_cache.get(slug)
            if not strike:
                time.sleep(1)
                continue

            btc = get_btc_price()
            if not btc:
                time.sleep(1)
                continue

            delta = btc - strike
            token_up, token_down = extract_tokens(market)

            # Bate no CLOB para ter Live Odds reais
            up_ask, up_liq = get_live_orderbook(token_up)
            down_ask, down_liq = get_live_orderbook(token_down)

            sinal_ativo = render_dashboard(
                market,
                btc,
                strike,
                time_left,
                delta,
                up_ask,
                up_liq,
                down_ask,
                down_liq,
            )

            if sinal_ativo:
                # TODO: py_clob_client para criar e enviar ordem
                time.sleep(
                    10
                )  # Pausa após sinal para não submeter ordens duplicadas
            else:
                time.sleep(1.5)  # Atualiza a UI a cada ~1.5s

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n[ERRO GLOBAL] {e}")
            time.sleep(2)


if __name__ == "__main__":
    run_strategy()
