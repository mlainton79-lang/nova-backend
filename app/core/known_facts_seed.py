"""
Known Facts Seeding — one-time bootstrap of facts that matter.

The fact_extractor is conversation-driven: it only learns when Matthew 
says something. But some facts are too important to wait for — family
relationships, maiden names, key dates.

This module seeds them explicitly on startup. Idempotent via 
ON CONFLICT DO NOTHING so running repeatedly is safe.

Distinct from fact_extractor (which extracts from conversation) — this is 
bedrock knowledge that anchors everything else.
"""
import os
import psycopg2
from typing import List, Dict


def get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")


# Bedrock facts — things Tony should always know, regardless of conversation history
BEDROCK_FACTS = [
    # Family
    ("Matthew", "wife_is", "Georgina Rose Lainton", 1.0),
    ("Matthew", "daughter_is", "Amelia Jane Lainton", 1.0),
    ("Matthew", "daughter_is", "Margot Rose Lainton", 1.0),
    ("Matthew", "mother_is", "Christine", 1.0),
    ("Matthew", "father_was", "Tony Lainton (passed 2 April 2026)", 1.0),

    ("Georgina", "maiden_name", "Wilkinson", 1.0),
    ("Georgina", "full_name", "Georgina Rose Lainton (née Wilkinson)", 1.0),
    ("Georgina", "relationship_to_matthew", "wife", 1.0),
    ("Georgina", "date_of_birth", "26 February 1992", 1.0),

    ("Amelia", "full_name", "Amelia Jane Lainton", 1.0),
    ("Amelia", "date_of_birth", "7 March 2021", 1.0),
    ("Amelia", "age_as_of_2026", "5", 1.0),
    ("Amelia", "relationship_to_matthew", "eldest daughter", 1.0),

    ("Margot", "full_name", "Margot Rose Lainton", 1.0),
    ("Margot", "date_of_birth", "20 July 2025", 1.0),
    ("Margot", "age_as_of_2026", "9 months", 1.0),
    ("Margot", "relationship_to_matthew", "youngest daughter", 1.0),

    ("Tony_Lainton", "relationship_to_matthew", "late father", 1.0),
    ("Tony_Lainton", "date_of_birth", "4 June 1945", 1.0),
    ("Tony_Lainton", "date_of_death", "2 April 2026", 1.0),

    # Work
    ("Matthew", "employer", "Sid Bailey Care Home, Brampton (CQC Outstanding)", 1.0),
    ("Matthew", "work_pattern", "3-on/3-off night shifts, 20:00-08:00", 1.0),
    ("Matthew", "work_role", "carer", 1.0),

    # Location
    ("Matthew", "home", "61 Swangate, Brampton Bierlow, Rotherham S63 6ER", 1.0),
    ("Matthew", "hometown", "Stafford (grew up)", 1.0),

    # Projects
    ("Matthew", "building", "Nova — AI assistant app with Tony identity", 1.0),
]


def seed_bedrock_facts() -> Dict:
    """Ensure all bedrock facts are stored. Idempotent."""
    try:
        conn = get_conn()
        conn.autocommit = True
        cur = conn.cursor()

        # Make sure the table exists — defensive, should already be init'd
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tony_facts (
                id SERIAL PRIMARY KEY,
                subject TEXT,
                predicate TEXT,
                object TEXT,
                confidence NUMERIC(3, 2) DEFAULT 0.7,
                source TEXT DEFAULT 'bedrock',
                created_at TIMESTAMP DEFAULT NOW(),
                superseded_by INT REFERENCES tony_facts(id)
            )
        """)

        seeded = 0
        already = 0
        for subject, predicate, obj, confidence in BEDROCK_FACTS:
            # Check if an identical fact already exists
            cur.execute("""
                SELECT id FROM tony_facts
                WHERE subject = %s AND predicate = %s AND object = %s
                  AND superseded_by IS NULL
                LIMIT 1
            """, (subject, predicate, obj))
            if cur.fetchone():
                already += 1
                continue

            cur.execute("""
                INSERT INTO tony_facts
                    (subject, predicate, object, confidence, source)
                VALUES (%s, %s, %s, %s, 'bedrock')
            """, (subject, predicate, obj, confidence))
            seeded += 1

        cur.close()
        conn.close()
        return {"ok": True, "seeded": seeded, "already_present": already,
                "total_bedrock": len(BEDROCK_FACTS)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
