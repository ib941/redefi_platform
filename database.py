import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker

# Establish a permanent localized cryptographic database file on your disk
DATABASE_URL = "sqlite:///redefi_bank.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 👥 TABLE 1: User Account Identities
class UserNode(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    username = Column(String)
    balance = Column(Float, default=10000.00)

# 📊 TABLE 2: Public Master Ledger History
class BlockTransaction(Base):
    __tablename__ = "blockchain_ledger"
    
    id = Column(Integer, primary_key=True, index=True)
    serial_number = Column(String, unique=True, index=True)
    sender = Column(String)
    recipient_name = Column(String)
    recipient_address = Column(String)
    amount = Column(Integer)
    currency = Column(String)
    gas_fee = Column(Float)
    routing_fee = Column(Float)
    total = Column(Float)
    status = Column(String)
    send_time = Column(String)
    receive_time = Column(String)
    log_action = Column(String)

# Compile and initialize all tables on your local disk storage
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()