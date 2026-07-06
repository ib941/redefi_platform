import os
import random
import secrets
import time
import requests
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database
from database import UserNode, BlockTransaction, get_db, hash_password, verify_password

database.init_db()
app = FastAPI()

# --- CORS ---
# "*" combined with allow_credentials=True is invalid in most browsers and,
# where it isn't rejected outright, it lets ANY website read responses from
# this API on behalf of a logged-in user. Lock this to your real frontend.
FRONTEND_ORIGINS = [
    "https://ib941.github.io",
    "http://localhost:5500",   # local dev (e.g. VS Code Live Server)
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SECRETS / CONFIG ---
API_KEY = os.getenv("GEMINI_API_KEY", "")
ADMIN_ACCESS_KEY = os.getenv("ADMIN_ACCESS_KEY", "")  # set this in Render's env vars, never in code

CURRENT_SESSION = {"email": None}

# OTP_STORE[email] = {"code": str, "expires": datetime, "attempts": int, "last_sent": datetime}
OTP_STORE = {}
OTP_TTL_SECONDS = 300          # code valid for 5 minutes
OTP_RESEND_COOLDOWN = 45       # seconds between resend requests
OTP_MAX_ATTEMPTS = 5           # wrong guesses allowed before the code is killed

CONTACTS = {
    "mum": {"label": "Mum / Mother", "address": "0x771_MOM_Escrow_Node89b"},
    "dad": {"label": "Dad / Father", "address": "0x224_DAD_Settlement_Node15f"},
    "bro": {"label": "Brother / Bro", "address": "0x993_BRO_Liquidity_Node01a"},
    "mohammed": {"label": "Mohammed / Friend", "address": "0x552_MOHAMMED_Wallet4e"},
    "friend": {"label": "General Friend Node", "address": "0x883_FRIEND_Channel01c"},
}


# 🔐 DEMO SAFETY NET: rebuilds the profile if Render's ephemeral disk wipes the SQLite file.
# Kept intentional for a zero-budget demo, but note this is a demo convenience,
# not something a real bank would ever do (free balance on lookup).
def get_or_create_demo_user(db: Session, email: str):
    target_email = email if email else "ibrahim@google.com"
    user = db.query(UserNode).filter(UserNode.email == target_email).first()
    if not user:
        user = UserNode(
            email=target_email,
            password_hash=hash_password("leogoat10"),
            username="ibra",
            balance=10000.00,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def seed_simulation_data(db: Session):
    if db.query(BlockTransaction).count() > 0:
        return
    names = ["Sarah", "John", "Ali", "Fatima", "David"]
    relations = ["mum", "dad", "bro", "friend"]
    base_time = datetime.now() - timedelta(days=2)

    for i in range(15):
        sender = random.choice(names)
        rel = random.choice(relations)
        amount = random.choice([250, 1200, 4500, 7200, 11500])
        send_time = base_time + timedelta(hours=i * 3, minutes=random.randint(1, 59))
        receive_time = send_time + timedelta(seconds=random.randint(2, 8))

        db.add(BlockTransaction(
            serial_number=f"TX-{104800 + i}",
            sender=sender,
            recipient_name=CONTACTS[rel]["label"],
            recipient_address=CONTACTS[rel]["address"],
            amount=amount,
            currency="USDC",
            gas_fee=15.00,
            routing_fee=round(amount * 0.01, 2),
            total=amount + 15.00 + round(amount * 0.01, 2),
            status="Success" if amount <= 10000 else "Flagged",
            send_time=send_time.strftime("%Y-%m-%d %H:%M:%S"),
            receive_time=receive_time.strftime("%Y-%m-%d %H:%M:%S") if amount <= 10000 else "N/A (HELD)",
            log_action="✅ SETTLED SUCCESSFUL" if amount <= 10000 else "🚨 AML LOCK TRIGGERED",
        ))
    db.commit()


def get_live_exchange_rate(target_currency: str):
    currency_code = target_currency.upper().strip()
    if currency_code in ["USD", "USDC", "USDT"]:
        return 1.0
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            rates = response.json().get("rates", {})
            if currency_code in rates:
                return 1 / rates[currency_code]
        return {"SAR": 0.27, "GBP": 1.26, "EUR": 1.08}.get(currency_code, 1.0)
    except Exception:
        return {"SAR": 0.27, "GBP": 1.26, "EUR": 1.08}.get(currency_code, 1.0)


def call_gemini(prompt_text: str, response_schema: dict | None = None):
    """Shared helper for all Gemini calls in this service."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API token missing from cluster host.")

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    # Both Standard (AIzaSy...) and Auth (AQ....) keys use the same header today.
    # Do NOT use Authorization: Bearer or a ?key= query param for either format —
    # x-goog-api-key is what Google's own current docs specify for both.
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY,
    }

    generation_config = {}
    if response_schema:
        generation_config = {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        }

    payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": generation_config,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=f"Google Gateway Response: {response.text}")

    raw_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(raw_text) if response_schema else raw_text


# --- SCHEMAS ---
class RegisterSchema(BaseModel):
    email: str
    password: str
    username: str


class LoginSchema(BaseModel):
    email: str
    password: str


class OTPVerifySchema(BaseModel):
    email: str
    code: str


class TransactionInputSchema(BaseModel):
    text: str


class SupportQuestionSchema(BaseModel):
    question: str


# --- AUTH: REGISTER ---
@app.post("/auth/register")
def register_node(data: RegisterSchema, db: Session = Depends(get_db)):
    existing = db.query(UserNode).filter(UserNode.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    db.add(UserNode(
        email=data.email,
        password_hash=hash_password(data.password),
        username=data.username,
    ))
    db.commit()
    return {"status": "success"}


# --- AUTH: LOGIN (verifies password, THEN issues an OTP) ---
@app.post("/auth/login")
def login_node(data: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(UserNode).filter(UserNode.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        # Same error for "no such user" and "wrong password" — don't reveal which one
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    existing = OTP_STORE.get(data.email)
    now = datetime.now()
    if existing and (now - existing["last_sent"]).total_seconds() < OTP_RESEND_COOLDOWN:
        wait = OTP_RESEND_COOLDOWN - int((now - existing["last_sent"]).total_seconds())
        raise HTTPException(status_code=429, detail=f"Please wait {wait}s before requesting another code.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    OTP_STORE[data.email] = {
        "code": code,
        "expires": now + timedelta(seconds=OTP_TTL_SECONDS),
        "attempts": 0,
        "last_sent": now,
    }

    # Zero-budget email workaround: printed codes land in Render's live log stream.
    # Swap this for a real email/SMS provider (e.g. Resend, Twilio) once you have one.
    print(f"[OTP DISPATCH] {data.email} -> {code} (expires in {OTP_TTL_SECONDS}s)")

    return {"status": "otp_sent", "message": "A verification code has been dispatched."}


# --- AUTH: VERIFY OTP ---
@app.post("/auth/verify-otp")
def verify_otp(data: OTPVerifySchema, db: Session = Depends(get_db)):
    record = OTP_STORE.get(data.email)
    if not record:
        raise HTTPException(status_code=401, detail="No active verification request for this email.")

    if datetime.now() > record["expires"]:
        del OTP_STORE[data.email]
        raise HTTPException(status_code=401, detail="Verification code expired. Please log in again.")

    if record["attempts"] >= OTP_MAX_ATTEMPTS:
        del OTP_STORE[data.email]
        raise HTTPException(status_code=429, detail="Too many incorrect attempts. Please log in again.")

    if record["code"] != data.code.strip():
        record["attempts"] += 1
        raise HTTPException(status_code=401, detail="Invalid verification code.")

    del OTP_STORE[data.email]
    CURRENT_SESSION["email"] = data.email
    user = get_or_create_demo_user(db, data.email)
    seed_simulation_data(db)
    return {"status": "success", "username": user.username, "balance": user.balance}


# --- LEDGER: USER ---
@app.get("/ledger/user")
def fetch_user_ledger(db: Session = Depends(get_db)):
    email = CURRENT_SESSION["email"] or "ibrahim@google.com"
    user = get_or_create_demo_user(db, email)
    personal_txs = (
        db.query(BlockTransaction)
        .filter(BlockTransaction.sender == user.username)
        .order_by(BlockTransaction.serial_number.desc())
        .all()
    )
    return {"ledger": personal_txs, "contacts": CONTACTS}


# --- LEDGER: ADMIN (header-based key, fails closed if unconfigured) ---
@app.get("/ledger/admin")
def fetch_admin_ledger(db: Session = Depends(get_db), x_admin_key: str = Header(default="")):
    if not ADMIN_ACCESS_KEY:
        raise HTTPException(status_code=503, detail="Admin access is not configured on this deployment.")
    if x_admin_key != ADMIN_ACCESS_KEY:
        raise HTTPException(status_code=403, detail="Access denied.")
    return {"ledger": db.query(BlockTransaction).order_by(BlockTransaction.serial_number.desc()).all()}


# --- AI: SLANG PAYMENT GATEWAY ---
@app.post("/transfer/process")
def process_slang_remittance(data: TransactionInputSchema, db: Session = Depends(get_db)):
    email = CURRENT_SESSION["email"] or "ibrahim@google.com"
    user_account = get_or_create_demo_user(db, email)

    prompt = f"""
Analyze this casual financial instruction string: "{data.text}"
1. Extract the amount value strictly as a clean integer whole number.
2. Extract the currency intended. Map it strictly to its official 3-letter currency code
   (e.g., 'riyals' or 'sar' -> 'SAR', 'pounds' or 'gbp' -> 'GBP', 'euros' or 'eur' -> 'EUR',
   'dollars' or 'bucks' or 'chips' -> 'USD'). If unspecified, default to 'USD'.
3. Map the slang recipient entity to one of our exact database keys:
   ['mum', 'dad', 'bro', 'mohammed', 'friend'].
   - 'momma', 'mom', 'mother', 'mum', 'mummy', 'old lady', 'queen' -> 'mum'
   - 'dad', 'father', 'poppa', 'pops', 'old man' -> 'dad'
   - 'brother', 'bro', 'bruh', 'sib' -> 'bro'
   - 'mohammed', 'moe', 'med' -> 'mohammed'
   - 'friend', 'homie', 'buddy', 'pal' -> 'friend'
Format response to match the response schema strictly.
"""
    schema = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer"},
            "currency": {"type": "string"},
            "recipient": {"type": "string"},
        },
        "required": ["amount", "currency", "recipient"],
    }

    try:
        extracted = call_gemini(prompt, schema)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Adaptive Semantic Pipeline Failure: {str(e)}")

    amount = extracted.get("amount", 0)
    currency_code = extracted.get("currency", "USD").upper().strip()
    recipient_key = extracted.get("recipient", "friend").lower().strip()

    logs = [
        "[Context Parsing]: Intent extraction resolved successfully.",
        f"[AI Extraction]: Mapped input to {amount} {currency_code} targeting profile '{recipient_key}'.",
    ]

    if recipient_key not in CONTACTS:
        return {"status": "failed", "logs": logs + [f"❌ ROUTING REJECTED: Entity tag '{recipient_key}' unresolved."]}

    live_rate = get_live_exchange_rate(currency_code)
    amount_in_usd = round(amount * live_rate, 2)
    logs.append(f"[💱 Live FX Rate]: 1 {currency_code} = ${live_rate:.4f} USD. Equivalent: ${amount_in_usd:.2f} USD.")

    network_gas_fee = 15.00
    cross_border_settlement_fee = round(amount_in_usd * 0.01, 2)
    total_required_outflow = amount_in_usd + network_gas_fee + cross_border_settlement_fee

    if total_required_outflow > user_account.balance:
        return {"status": "failed", "logs": logs + ["❌ LIQUIDITY REJECTION: Outflow required exceeds user capacity."]}

    send_time = datetime.now()
    receive_time = send_time + timedelta(seconds=random.randint(2, 5))
    total_existing_blocks = db.query(BlockTransaction).count()

    if amount_in_usd > 10000:
        action_message = "🚨 FRAUD BLOCK WARNING: Principal value exceeds $10,000 safety limit. HELD."
        transaction_status, status_label = "flagged", "Flagged"
    else:
        user_account.balance = round(user_account.balance - total_required_outflow, 2)
        action_message = "✅ BLOCK FINALIZED: Successfully compiled blocks. Dispatched settlement assets."
        transaction_status, status_label = "success", "Success"

    db.add(BlockTransaction(
        serial_number=f"TX-{total_existing_blocks + 104800}",
        sender=user_account.username,
        recipient_name=CONTACTS[recipient_key]["label"],
        recipient_address=CONTACTS[recipient_key]["address"],
        amount=amount,
        currency=currency_code,
        gas_fee=network_gas_fee,
        routing_fee=cross_border_settlement_fee,
        total=total_required_outflow,
        status=status_label,
        send_time=send_time.strftime("%Y-%m-%d %H:%M:%S"),
        receive_time=receive_time.strftime("%Y-%m-%d %H:%M:%S") if status_label == "Success" else "N/A (HELD)",
        log_action=action_message,
    ))
    db.commit()

    return {"status": transaction_status, "logs": logs, "new_balance": user_account.balance}


# --- AI: COMPLIANCE COPILOT ---
# Turns a flagged transaction into a plain-English explanation + recommended
# next step, the way a real compliance analyst copilot would (uncle's point #2/#8).
@app.post("/compliance/explain/{serial_number}")
def explain_flagged_transaction(serial_number: str, db: Session = Depends(get_db)):
    tx = db.query(BlockTransaction).filter(BlockTransaction.serial_number == serial_number).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    if tx.compliance_note:
        return {"serial_number": serial_number, "note": tx.compliance_note, "cached": True}

    prompt = f"""
You are a compliance copilot for a remittance platform. A transaction was flagged
by an automated rule. Write a short (3-4 sentence) plain-English note for a human
compliance officer covering: (1) why it was likely flagged, given the data below,
and (2) one concrete recommended next action (e.g. request source-of-funds document,
escalate to senior review, clear as false positive). Be concise and factual, do not
invent facts not implied by the data.

Transaction data:
- Serial: {tx.serial_number}
- Sender: {tx.sender}
- Recipient: {tx.recipient_name}
- Amount: {tx.amount} {tx.currency}
- Total outflow: {tx.total}
- Status: {tx.status}
- Sent at: {tx.send_time}
"""
    note = call_gemini(prompt)
    tx.compliance_note = note.strip()
    db.commit()
    return {"serial_number": serial_number, "note": tx.compliance_note, "cached": False}


# --- AI: CUSTOMER SUPPORT Q&A ---
# Answers natural-language questions using only the logged-in user's real
# ledger data (uncle's point #3 — "where is my money?" style questions).
@app.post("/support/ask")
def support_ask(data: SupportQuestionSchema, db: Session = Depends(get_db)):
    email = CURRENT_SESSION["email"] or "ibrahim@google.com"
    user = get_or_create_demo_user(db, email)
    recent_txs = (
        db.query(BlockTransaction)
        .filter(BlockTransaction.sender == user.username)
        .order_by(BlockTransaction.serial_number.desc())
        .limit(10)
        .all()
    )

    tx_summary = "\n".join(
        f"- {tx.serial_number}: {tx.amount} {tx.currency} to {tx.recipient_name}, "
        f"status={tx.status}, sent={tx.send_time}, received={tx.receive_time}"
        for tx in recent_txs
    ) or "No transactions on record."

    prompt = f"""
You are a remittance customer support assistant. Answer the customer's question
using ONLY the account data below. If the answer isn't in the data, say so honestly
rather than guessing. Keep the answer to 2-3 sentences, friendly and direct.

Account balance: ${user.balance}
Recent transactions:
{tx_summary}

Customer question: "{data.question}"
"""
    answer = call_gemini(prompt)
    return {"answer": answer.strip()}