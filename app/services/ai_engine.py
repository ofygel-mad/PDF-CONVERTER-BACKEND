"""
Local AI Engine — zero external dependencies, zero network calls.

Capabilities:
  • Merchant categorisation  (keyword taxonomy, 200+ patterns)
  • Recurring transaction detection  (signature clustering)
  • Spending trend analysis  (linear regression over daily totals)
  • Cash-flow velocity flags  (burst detection)
  • Z-score anomaly scoring  (replaces simple threshold heuristic)
  • Russian-language insight summary  (template engine, not LLM)
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.schemas.statement import ParsedStatement, StatementTransaction

# ──────────────────────────────────────────────────────────────────────────────
# Merchant → Category taxonomy
# Keys are regex patterns (case-insensitive); first match wins.
# ──────────────────────────────────────────────────────────────────────────────
_CATEGORY_RULES: list[tuple[str, str]] = [
    # ── Supermarkets & Groceries ──────────────────────────────────────────────
    (r"магнум|magnum", "Супермаркеты"),
    (r"small|смол", "Супермаркеты"),
    (r"metro cash|metro кэш", "Супермаркеты"),
    (r"zeleniy|зеленый|зелёный", "Супермаркеты"),
    (r"аян|ayan", "Супермаркеты"),
    (r"арзан|arzan", "Супермаркеты"),
    (r"абзал|abzal", "Супермаркеты"),
    (r"sulpak.*food|продукт", "Супермаркеты"),
    (r"spar|спар", "Супермаркеты"),
    (r"interspar|интерспар", "Супермаркеты"),
    (r"globus|глобус", "Супермаркеты"),
    (r"дикси|dixy", "Супермаркеты"),
    (r"пятёрочка|pyaterochka", "Супермаркеты"),
    (r"перекрёст|perekrestok", "Супермаркеты"),
    (r"ашан|auchan", "Супермаркеты"),

    # ── Food delivery & restaurants ──────────────────────────────────────────
    (r"wolt|вольт", "Доставка еды"),
    (r"glovo|гловo|гловo", "Доставка еды"),
    (r"яндекс[\s\.]*еда|yandex[\s\.]*food|yandex[\s\.]*eda", "Доставка еды"),
    (r"delivery[\s\.]*club", "Доставка еды"),
    (r"chocofood|чокофуд", "Доставка еды"),
    (r"mcdonald|макдонал", "Рестораны и кафе"),
    (r"kfc|кфс", "Рестораны и кафе"),
    (r"burger king|бургер кинг", "Рестораны и кафе"),
    (r"pizza hut|пицца хат", "Рестораны и кафе"),
    (r"domino.s pizza|доминос", "Рестораны и кафе"),
    (r"papa john|папа джон", "Рестораны и кафе"),
    (r"subway|сабвэй", "Рестораны и кафе"),
    (r"starbucks|старбакс", "Рестораны и кафе"),
    (r"cofix|кофикс", "Рестораны и кафе"),
    (r"shokoladnitsa|шоколадниц", "Рестораны и кафе"),
    (r"tanuki|тануки", "Рестораны и кафе"),
    (r"суши|sushi|суши", "Рестораны и кафе"),
    (r"plov|плов", "Рестораны и кафе"),
    (r"кафе|cafe|ресторан|restaurant|bistro|бистро", "Рестораны и кафе"),

    # ── Transport ────────────────────────────────────────────────────────────
    (r"яндекс[\s\.]*такси|yandex[\s\.]*taxi", "Транспорт"),
    (r"uber|убер", "Транспорт"),
    (r"bolt|болт", "Транспорт"),
    (r"indriver|indrive|индрайв", "Транспорт"),
    (r"gett|гетт", "Транспорт"),
    (r"такси|taxi|cab", "Транспорт"),
    (r"аэропорт|airport|авиа", "Транспорт"),
    (r"air astana|эйр астана", "Транспорт"),
    (r"fly arystan|флай арыстан", "Транспорт"),
    (r"qazaq air|казак эйр", "Транспорт"),
    (r"аэрофлот|aeroflot", "Транспорт"),
    (r"автобус|bus|метро|metro|трамвай", "Транспорт"),
    (r"parking|парковк|паркинг", "Транспорт"),
    (r"azs|азс|бензин|petrol|fuel|заправ", "Транспорт"),
    (r"shell|шелл", "Транспорт"),
    (r"гелиос|helios|kpi azs|казмунайгаз", "Транспорт"),

    # ── Online shopping ──────────────────────────────────────────────────────
    (r"kaspi[\s\.]*магазин|kaspi[\s\.]*shop|kaspi[\s\.]*market", "Онлайн-покупки"),
    (r"wildberries|вайлдберрис|wb\.ru", "Онлайн-покупки"),
    (r"ozon|озон", "Онлайн-покупки"),
    (r"lamoda|ламода", "Онлайн-покупки"),
    (r"aliexpress|алиэкспресс", "Онлайн-покупки"),
    (r"amazon|амазон", "Онлайн-покупки"),
    (r"ebay|ибэй", "Онлайн-покупки"),
    (r"joom|джум", "Онлайн-покупки"),
    (r"shein|шеин", "Онлайн-покупки"),

    # ── Clothing & footwear ──────────────────────────────────────────────────
    (r"zara|зара", "Одежда и обувь"),
    (r"h&m|h and m|h\.m\.", "Одежда и обувь"),
    (r"uniqlo|юникло", "Одежда и обувь"),
    (r"adidas|адидас", "Одежда и обувь"),
    (r"nike|найк", "Одежда и обувь"),
    (r"puma|пума", "Одежда и обувь"),
    (r"new balance|нью баланс", "Одежда и обувь"),
    (r"lcwaikiki|лс вайкики", "Одежда и обувь"),
    (r"oodji|уджи", "Одежда и обувь"),
    (r"gloria jeans|глория джинс", "Одежда и обувь"),
    (r"befree|бифри", "Одежда и обувь"),
    (r"colin.s|колинз", "Одежда и обувь"),
    (r"sulpak.*одежд|одежд|обувь|обувной", "Одежда и обувь"),

    # ── Healthcare & pharmacy ─────────────────────────────────────────────────
    (r"аптек|apteka|pharmacy|farmacy", "Медицина и аптеки"),
    (r"euromed|евромед", "Медицина и аптеки"),
    (r"invivo|инвиво", "Медицина и аптеки"),
    (r"доктор|doctor|clinic|клиник|hospital|больниц", "Медицина и аптеки"),
    (r"стоматолог|dental|dent|зубн", "Медицина и аптеки"),
    (r"лаборатор|analyzes|анализ", "Медицина и аптеки"),
    (r"medel|медел|на здоровь", "Медицина и аптеки"),

    # ── Utilities & housing ──────────────────────────────────────────────────
    (r"коммунал|utility|utilities|жкх|квартплат", "ЖКХ и коммунальные"),
    (r"водоканал|vodokanal", "ЖКХ и коммунальные"),
    (r"алматыэнергосбыт|энергосбыт|электроэнерги", "ЖКХ и коммунальные"),
    (r"тепло|теплосеть|heating", "ЖКХ и коммунальные"),
    (r"газ|gazprom|gas service", "ЖКХ и коммунальные"),
    (r"управдом|ksk|осмд|ао \"управление", "ЖКХ и коммунальные"),

    # ── Telecom & internet ───────────────────────────────────────────────────
    (r"beeline|билайн", "Связь и интернет"),
    (r"kcell|кселл", "Связь и интернет"),
    (r"activ|актив", "Связь и интернет"),
    (r"tele2|теле2", "Связь и интернет"),
    (r"altel|алтел", "Связь и интернет"),
    (r"казахтелеком|kazakhtelecom", "Связь и интернет"),
    (r"internet|интернет|wifi|wi-fi", "Связь и интернет"),
    (r"мобильн|mobile|gsm", "Связь и интернет"),

    # ── Entertainment & streaming ────────────────────────────────────────────
    (r"netflix|нетфликс", "Развлечения"),
    (r"spotify|спотифай", "Развлечения"),
    (r"youtube premium|ютуб", "Развлечения"),
    (r"apple music|эпл мьюзик", "Развлечения"),
    (r"yandex[\s\.]*музыка|яндекс[\s\.]*музык", "Развлечения"),
    (r"steam|стим|игр|game|gaming", "Развлечения"),
    (r"кино|cinema|film|movie|кинотеатр", "Развлечения"),
    (r"театр|theatre|concert|концерт", "Развлечения"),
    (r"казино|casino|букмекер|betting|ставк", "Развлечения"),

    # ── Education ────────────────────────────────────────────────────────────
    (r"coursera|udemy|skillfactory|skyeng|нетолог", "Образование"),
    (r"школ|school|university|университет|колледж|college", "Образование"),
    (r"репетитор|tutor|обучени", "Образование"),

    # ── Financial services ───────────────────────────────────────────────────
    (r"страхован|insurance|insur", "Страхование и финансы"),
    (r"kredit|кредит|рассрочк|loan|займ", "Страхование и финансы"),
    (r"брокер|broker|invest|инвест", "Страхование и финансы"),

    # ── Electronics & tech ──────────────────────────────────────────────────
    (r"sulpak|сулпак", "Электроника"),
    (r"technodome|технодом", "Электроника"),
    (r"mechta|мечта", "Электроника"),
    (r"apple store|эпл стор|iphone|apple\.com", "Электроника"),
    (r"samsung|самсунг", "Электроника"),
    (r"dns|днс|re:store|реcтор", "Электроника"),

    # ── Transfers ────────────────────────────────────────────────────────────
    (r"перевод|transfer|p2p|перечислени", "Переводы"),
    (r"^ип |^тоо |^ао |^ООО ", "Переводы"),

    # ── Cash withdrawal ──────────────────────────────────────────────────────
    (r"снятие|atm|банкомат|cash withdrawal|наличн", "Снятие наличных"),

    # ── Top-up ───────────────────────────────────────────────────────────────
    (r"пополнение|зачислени|поступлени|deposit|top.?up", "Пополнение счёта"),
]

# Pre-compile patterns for performance
_COMPILED_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pattern, re.IGNORECASE), category)
    for pattern, category in _CATEGORY_RULES
]

# Operation-based fallback mapping
_OPERATION_CATEGORY: dict[str, str] = {
    "Покупка": "Покупки",
    "Перевод": "Переводы",
    "Пополнение": "Пополнение счёта",
    "Снятие": "Снятие наличных",
    "Разное": "Прочее",
}


# ──────────────────────────────────────────────────────────────────────────────
# Public data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CategoryResult:
    category: str
    confidence: float  # 0.0–1.0


@dataclass
class RecurringGroup:
    signature: str          # canonical merchant key
    category: str
    occurrences: int
    total_amount: float
    avg_amount: float
    dates: list[str]


@dataclass
class SpendingTrend:
    direction: str          # "growing" | "stable" | "declining"
    slope_pct: float        # % change per week (positive = growing)
    description: str


@dataclass
class AnomalyResult:
    row_index: int          # 0-based
    z_score: float
    reason: str


@dataclass
class AIInsights:
    categories: list[str] = field(default_factory=list)          # per-transaction, same order
    category_breakdown: dict[str, float] = field(default_factory=dict)  # category → total ₸
    top_merchants: list[dict[str, Any]] = field(default_factory=list)
    recurring: list[dict[str, Any]] = field(default_factory=list)
    trend: dict[str, Any] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    ai_available: bool = True


# ──────────────────────────────────────────────────────────────────────────────
# Merchant categoriser
# ──────────────────────────────────────────────────────────────────────────────

def categorize_transaction(transaction: StatementTransaction) -> CategoryResult:
    """Classify a single transaction using the local taxonomy."""
    search_text = f"{transaction.detail} {transaction.operation}".strip()

    for pattern, category in _COMPILED_RULES:
        if pattern.search(search_text):
            return CategoryResult(category=category, confidence=0.92)

    # Fallback: operation-based
    op_category = _OPERATION_CATEGORY.get(transaction.operation)
    if op_category:
        return CategoryResult(category=op_category, confidence=0.60)

    return CategoryResult(category="Прочее", confidence=0.40)


# ──────────────────────────────────────────────────────────────────────────────
# Anomaly detection — Z-score + velocity
# ──────────────────────────────────────────────────────────────────────────────

def detect_anomalies(transactions: list[StatementTransaction]) -> list[AnomalyResult]:
    """
    Enhanced anomaly detection using Z-scores on expense amounts.
    Flags transactions whose |z-score| > 2.5 (roughly top/bottom 1.2%).
    Also flags velocity bursts: ≥5 outflow transactions on the same day.
    """
    results: list[AnomalyResult] = []

    expenses = [t.expense for t in transactions if t.expense is not None and t.expense > 0]
    if len(expenses) < 4:
        return results

    mean = statistics.mean(expenses)
    stdev = statistics.stdev(expenses)
    if stdev < 1e-6:
        return results

    # Z-score anomalies
    for idx, t in enumerate(transactions):
        if t.expense is None or t.expense <= 0:
            continue
        z = (t.expense - mean) / stdev
        if abs(z) > 2.5:
            results.append(
                AnomalyResult(
                    row_index=idx,
                    z_score=round(z, 2),
                    reason=f"Сумма {t.expense:,.0f} ₸ — статистический выброс (z={z:.1f})",
                )
            )

    # Velocity burst: 5+ outflows in the same calendar day
    day_counts: Counter[str] = Counter(
        t.date for t in transactions if t.direction == "outflow"
    )
    burst_days = {day for day, count in day_counts.items() if count >= 5}
    for idx, t in enumerate(transactions):
        if t.date in burst_days and t.direction == "outflow":
            already = any(r.row_index == idx for r in results)
            if not already:
                results.append(
                    AnomalyResult(
                        row_index=idx,
                        z_score=0.0,
                        reason=f"Всплеск активности: {day_counts[t.date]} операций за {t.date}",
                    )
                )

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Recurring transaction detector
# ──────────────────────────────────────────────────────────────────────────────

def detect_recurring(transactions: list[StatementTransaction]) -> list[RecurringGroup]:
    """
    Identifies transactions with the same merchant (normalised detail) that
    appear ≥ 2 times.  Marks subscriptions, regular transfers, etc.
    """
    groups: dict[str, list[StatementTransaction]] = defaultdict(list)
    for t in transactions:
        key = _normalize_merchant(t.detail)
        if key:
            groups[key].append(t)

    recurring: list[RecurringGroup] = []
    for signature, group in groups.items():
        if len(group) < 2:
            continue
        expenses = [t.expense or 0.0 for t in group]
        total = sum(expenses)
        avg = total / len(group)
        cat = categorize_transaction(group[0]).category
        recurring.append(
            RecurringGroup(
                signature=signature,
                category=cat,
                occurrences=len(group),
                total_amount=round(total, 2),
                avg_amount=round(avg, 2),
                dates=sorted({t.date for t in group}),
            )
        )

    # Sort by total amount descending
    recurring.sort(key=lambda g: g.total_amount, reverse=True)
    return recurring[:10]


def _normalize_merchant(detail: str) -> str:
    """Strip noise, lowercase, keep first 30 chars as merchant key."""
    cleaned = re.sub(r"\s+", " ", detail.strip().lower())
    cleaned = re.sub(r"\d{4,}", "", cleaned)      # remove long numbers
    cleaned = re.sub(r"[^\w\s]", "", cleaned)     # remove punctuation
    return cleaned[:30].strip()


# ──────────────────────────────────────────────────────────────────────────────
# Spending trend (linear regression over daily totals)
# ──────────────────────────────────────────────────────────────────────────────

def compute_spending_trend(transactions: list[StatementTransaction]) -> SpendingTrend:
    """
    Fits a simple linear regression on daily expense totals.
    Returns direction and weekly slope percentage.
    """
    daily: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.expense:
            daily[t.date] = daily[t.date] + t.expense

    if len(daily) < 3:
        return SpendingTrend(direction="stable", slope_pct=0.0, description="Недостаточно данных для анализа тренда.")

    dates_sorted = sorted(daily.keys())
    n = len(dates_sorted)
    day_indices = list(range(n))
    y = [daily[d] for d in dates_sorted]

    # Simple least-squares slope
    x_mean = (n - 1) / 2
    y_mean = statistics.mean(y)
    numerator = sum((day_indices[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((day_indices[i] - x_mean) ** 2 for i in range(n))

    if denominator < 1e-9 or y_mean < 1e-6:
        return SpendingTrend(direction="stable", slope_pct=0.0, description="Расходы стабильны на протяжении периода.")

    slope = numerator / denominator
    weekly_slope_pct = round((slope * 7 / y_mean) * 100, 1)

    if weekly_slope_pct > 10:
        direction = "growing"
        desc = f"Расходы растут — прибавляют примерно {weekly_slope_pct:.0f}% в неделю."
    elif weekly_slope_pct < -10:
        direction = "declining"
        desc = f"Расходы снижаются — сокращаются примерно на {abs(weekly_slope_pct):.0f}% в неделю."
    else:
        direction = "stable"
        desc = "Расходы стабильны — резкого роста или снижения не выявлено."

    return SpendingTrend(direction=direction, slope_pct=weekly_slope_pct, description=desc)


# ──────────────────────────────────────────────────────────────────────────────
# Smart Russian-language summary generator
# ──────────────────────────────────────────────────────────────────────────────

def generate_summary(
    statement: ParsedStatement,
    categories: list[str],
    trend: SpendingTrend,
    anomalies: list[AnomalyResult],
    recurring: list[RecurringGroup],
) -> str:
    """
    Assembles a concise human-readable analysis in Russian without any LLM.
    All text is derived deterministically from the computed statistics.
    """
    meta = statement.metadata
    txs = statement.transactions
    totals = meta.totals

    parts: list[str] = []

    # ── Period header ──────────────────────────────────────────────────────
    period = ""
    if meta.period_start and meta.period_end:
        period = f" за период {meta.period_start} – {meta.period_end}"

    parts.append(
        f"Выписка{period} содержит {len(txs)} операций: "
        f"приход {_fmt(totals.income_total)} ₸, расход {_fmt(totals.expense_total)} ₸."
    )

    # ── Top category ──────────────────────────────────────────────────────
    cat_totals: dict[str, float] = defaultdict(float)
    for t, cat in zip(txs, categories):
        if t.expense:
            cat_totals[cat] += t.expense
    if cat_totals:
        top_cat, top_amount = max(cat_totals.items(), key=lambda x: x[1])
        top_pct = top_amount / totals.expense_total * 100 if totals.expense_total else 0
        parts.append(
            f"Наибольшая доля расходов приходится на «{top_cat}» — "
            f"{_fmt(top_amount)} ₸ ({top_pct:.0f}% от общих трат)."
        )

    # ── Trend ─────────────────────────────────────────────────────────────
    parts.append(trend.description)

    # ── Recurring ─────────────────────────────────────────────────────────
    if recurring:
        top_rec = recurring[0]
        parts.append(
            f"Регулярный платёж: «{top_rec.signature}» встречается {top_rec.occurrences} раз "
            f"на сумму {_fmt(top_rec.total_amount)} ₸."
        )

    # ── Anomalies ─────────────────────────────────────────────────────────
    zscore_anomalies = [a for a in anomalies if abs(a.z_score) > 2.5]
    if zscore_anomalies:
        parts.append(
            f"Обнаружено {len(zscore_anomalies)} статистически нетипичных операции — "
            "рекомендуется проверить перед экспортом."
        )

    return " ".join(parts)


def _fmt(value: float) -> str:
    """Format a currency value with thousands separator."""
    return f"{value:,.0f}".replace(",", " ")


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def enrich_statement(statement: ParsedStatement) -> tuple[ParsedStatement, AIInsights]:
    """
    Run the full local AI pipeline on a parsed statement.
    Returns:
      • updated statement with .category set on every transaction
      • AIInsights dataclass with all computed analytics
    Never raises; falls back gracefully on any error.
    """
    try:
        return _run_enrichment(statement)
    except Exception:
        empty = AIInsights(
            categories=["Прочее"] * len(statement.transactions),
            ai_available=False,
        )
        return statement, empty


def _run_enrichment(
    statement: ParsedStatement,
) -> tuple[ParsedStatement, AIInsights]:
    txs = statement.transactions

    # 1. Categorise every transaction
    cat_results = [categorize_transaction(t) for t in txs]
    categories = [r.category for r in cat_results]

    # 2. Stamp category onto transaction objects
    enriched_txs = [
        t.model_copy(update={"category": cat})
        for t, cat in zip(txs, categories)
    ]
    enriched_statement = statement.model_copy(update={"transactions": enriched_txs})

    # 3. Category breakdown (expenses only)
    cat_totals: dict[str, float] = defaultdict(float)
    for t, cat in zip(enriched_txs, categories):
        if t.expense:
            cat_totals[cat] += t.expense
    category_breakdown = {k: round(v, 2) for k, v in sorted(cat_totals.items(), key=lambda x: -x[1])}

    # 4. Top merchants by spend
    merchant_totals: dict[str, float] = defaultdict(float)
    merchant_counts: Counter[str] = Counter()
    for t in enriched_txs:
        if t.expense:
            key = _normalize_merchant(t.detail) or t.operation
            merchant_totals[key] += t.expense
            merchant_counts[key] += 1
    top_merchants = [
        {"name": name, "total": round(amount, 2), "count": merchant_counts[name]}
        for name, amount in sorted(merchant_totals.items(), key=lambda x: -x[1])[:8]
    ]

    # 5. Recurring transactions
    recurring = detect_recurring(enriched_txs)
    recurring_dicts = [
        {
            "signature": g.signature,
            "category": g.category,
            "occurrences": g.occurrences,
            "total_amount": g.total_amount,
            "avg_amount": g.avg_amount,
            "dates": g.dates,
        }
        for g in recurring
    ]

    # 6. Trend analysis
    trend = compute_spending_trend(enriched_txs)
    trend_dict = {
        "direction": trend.direction,
        "slope_pct": trend.slope_pct,
        "description": trend.description,
    }

    # 7. Anomaly detection
    anomalies = detect_anomalies(enriched_txs)
    anomaly_dicts = [
        {"row_index": a.row_index, "z_score": a.z_score, "reason": a.reason}
        for a in anomalies
    ]

    # 8. Natural language summary
    summary = generate_summary(enriched_statement, categories, trend, anomalies, recurring)

    insights = AIInsights(
        categories=categories,
        category_breakdown=category_breakdown,
        top_merchants=top_merchants,
        recurring=recurring_dicts,
        trend=trend_dict,
        anomalies=anomaly_dicts,
        summary=summary,
        ai_available=True,
    )

    return enriched_statement, insights
