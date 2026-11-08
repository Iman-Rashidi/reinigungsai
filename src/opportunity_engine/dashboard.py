"""Streamlit view for the persisted opportunity engine."""
from __future__ import annotations

import csv
import io

import streamlit as st

from .service import run_discovery
from .store import OpportunityStore, render_storage_warning


MANUAL_LINKS = [
    ("Bekanntmachungsservice", "https://oeffentlichevergabe.de/"),
    ("TED", "https://ted.europa.eu/de/"),
    ("Auftragsbank – Aufträge", "https://www.auftragsbank.de/auftraege"),
    ("eVergabe Online", "https://www.evergabe-online.de/"),
]


def _csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO()
    fields = [
        "title", "category", "opportunity_type", "buyer", "city", "region",
        "publication_date", "deadline", "estimated_value", "currency", "cpv",
        "score", "score_reason", "status", "source_ids", "url",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def render_opportunity_engine_tab() -> None:
    st.subheader("موتور چندمنبعی کشف سفارش و مناقصه")
    st.caption(
        "Bekanntmachungsservice و TED منابع رسمی هستند؛ Tavily فقط سیگنال‌های عمومی وب را اضافه می‌کند. "
        "نتیجه‌ها قبل از تأیید انسانی، سفارش قطعی محسوب نمی‌شوند."
    )

    db = OpportunityStore()
    warning = render_storage_warning(db.path)
    if warning:
        st.warning(warning)
    else:
        st.caption(f"مسیر پایگاه داده: {db.path}")

    with st.form("opportunity_engine_run"):
        col1, col2 = st.columns(2)
        city = col1.text_input("محدودهٔ جغرافیایی", value="NRW", help="NRW یا نام شهر مثل Viersen")
        category = col2.selectbox(
            "حوزهٔ خدمات",
            ["Alle", "Reinigung", "Sicherheit", "Facility Management", "Bau / Handwerk"],
            format_func=lambda value: {
                "Alle": "تمام حوزه‌های پشتیبانی‌شده",
                "Reinigung": "نظافت و Gebäudereinigung",
                "Sicherheit": "خدمات امنیتی",
                "Facility Management": "Facility Management",
                "Bau / Handwerk": "ساخت‌وساز و خدمات فنی",
            }.get(value, value),
        )
        col3, col4 = st.columns(2)
        days_back = col3.slider("روزهای گذشته برای BKMS", 1, 31, 7)
        include_tavily = col4.checkbox(
            "افزودن جست‌وجوی عمومی Tavily",
            value=bool(__import__("os").environ.get("TAVILY_API_KEY", "").strip()),
            help="TAVILY_API_KEY باید در Environment ثبت شده باشد.",
        )
        submitted = st.form_submit_button("اجرای موتور کشف", type="primary")

    if submitted:
        try:
            with st.spinner("منابع رسمی و عمومی در حال بررسی هستند؛ هر منبع مستقل خطایابی می‌شود..."):
                report = run_discovery(
                    city=city,
                    category=category,
                    days_back=days_back,
                    include_tavily=include_tavily,
                    store=db,
                )
            st.session_state["opportunity_engine_report"] = report
            st.success(
                f"اجرا تمام شد: {report['records_new']} فرصت جدید، "
                f"{report['records_changed']} تغییر و {report['records_seen']} رکورد بررسی‌شده."
            )
            if report["errors"]:
                st.warning(f"{report['errors']} منبع با خطا روبه‌رو شد؛ بقیهٔ منابع مستقل ادامه دادند.")
        except Exception as exc:
            st.error(f"اجرای موتور با خطا متوقف شد: {type(exc).__name__}: {exc}")

    report = st.session_state.get("opportunity_engine_report", {})
    if report:
        st.caption(
            f"آخرین اجرا: محدوده {report.get('city')} · حوزه {report.get('category')} · "
            f"دوره {report.get('days_back')} روز"
        )
        source_cols = st.columns(min(4, max(1, len(report.get("sources", [])))))
        for index, source in enumerate(report.get("sources", [])):
            with source_cols[index % len(source_cols)]:
                st.metric(
                    source.get("source_id", "Quelle"),
                    f"{source.get('new', 0)} جدید",
                    delta=f"{source.get('changed', 0)} تغییر",
                )
                st.caption(f"وضعیت: {source.get('status')} · دیده‌شده: {source.get('seen', 0)}")

    stats = db.stats()
    metric_cols = st.columns(4)
    metric_cols[0].metric("فرصت‌های ثبت‌شده", stats["total"])
    metric_cols[1].metric("فرصت‌های باز", stats["open"])
    metric_cols[2].metric("جدید در ۲۴ ساعت", stats["new_24h"])
    metric_cols[3].metric("تغییرکرده در ۷ روز", stats["changed_7d"])

    st.divider()
    st.markdown("**فیلتر بانک فرصت‌ها**")
    f1, f2, f3 = st.columns(3)
    query = f1.text_input("جست‌وجوی متن", key="opp_search_text")
    selected_category = f2.selectbox(
        "حوزه",
        ["Alle", "Reinigung", "Sicherheit", "Facility Management", "Bau / Handwerk", "Unbekannt"],
        key="opp_filter_category",
    )
    selected_status = f3.selectbox("وضعیت", ["Alle", "open", "closed", "unknown"], key="opp_filter_status")
    include_jobs = st.checkbox("نمایش آگهی‌های استخدامی (به‌طور پیش‌فرض پنهان)", value=False)
    rows = db.list_opportunities(
        query=query,
        category=selected_category,
        status=selected_status,
        include_jobs=include_jobs,
        limit=2000,
    )
    if rows:
        display_rows = []
        for row in rows:
            display_rows.append({
                "امتیاز": row["score"],
                "عنوان": row["title"],
                "نوع": row["opportunity_type"],
                "حوزه": row["category"],
                "سفارش‌دهنده": row["buyer"] or "اعلام نشده",
                "شهر": row["city"] or "نیازمند بررسی",
                "انتشار": row["publication_date"] or "نامشخص",
                "مهلت": row["deadline"] or "اعلام نشده",
                "ارزش": f"{row['estimated_value']} {row['currency']}" if row["estimated_value"] else "اعلام نشده",
                "وضعیت": row["status"],
                "تعداد منابع": row["source_count"],
                "لینک": row["url"] or "",
            })
        st.dataframe(
            display_rows,
            use_container_width=True,
            hide_index=True,
            column_config={
                "لینک": st.column_config.LinkColumn("اصل آگهی"),
                "امتیاز": st.column_config.NumberColumn("امتیاز", min_value=0, max_value=100),
            },
        )
        st.download_button(
            "خروجی کامل فرصت‌ها (CSV)",
            data=_csv_bytes(rows),
            file_name="reinigungsradar_opportunities.csv",
            mime="text/csv",
        )
        with st.expander("دلایل رتبه‌بندی و شواهد"):
            for row in rows[:40]:
                st.markdown(f"**{row['title']}** · {row['score']}/100")
                st.caption(row.get("score_reason") or "هنوز شواهد کافی ثبت نشده است.")
                if row.get("url"):
                    st.markdown(f"[بازکردن منبع اصلی]({row['url']})")
    else:
        st.info("هنوز فرصتی در بانک ثبت نشده یا فیلتر فعلی نتیجه‌ای ندارد. جست‌وجو را از بالا اجرا کنید.")

    st.divider()
    st.markdown("**سلامت منابع و خطاهای اخیر**")
    sources = db.list_sources()
    if sources:
        source_rows = [{
            "منبع": item["name"],
            "شناسه": item["source_id"],
            "نوع": item["kind"],
            "دسترسی": item["access_mode"],
            "وضعیت آخر": item["last_status"],
            "آخرین اجرا": item["last_run_at"] or "هنوز اجرا نشده",
            "تعداد آخرین اجرا": item["last_count"],
            "خطا": item["last_error"] or "",
        } for item in sources]
        st.dataframe(source_rows, use_container_width=True, hide_index=True)

    changes = db.recent_changes(30)
    if changes:
        with st.expander(f"تاریخچهٔ تغییرات ({len(changes)} مورد اخیر)"):
            st.dataframe(
                [{
                    "زمان": item["changed_at"],
                    "آگهی": item["title"],
                    "فیلد": item["field"],
                    "مقدار قبلی": item["old_value"],
                    "مقدار جدید": item["new_value"],
                    "منبع": item["source_id"],
                    "لینک": item["url"] or "",
                } for item in changes],
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.markdown("**پورتال‌های تکمیلی برای بررسی دستی**")
    link_cols = st.columns(4)
    for index, (label, url) in enumerate(MANUAL_LINKS):
        link_cols[index].link_button(label, url, use_container_width=True)
    st.caption(
        "Auftragsbank و پلتفرم‌های حساب‌محور در این نسخه خودکار scrape نمی‌شوند؛ "
        "برای اتصال خودکار باید API یا اجازهٔ صریح دسترسی داشته باشیم."
    )
    st.warning(
        "این موتور فرصت‌ها را پیدا و اولویت‌بندی می‌کند؛ صحت، شرایط شرکت در مناقصه، "
        "اسناد اصلی و مهلت‌ها باید پیش از هر تصمیم توسط کاربر بررسی شوند. "
        "هیچ پیام، پیشنهاد یا تماس خودکاری ارسال نمی‌شود."
    )
