import os
import random
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from sqlalchemy.orm import Session

import database
from database import UserNode, BlockTransaction, get_db

database.init_db()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Load secure cloud environment keys
API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)
CURRENT_SESSION = {"email": None}

OTP_STORE = {}

CONTACTS = {
    "mum": {"label": "Mum / Mother", "address": "0x771_MOM_Escrow_Node89b"},
    "dad": {"label": "Dad / Father", "address": "0x224_DAD_Settlement_Node15f"},
    "bro": {"label": "Brother / Bro", "address": "0x993_BRO_Liquidity_Node01a"},
    "mohammed": {"label": "Mohammed / Friend", "address": "0x552_MOHAMMED_Wallet4e"},
    "friend": {"label": "General Friend Node", "address": "0x883_FRIEND_Channel01c"}
}

# 🔐 DEMO SAFETY NET: Auto-builds the profile if Render's virtual drive wipes the SQLite file
def get_or_create_demo_user(db: Session, email: str):
    target_email = email if email else "ibrahim@google.com"
    user = db.query(UserNode).filter(UserNode.email == target_email).first()
    if not user:
        user = UserNode(email=target_email, password="leogoat10", username="ibra", balance=10000.00)
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
        send_time = base_time + timedelta(hours=i*3, minutes=random.randint(1,59))
        receive_time = send_time + timedelta(seconds=random.randint(2, 8))
        
        tx_block = BlockTransaction(
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
            log_action="✅ SETTLED SUCCESSFUL" if amount <= 10000 else "🚨 AML LOCK TRIGGERED"
        )
        db.add(tx_block)
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

class RegisterSchema(BaseModel):
    email: str
    password: str
    username: str

class OTPRequestSchema(BaseModel):
    email: str

class OTPVerifySchema(BaseModel):
    email: str
    code: str

class TransactionInputSchema(BaseModel):
    text: str

class AIParserOutputSchema(BaseModel):
    amount: int
    currency: str
    recipient: str

@app.post("/auth/register")
def register_node(data: RegisterSchema, db: Session = Depends(get_db)):
    existing = db.query(UserNode).filter(UserNode.email == data.email).first()
    if existing:
        return {"status": "success"}
    new_user = UserNode(email=data.email, password=data.password, username=data.username)
    db.add(new_user)
    db.commit()
    return {"status": "success"}

@app.post("/auth/request-otp")
def request_otp(data: OTPRequestSchema, db: Session = Depends(get_db)):
    get_or_create_demo_user(db, data.email)
    secure_code = "123456"
    OTP_STORE[data.email] = secure_code
    return {"status": "success", "message": "Master bypass code initialized."}

@app.post("/auth/verify-otp")
def verify_otp(data: OTPVerifySchema, db: Session = Depends(get_db)):
    if data.email not in OTP_STORE or OTP_STORE[data.email] != data.code.strip():
        raise HTTPException(status_code=401, detail="Invalid verification code token.")
    
    del OTP_STORE[data.email]
    CURRENT_SESSION["email"] = data.email
    user = get_or_create_demo_user(db, data.email)
    seed_simulation_data(db)
    return {"status": "success", "username": user.username, "balance": user.balance}

@app.get("/ledger/user")
def fetch_user_ledger(db: Session = Depends(get_db)):
    email = CURRENT_SESSION["email"] or "ibrahim@google.com"
    user = get_or_create_demo_user(db, email)
    personal_txs = db.query(BlockTransaction).filter(BlockTransaction.sender == user.username).order_by(BlockTransaction.serial_number.desc()).all()
    return {"ledger": personal_txs, "contacts": CONTACTS}

@app.get("/ledger/admin")
def fetch_admin_ledger(code: str, db: Session = Depends(get_db)):
    if code != "LEO_OPERATIONS_2026": 
        raise HTTPException(status_code=403, detail="Access Denied.")
    master_ledger = db.query(BlockTransaction).order_by(BlockTransaction.serial_number.desc()).all()
    return {"ledger": master_ledger}

@app.post("/transfer/process")
def process_slang_remittance(data: TransactionInputSchema, db: Session = Depends(get_db)):
    email = CURRENT_SESSION["email"] or "ibrahim@google.com"
    user_account = get_or_create_demo_user(db, email)

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"""
            Analyze this casual financial instruction string: "{data.text}"
            1. Extract the amount value strictly as a clean integer whole number.
            2. Extract the currency intended. Map it strictly to its official 3-letter currency code (e.g., 'riyals' or 'sar' -> 'SAR', 'pounds' or 'gbp' -> 'GBP', 'euros' or 'eur' -> 'EUR', 'dollars' or 'bucks' or 'chips' -> 'USD'). If unspecified, default to 'USD'.
            3. Map the slang recipient entity to one of our exact database keys: ['mum', 'dad', 'bro', 'mohammed', 'friend'].
                LINGUISTIC MAP GUIDELINE:
               - Variations like 'momma', 'mom', 'mother', 'mum', 'mummy', 'old lady', 'queen' -> 'mum'
               - Variations like 'dad', 'father', 'poppa', 'pops', 'old man' -> 'dad'
               - Variations like 'brother', 'bro', 'bruh', 'sib' -> 'bro'
               - Variations like 'mohammed', 'moe', 'med' -> 'mohammed'
               - Variations like 'friend', 'homie', 'buddy', 'pal' -> 'friend'
            Format response to match the response schema format strictly.
            """,
            config={'response_mime_type': 'application/json', 'response_schema': AIParserOutputSchema},
        )
        extracted = response.parsed
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Engine Exception: {str(e)}")

    amount = extracted.amount
    currency_code = extracted.currency.upper().strip()
    recipient_key = extracted.recipient.lower().strip()

    logs = [
        f"[Context Parsing]: Intent extraction resolved successfully.",
        f"[AI Extraction]: Mapped input to {amount} {currency_code} targeting profile '{recipient_key}'."
    ]

    if recipient_key not in CONTACTS:
        return {"status": "failed", "logs": logs + [f"❌ ROUTING REJECTED: Entity tag '{recipient_key}' unresolved."]}

    live_rate = get_live_exchange_rate(currency_code)
    amount_in_usd = round(amount * live_rate, 2)
    logs.append(f"[💱 Live FX Rate]: Fetched market price. 1 {currency_code} = ${live_rate:.4f} USD. Equivalent: ${amount_in_usd:.2f} USD.")

    network_gas_fee = 15.00
    cross_border_settlement_fee = round(amount_in_usd * 0.01, 2)
    total_required_outflow = amount_in_usd + network_gas_fee + cross_border_settlement_fee

    if total_required_outflow > user_account.balance:
        return {"status": "failed", "logs": logs + [f"❌ LIQUIDITY REJECTION: Outflow required exceeds user capacity."]}

    send_time = datetime.now()
    receive_time = send_time + timedelta(seconds=random.randint(2, 5))
    total_existing_blocks = db.query(BlockTransaction).count()

    if amount_in_usd > 10000:
        action_message = f"🚨 FRAUD BLOCK WARNING: Principal value exceeds $10,000 safety limit. HELD."
        transaction_status = "flagged"
        status_label = "Flagged"
    else:
        user_account.balance = round(user_account.balance - total_required_outflow, 2)
        action_message = f"✅ BLOCK FINALIZED: Successfully compiled blocks. Dispatched settlement assets."
        transaction_status = "success"
        status_label = "Success"

    new_block = BlockTransaction(
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
        log_action=action_message
    )
    
    db.add(new_block)
    db.commit()

    return {"status": transaction_status, "logs": logs, "new_balance": user_account.balance}