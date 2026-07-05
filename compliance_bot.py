# The updated function that checks a single amount
def scan_amount(amount):
    if amount > 10000:
        return f"🚨 BLOCKED: ${amount} exceeds the $10k standard ceiling!"
    elif amount > 5000:
        return f"⚠️ WARNING: ${amount} triggered a mid-tier audit flag."
    else:
        return f"✅ APPROVED: ${amount} cleared successfully."

# A fresh batch of global remittance transfers waiting to clear
batch_transfers = [1200, 15000, 4800, 7500, 350]

print("--- STARTING BATCH COMPLIANCE SCAN ---")

# The loop running through every transaction automatically
for current_transfer in batch_transfers:
    scan_result = scan_amount(current_transfer)
    print(scan_result)

print("--- SCAN COMPLETE ---")