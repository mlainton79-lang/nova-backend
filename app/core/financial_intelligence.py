"""
Tony's Financial Intelligence Engine.

No bank access needed. Tony builds Matthew's financial picture
from email receipts, payment notifications, and correspondence.

Tony reads:
- PayPal payment confirmations
- eBay/Vinted sale notifications  
- Universal Credit emails
- Bill notifications (energy, phone, etc)
- Bank statement summary emails
- Any email with monetary amounts

Over time Tony builds:
- Estimated monthly income (shifts + selling)
- Known outgoings (bills, debts)
- Trend analysis (is money situation improving?)
- Specific alerts (low balance indicators, missed payments)

This gives Tony genuine financial awareness without needing
direct bank access.
"""
import os
import re
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from app.core.model_router import gemini_json, gemini

def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


def init_financial_tables():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_financial_events (
                id SERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                amount FLOAT,
                direction TEXT,  -- 'in' or 'out'
                source TEXT,
                description TEXT,
                event_date DATE,
                raw_email_subject TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_financial_summary (
                id SERIAL PRIMARY KEY,
                period TEXT NOT NULL UNIQUE,
                estimated_income FLOAT,
                known_outgoings FLOAT,
                selling_income FLOAT,
                trend TEXT,
                notes TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[FINANCIAL_INTEL] Tables initialised")
    except Exception as e:
        print(f"[FINANCIAL_INTEL] Init failed: {e}")


FINANCIAL_EMAIL_KEYWORDS = [
    "payment", "invoice", "receipt", "paid", "transfer",
    "refund", "credit", "debit", "balance", "statement",
    "vinted", "ebay", "paypal", "sold", "purchase",
    "universal credit", "pip", "hmrc", "tax credit",
    "direct debit", "standing order", "overdue", "reminder",
    # no hardcoded topics; debts are tracked generically from transactions
]


async def extract_financial_data_from_email(email: Dict) -> Optional[Dict]:
    """
    Extract financial information from a single email.
    """
    subject = email.get("subject", "")
    snippet = email.get("snippet", "")
    body = email.get("body", snippet)

    # Quick filter - is this financially relevant?
    combined = (subject + " " + body).lower()
    if not any(kw in combined for kw in FINANCIAL_EMAIL_KEYWORDS):
        return None

    prompt = f"""Extract financial information from this email.

Subject: {subject}
Content: {body[:500]}

Extract any financial data present:
- Amount (number only, no £ symbol)
- Direction: 'in' (money received) or 'out' (money paid/owed)
- Type: sale/payment/bill/credit/debt/refund/salary/other
- Source: who sent/received the money

If no financial data: return null.

Respond in JSON:
{{
    "amount": 0.00,
    "direction": "in/out",
    "type": "sale/payment/bill/credit/debt/refund/salary/other",
    "source": "company or person name",
    "description": "brief description"
}}

Or: null"""

    result = await gemini_json(prompt, task="analysis", max_tokens=200, temperature=0.1)
    
    if result and result.get("amount"):
        result["email_subject"] = subject[:100]
        result["date"] = email.get("date", "")[:10]
    
    return result if (result and result.get("amount")) else None


async def scan_emails_for_financial_data() -> List[Dict]:
    """Scan recent emails for financial information."""
    financial_events = []
    
    try:
        from app.core.gmail_service import search_all_accounts
        
        # Search for financial emails
        queries = [
            "PayPal OR Vinted OR eBay payment sold",
            "universal credit OR HMRC OR tax",
            "invoice OR receipt OR paid",
            "direct debit OR standing order OR overdue",
        ]
        
        all_emails = []
        for query in queries[:2]:
            emails = await search_all_accounts(query, max_per_account=10)
            all_emails.extend(emails)
        
        # Process each email
        for email in all_emails[:20]:
            data = await extract_financial_data_from_email(email)
            if data:
                financial_events.append(data)
                
                # Store in DB
                try:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT INTO tony_financial_events
                        (event_type, amount, direction, source, description, event_date, raw_email_subject)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        data.get("type", "other"),
                        data.get("amount", 0),
                        data.get("direction", "out"),
                        data.get("source", "")[:100],
                        data.get("description", "")[:200],
                        data.get("date") or datetime.utcnow().date(),
                        data.get("email_subject", "")[:100]
                    ))
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass
    
    except Exception as e:
        print(f"[FINANCIAL_INTEL] Email scan failed: {e}")
    
    return financial_events


