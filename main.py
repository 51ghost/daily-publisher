#!/usr/bin/env python3
import os, requests
from datetime import datetime, date
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.environ["SUPABASE_URL"],
                   os.environ["SUPABASE_SERVICE_KEY"])
SCAFFOLD_URL = os.environ["SCAFFOLD_API_URL"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

def notify(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT, "text": msg},
        timeout=10
    )

def already_published_today() -> bool:
    today = date.today().isoformat()
    r = sb.table("android_ideas").select("id")\
          .gte("last_published_at", f"{today}T00:00:00")\
          .limit(1).execute()
    return len(r.data) > 0

def get_best_idea():
    r = sb.table("android_ideas")\
          .select("id,app_name,package_name,"
                  "monetization_score,kotlin_stub,"
                  "design_spec,data_source_url")\
          .eq("publish_status", "ready")\
          .eq("data_verified", True)\
          .order("monetization_score", desc=True)\
          .limit(1).execute()
    return r.data[0] if r.data else None

def validate(idea) -> tuple:
    stub = idea.get("kotlin_stub", "")
    if len(stub) < 500:
        return False, f"kotlin_stub too short ({len(stub)} chars)"
    if "TODO" in stub:
        return False, "kotlin_stub still has TODO comments"
    if not idea.get("package_name"):
        return False, "missing package_name"
    if not idea.get("design_spec"):
        return False, "missing design_spec"
    if not idea.get("data_source_url"):
        return False, "missing data_source_url"
    return True, "ok"

def run():
    print(f"Daily publisher starting: {datetime.now()}")

    if already_published_today():
        msg = "ℹ️ Already published today. Skipping."
        print(msg)
        notify(msg)
        return

    idea = get_best_idea()
    if not idea:
        msg = ("⚠️ No verified ideas in queue.\n"
               "Run Hermes cron manually to generate ideas.")
        print(msg)
        notify(msg)
        return

    valid, reason = validate(idea)
    if not valid:
        print(f"Validation failed: {reason}")
        sb.table("android_ideas").update({
            "publish_status": "validation_failed"
        }).eq("id", idea["id"]).execute()
        notify(f"❌ Validation failed: {idea['app_name']}\n"
               f"Reason: {reason}")
        return

    print(f"Triggering build: {idea['app_name']}")
    notify(f"🚀 Daily publisher triggered\n"
           f"App: {idea['app_name']}\n"
           f"Score: {idea['monetization_score']}/10\n"
           f"Starting scaffold and build now...")

    r = requests.post(
        f"{SCAFFOLD_URL}/build/{idea['id']}",
        headers={"x-webhook-secret": WEBHOOK_SECRET},
        timeout=30
    )

    if r.status_code == 200:
        print(f"Build triggered successfully for {idea['app_name']}")
    else:
        print(f"Scaffold API error: {r.status_code} {r.text}")
        notify(f"❌ Scaffold API error: {r.status_code}")

if __name__ == "__main__":
    run()
