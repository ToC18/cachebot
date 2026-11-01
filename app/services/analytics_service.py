import io
from decimal import Decimal
from typing import Dict, List, Tuple
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


class AnalyticsService:
    @staticmethod
    def generate_budget_breakdown_chart(
        frozen_obligations: Decimal,
        savings_total: Decimal,
        flexible_spent: Decimal,
        safe_spend_balance: Decimal,
        currency: str = "BYN"
    ) -> bytes:
        labels = []
        sizes = []
        colors = []

        if frozen_obligations > 0:
            labels.append(f"Обязательства\n({frozen_obligations} {currency})")
            sizes.append(float(frozen_obligations))
            colors.append("#34495e")

        if savings_total > 0:
            labels.append(f"Копилка/Подушка\n({savings_total} {currency})")
            sizes.append(float(savings_total))
            colors.append("#2ecc71")

        if flexible_spent > 0:
            labels.append(f"Потрачено (гибкие)\n({flexible_spent} {currency})")
            sizes.append(float(flexible_spent))
            colors.append("#e74c3c")

        if safe_spend_balance > 0:
            labels.append(f"Свободный остаток\n({safe_spend_balance} {currency})")
            sizes.append(float(safe_spend_balance))
            colors.append("#3498db")

        if not sizes:
            sizes = [1]
            labels = ["Нет данных"]
            colors = ["#bdc3c7"]

        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(aspect="equal"))
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            colors=colors,
            pctdistance=0.75,
            textprops=dict(color="#2c3e50", fontsize=10, weight="bold")
        )

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(10)
            autotext.set_weight('bold')

        centre_circle = plt.Circle((0, 0), 0.50, fc='white')
        fig.gca().add_artist(centre_circle)

        plt.title("Структура твоего бюджета (ZBB)", fontsize=13, weight="bold", pad=20)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    @staticmethod
    def generate_expense_categories_chart(
        categories: Dict[str, Decimal],
        currency: str = "BYN"
    ) -> bytes:
        """Чертит красивую круговую диаграмму распределения трат по категориям (фича 1)."""
        labels = []
        sizes = []
        palette = [
            "#e74c3c", "#3498db", "#f39c12", "#2ecc71", "#9b59b6",
            "#1abc9c", "#e67e22", "#34495e", "#d35400", "#7f8c8d"
        ]

        # Сортируем от больших к меньшим
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        for cat_name, amt in sorted_cats:
            if amt > Decimal("0.00"):
                clean_name = cat_name.split(" ", 1)[-1] if " " in cat_name else cat_name
                labels.append(f"{clean_name}\n({amt} {currency})")
                sizes.append(float(amt))

        if not sizes:
            sizes = [1]
            labels = ["Нет трат"]
            colors = ["#bdc3c7"]
        else:
            colors = palette[:len(sizes)]

        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(aspect="equal"))
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct="%1.1f%%",
            startangle=140,
            colors=colors,
            pctdistance=0.75,
            textprops=dict(color="#2c3e50", fontsize=9, weight="bold")
        )

        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontsize(9)
            autotext.set_weight('bold')

        centre_circle = plt.Circle((0, 0), 0.52, fc='white')
        fig.gca().add_artist(centre_circle)

        plt.title("Распределение расходов по категориям", fontsize=13, weight="bold", pad=20)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()