async def build_financial_picture() -> Dict:
    """
    Build a complete financial picture from all available data.
    """
    try:
        conn = get_conn()
        cur = conn.cursor()
        
        # Last 30 days
        cur.execute("""
            SELECT event_type, amount, direction, source
            FROM tony_financial_events
            WHERE event_date > NOW() - INTERVAL '30 days'
            ORDER BY event_date DESC
        """)
        events = cur.fetchall()
        cur.close()
        conn.close()
        
        if not events:
            return {"status": "no_data", "message": "No financial emails found yet"}
        
        income = sum(e[1] for e in events if e[2] == 'in' and e[1])
        outgoings = sum(e[1] for e in events if e[2] == 'out' and e[1])
        selling = sum(e[1] for e in events if e[2] == 'in' and e[0] in ('sale', 'refund') and e[1])
        
        events_text = "\n".join(
            f"- {e[2].upper()} £{e[1]:.2f} from {e[3]} ({e[0]})"
            for e in events[:10] if e[1]
        )
        
        prompt = f"""Based on Matthew's financial email data, assess his financial health.

Last 30 days financial events:
{events_text}

Estimated:
- Money in: £{income:.2f}
- Money out: £{outgoings:.2f}
- From selling (Vinted/eBay): £{selling:.2f}

Matthew's context: Night shift care worker in Rotherham, wife and 2 young daughters.

Provide financial intelligence:

JSON response:
{{
    "monthly_surplus_estimate": "£X surplus/deficit",
    "selling_performance": "how Vinted/eBay income looks",
    "concerns": ["specific financial concerns"],
    "positive_signals": ["good financial signals"],
    "advice": "most important financial action this week",
    "trend": "improving/stable/concerning"
}}"""

        assessment = await gemini_json(prompt, task="reasoning", max_tokens=512)
        
        if assessment:
            # Update summary
            try:
                conn = get_conn()
                cur = conn.cursor()
                period = datetime.utcnow().strftime("%Y-%m")
                cur.execute("""
                    INSERT INTO tony_financial_summary
                    (period, estimated_income, known_outgoings, selling_income, trend, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (period) DO UPDATE SET
                        estimated_income = EXCLUDED.estimated_income,
                        known_outgoings = EXCLUDED.known_outgoings,
                        selling_income = EXCLUDED.selling_income,
                        trend = EXCLUDED.trend,
                        notes = EXCLUDED.notes,
                        updated_at = NOW()
                """, (
                    period, income, outgoings, selling,
                    assessment.get("trend", "unknown"),
                    assessment.get("advice", "")[:300]
                ))
                conn.commit()
                cur.close()
                conn.close()
            except Exception:
                pass
            
            # Update living memory with financial picture
            try:
                from app.core.living_memory import update_section
                update_section(
                    "FINANCIAL",
                    f"Last 30 days: Income £{income:.0f}, Outgoings £{outgoings:.0f}, Selling £{selling:.0f}. "
                    f"Trend: {assessment.get('trend', 'unknown')}. "
                    f"{assessment.get('advice', '')[:100]}"
                )
            except Exception:
                pass
        
        return {
            "income": income,
            "outgoings": outgoings,
            "selling": selling,
            "assessment": assessment or {},
            "events_processed": len(events)
        }
    
    except Exception as e:
        print(f"[FINANCIAL_INTEL] Picture build failed: {e}")
        return {}


async def run_financial_intelligence() -> Dict:
    """Full financial intelligence run."""
    print("[FINANCIAL_INTEL] Scanning for financial data...")
    
    # Scan emails
    events = await scan_emails_for_financial_data()
    print(f"[FINANCIAL_INTEL] Found {len(events)} financial events")
    
    # Build picture
    picture = await build_financial_picture()
    
    # Alert if concerning
    if picture.get("assessment", {}).get("trend") == "concerning":
        try:
            from app.core.proactive import create_alert
            create_alert(
                alert_type="financial_concern",
                title="Tony: Financial concern detected",
                body=picture["assessment"].get("advice", "Review your finances"),
                priority="high",
                source="financial_intelligence"
            )
        except Exception:
            pass
    
    return {"events": len(events), "picture": picture}
