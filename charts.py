import pandas as pd
from prophet import Prophet
import plotly.graph_objs as go

from forecaster import HyperliquidForecaster


class ForecastChart:
    """
    Genera grafici di previsione stile 'Binance dark' usando:
    - i dati di Hyperliquid (tramite HyperliquidForecaster)
    - un modello Prophet ricostruito qui dentro

    NON richiede modifiche a forecaster.py.
    """

    def __init__(self, testnet: bool = True):
        self.forecaster = HyperliquidForecaster(testnet=testnet)

    def plot(self, coin: str, interval: str = "15m", n_future: int = 4):
        """
        Crea un grafico interattivo per un singolo coin.

        :param coin: es. "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE"
        :param interval: "15m" o "1h"
        :param n_future: numero di punti futuri da predire (default 4)
        """

        # 1) Recupero storico prezzi tramite il forecaster di Simone
        if interval == "15m":
            df_hist = self.forecaster._fetch_candles(coin, "15m", limit=300)
            freq = "15min"
            tf_label = "Prossimi 15 Minuti"
        elif interval == "1h":
            df_hist = self.forecaster._fetch_candles(coin, "1h", limit=500)
            freq = "H"
            tf_label = "Prossima Ora"
        else:
            raise ValueError("interval deve essere '15m' oppure '1h'")

        if df_hist.empty:
            raise RuntimeError(f"Nessun dato storico per {coin} ({interval})")

        last_price = df_hist["y"].iloc[-1]

        # 2) Modello Prophet (stile Simone: daily + weekly)
        model = Prophet(daily_seasonality=True, weekly_seasonality=True)
        model.fit(df_hist)

        # 3) Creazione serie futura (n_future punti in avanti)
        future = model.make_future_dataframe(periods=n_future, freq=freq)
        forecast = model.predict(future)

        # 4) Separiamo storico vs futuro
        last_hist_ts = df_hist["ds"].max()
        forecast_future = forecast[forecast["ds"] > last_hist_ts]

        # 5) Costruzione grafico Plotly
        fig = go.Figure()

        # Prezzo reale storico
        fig.add_trace(go.Scatter(
            x=df_hist["ds"],
            y=df_hist["y"],
            mode="lines",
            name="Prezzo Reale",
            line=dict(color="#1f9d55")  # verde
        ))

        # Previsione (intera serie yhat)
        fig.add_trace(go.Scatter(
            x=forecast["ds"],
            y=forecast["yhat"],
            mode="lines",
            name="Previsione",
            line=dict(color="#f6465d")  # rosso
        ))

        # Banda di confidenza
        fig.add_trace(go.Scatter(
            x=forecast["ds"],
            y=forecast["yhat_upper"],
            mode="lines",
            line=dict(color="rgba(246,70,93,0.2)"),
            showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=forecast["ds"],
            y=forecast["yhat_lower"],
            mode="lines",
            line=dict(color="rgba(246,70,93,0.2)"),
            fill="tonexty",
            name="Intervallo di Confidenza"
        ))

        # Punto futuro evidenziato (ultimo punto previsto)
        if not forecast_future.empty:
            last_fc = forecast_future.tail(1).iloc[0]
            fig.add_trace(go.Scatter(
                x=[last_fc["ds"]],
                y=[last_fc["yhat"]],
                mode="markers",
                name="Previsione Futura",
                marker=dict(size=10, color="#f0b90b", symbol="star")
            ))

        # 6) Layout stile Binance dark
        title = f"{coin} — {tf_label}"
        fig.update_layout(
            title=dict(
                text=title,
                x=0.5,
                xanchor="center",
                font=dict(size=20, color="#f0b90b")  # giallo Binance
            ),
            plot_bgcolor="#0b0e11",
            paper_bgcolor="#0b0e11",
            hovermode="x unified",
            font=dict(color="#eaecef"),
            xaxis=dict(
                title="Data/Ora",
                showgrid=True,
                gridcolor="rgba(150,150,150,0.15)",
                zeroline=False,
                showline=True,
                linecolor="rgba(150,150,150,0.3)",
            ),
            yaxis=dict(
                title="Prezzo (USD)",
                showgrid=True,
                gridcolor="rgba(150,150,150,0.15)",
                zeroline=False,
                showline=True,
                linecolor="rgba(150,150,150,0.3)",
            ),
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                bordercolor="rgba(150,150,150,0.2)",
                borderwidth=1
            )
        )

        fig.show()


if __name__ == "__main__":
    # Esempio: grafico BTC 15m su testnet
    chart = ForecastChart(testnet=True)
    chart.plot("BTC", interval="15m", n_future=4)
    # Puoi provare anche:
    # chart.plot("ETH", interval="1h", n_future=6)
